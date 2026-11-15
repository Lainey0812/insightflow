"""Startup captures real loaded templates, never synthetic model executions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.observability.provenance import digest
from app.services.prompt_registration import register_loaded_templates
from app.storage.prompt_registry import template_content
from test_prompt_registry import provider


def sources(app):
    return {key: service.prompt_source for key, service in [
        ('intent_parser', app.state.intent_parser), ('analysis_planner', app.state.analysis_planner),
        ('insight_generator', app.state.report_service)]}


def test_startup_three_loaded_versions_readable_and_restart_immutable(tmp_path):
    llm, _, requests = provider(tmp_path/'transport')
    settings = Settings(tmp_path/'app', admin_read_token='read')
    app = create_app(settings, llm)
    repo = app.state.llm_captures.repository
    with TestClient(app) as client:
        catalog = client.get('/admin/prompts', headers={'X-Admin-Token': 'read'}).json()
        assert len(catalog['items']) == 3
        assert all(row['version_count'] == 1 and row['runtime_registration'] == 'registered' for row in catalog['items'])
        original = {key: repo.template(source.snapshot.template_snapshot_id) for key, source in sources(app).items()}
        for key, source in sources(app).items():
            assert original[key].system_template == source.system_prompt
            detail = client.get('/admin/prompts/'+key+'/versions/'+original[key].template_snapshot_id, headers={'X-Admin-Token': 'read'})
            assert detail.status_code == 200
            assert detail.json()['template']['content_hash'] == source.snapshot.content_hash
        assert client.get('/admin/prompts/intent_parser/versions/missing', headers={'X-Admin-Token': 'read'}).status_code == 404
        with closing(repo.connect()) as conn:
            assert conn.execute('SELECT count(*) FROM llm_calls').fetchone()[0] == 0
            assert conn.execute('SELECT count(*) FROM llm_request_snapshots').fetchone()[0] == 0
        assert requests == []
    other = create_app(settings, llm)
    with TestClient(other):
        for key, source in sources(other).items():
            assert other.state.llm_captures.repository.template(source.snapshot.template_snapshot_id) == original[key]
        with closing(repo.connect()) as conn:
            assert conn.execute('SELECT count(*) FROM prompt_templates').fetchone()[0] == 3
    assert requests == []


def test_parallel_startup_registration_is_idempotent(tmp_path):
    llm, _, requests = provider(tmp_path/'transport')
    app = create_app(Settings(tmp_path/'app'), llm)
    repo = app.state.llm_captures.repository
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register_loaded_templates(repo, sources(app)), range(2)))
    assert all(set(result.values()) == {'registered'} for result in results)
    with closing(repo.connect()) as conn:
        assert conn.execute('SELECT count(*) FROM prompt_templates').fetchone()[0] == 3
        assert conn.execute('SELECT count(*) FROM llm_calls').fetchone()[0] == 0
    assert requests == []


def test_version_conflict_preserves_history_and_does_not_claim_registered(tmp_path, caplog):
    llm, _, requests = provider(tmp_path/'transport')
    app = create_app(Settings(tmp_path/'app', admin_read_token='read'), llm)
    repo = app.state.llm_captures.repository
    source = sources(app)['intent_parser']
    prior = source.snapshot.model_copy(update={'system_template': 'Explicit conflicting fixture'})
    sha = digest(template_content(prior))
    prior = repo.register(prior.model_copy(update={'content_hash': sha, 'template_snapshot_id': 'pt_'+sha}))
    with TestClient(app) as client:
        assert app.state.prompt_registration['intent_parser'] == 'PROMPT_VERSION_CONFLICT'
        row = client.get('/admin/prompts?node=intent_parser', headers={'X-Admin-Token': 'read'}).json()['items'][0]
        assert row['runtime_registration'] == 'not_registered'
        assert row['version_count'] == 1
        assert repo.template(prior.template_snapshot_id) == prior
        assert repo.template(source.snapshot.template_snapshot_id) is None
    assert 'Explicit conflicting fixture' not in caplog.text
    assert requests == []


def test_missing_storage_or_source_mismatch_is_not_silently_registered(tmp_path, monkeypatch):
    llm, _, _ = provider(tmp_path/'transport')
    app = create_app(Settings(tmp_path/'app'), llm)
    selected = sources(app)
    assert set(register_loaded_templates(None, selected).values()) == {'LLM_SNAPSHOT_UNAVAILABLE'}
    source = selected['intent_parser']
    monkeypatch.setattr(source, 'build', lambda: source.snapshot.model_copy(update={'content_hash': 'mismatch'}))
    assert register_loaded_templates(app.state.llm_captures.repository, {'intent_parser': source}) == {'intent_parser': 'PROMPT_SOURCE_MISMATCH'}
    assert app.state.llm_captures.repository.template(source.snapshot.template_snapshot_id) is None


def test_unconfigured_provider_creates_no_invented_current_templates(tmp_path):
    app = create_app(Settings(tmp_path, admin_read_token='read'))
    with TestClient(app) as client:
        assert app.state.prompt_registration == {}
        rows = client.get('/admin/prompts', headers={'X-Admin-Token': 'read'}).json()['items']
        assert all(row['version_count'] == 0 and row['runtime_registration'] == 'unknown' for row in rows)
