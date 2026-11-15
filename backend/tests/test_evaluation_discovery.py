"""Run and dataset discovery. Temp directories and scripted runs only; no model calls.

Historical directories are read and then compared. Nothing in them is written.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.evaluation.admin_views import DatasetListPage, RunListPage
from app.evaluation.datasets import DatasetSource
from app.evaluation.golden_fidelity import GOLD_PATH
from app.evaluation.run_index import EvaluationRoot
from app.evaluation.runs import read_run
from app.main import create_app
from app.services.evaluation_admin import build_evaluation_admin
from test_evaluation_contracts import fake_agent, start

AUTH = {'X-Admin-Token': 'read'}
REPO = Path(__file__).resolve().parents[2]
HISTORICAL_GOLDEN = REPO / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs'
HISTORICAL_TC = Path('/Users/lainey/Desktop/vibe-coding/var/regression/runs')
TC_CASES = REPO / 'docs/testing/typical-suite-v1-2026-11-09/cases.json'
GOLDEN_REF = 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'
TC_REF = 'docs/testing/typical-suite-v1-2026-11-09/cases.json'


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path):
    rows = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            stat = os.lstat(path)
            linked = path.is_symlink()
            digest = None
            if not linked and stat.st_mode & 0o170000 == 0o100000:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size, digest, linked))
    return rows


def _legacy(run_dir: Path, run_id: str, started: str, sha: str):
    run_dir.mkdir(parents=True)
    (run_dir / 'summary.json').write_text(json.dumps({
        'run_id': run_id, 'started_at': started, 'finished_at': started, 'golden_sha256': sha,
        'cases': [{'case_id': 'RF-01', 'verdict': {'status': 'passed', 'reason': 'ok'}, 'execution_status': 'success'}],
    }))


def _tc(run_dir: Path, *, finished: bool, sha: str, started: str, version='typical-suite-v1'):
    run_dir.mkdir(parents=True)
    body = {'run_id': run_dir.name, 'started_at': started, 'suite': {'version': version, 'cases_sha256': sha},
            'selected_cases': ['TC01'], 'cases': []}
    if finished:
        body['finished_at'] = started
        body['cases'] = [{'case_id': 'TC01', 'status': 'passed', 'checks': []}]
        (run_dir / 'run.json').write_text(json.dumps(body))
    else:
        (run_dir / 'run-start.json').write_text(json.dumps(body))


def _layout(tmp_path: Path):
    golden = tmp_path / 'golden'
    tc = tmp_path / 'tc'
    other = tmp_path / 'other-golden'
    for path in (golden, tc, other):
        path.mkdir()
    document = json.loads(TC_CASES.read_text())
    suite = tmp_path / 'cases.json'
    suite.write_text(json.dumps({'suite_version': 'typical-suite-v1', 'cases': document['cases'][:2]}))
    suite_sha = _sha(suite)
    _legacy(golden / 'gf_20990101-000000_aaaaaa', 'gf_20990101-000000_aaaaaa', '2026-01-01T00:00:00+00:00', _sha(GOLD_PATH))
    _legacy(golden / 'gf_20990101-000000_bbbbbb', 'gf_20990101-000000_bbbbbb', '2026-01-01T00:00:00+00:00', '0' * 64)
    _legacy(golden / 'gf_20990101-000000_cccccc', 'gf_20990101-000000_cccccc', '2026-01-02T00:00:00+00:00', _sha(GOLD_PATH))
    _legacy(other / 'gf_20990101-000000_cccccc', 'gf_20990101-000000_cccccc', '2026-01-02T00:00:00+00:00', _sha(GOLD_PATH))
    _tc(tc / 'rg_20990101-000000_aaaaaa', finished=True, sha=suite_sha, started='2026-01-03T00:00:00+00:00')
    _tc(tc / 'rg_20990101-000000_bbbbbb', finished=False, sha='1' * 64, started='2026-01-04T00:00:00+00:00')
    (golden / 'scratch').mkdir()
    (golden / 'gf_20990101-000000_badbad').mkdir()
    (golden / 'gf_20990101-000000_badbad' / 'summary.json').write_text('{')
    (golden / 'gf_20990101-000000_e0e0e0').mkdir()
    (golden / 'gf_20990101-000000_f0f0f0').write_text('x')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('secret-token')
    (golden / 'gf_20990101-000000_0a0a0a').symlink_to(outside, target_is_directory=True)
    holder = golden / 'holder'
    holder.mkdir()
    (golden / 'gf_20990101-000000_0b0b0b').symlink_to(holder, target_is_directory=True)
    new_run = golden / 'gf_20990101-000000_dddddd'
    start(new_run, fake_agent())
    incomplete = golden / 'gf_20990101-000000_eeeeee'
    with pytest.raises(RuntimeError):
        start(incomplete, fake_agent(fail_at='RF-02'))
    missing_manifest = golden / 'gf_20990101-000000_ffffff'
    start(missing_manifest, fake_agent())
    (missing_manifest / 'run-manifest.json').unlink()
    (new_run / 'data').mkdir()
    (new_run / 'data' / 'trace.sqlite3').write_bytes(b'SQLite format 3\x00')
    roots = [EvaluationRoot('golden', golden, 'golden'), EvaluationRoot('tc', tc, 'tc_regression'),
             EvaluationRoot('golden-copy', other, 'golden')]
    sources = [DatasetSource('golden', GOLD_PATH, GOLDEN_REF, 'golden'),
               DatasetSource('tc', suite, 'fixtures/cases.json', 'tc')]
    return build_evaluation_admin(roots, sources, GOLD_PATH), suite


def test_discovery_covers_formats_faults_sort_and_relation(tmp_path, monkeypatch):
    def refuse_sqlite(*_args, **_kwargs):
        raise AssertionError('SQLite must not be opened')
    monkeypatch.setattr(sqlite3, 'connect', refuse_sqlite)
    service, suite = _layout(tmp_path)
    page = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='-created_at')
    RunListPage.model_validate(page.model_dump())
    found = {item.run_id: item for item in page.items}
    assert 'gf_20990101-000000_aaaaaa' in found
    assert found['gf_20990101-000000_aaaaaa'].integrity_status == 'UNVERIFIED'
    assert found['gf_20990101-000000_aaaaaa'].agent_version is None
    assert found['gf_20990101-000000_aaaaaa'].dataset_version is None
    assert found['gf_20990101-000000_aaaaaa'].dataset_id == 'requirement-fidelity-golden-v1'
    assert found['rg_20990101-000000_aaaaaa'].run_type == 'tc_regression'
    assert found['rg_20990101-000000_aaaaaa'].dataset_version is None
    assert found['gf_20990101-000000_dddddd'].integrity_status == 'VERIFIED'
    assert found['gf_20990101-000000_dddddd'].agent_id == 'insightflow'
    assert found['gf_20990101-000000_dddddd'].agent_version is None
    assert found['gf_20990101-000000_eeeeee'].lifecycle_status == 'INCOMPLETE'
    assert found['gf_20990101-000000_ffffff'].integrity_status == 'INCOMPLETE'
    assert found['gf_20990101-000000_ffffff'].lifecycle_status == 'INCOMPLETE'
    assert 'gf_20990101-000000_badbad' not in found
    assert 'gf_20990101-000000_e0e0e0' not in found
    assert 'gf_20990101-000000_cccccc' not in found
    assert 'gf_20990101-000000_0a0a0a' not in found
    codes = {warning.code for warning in page.discovery_warnings}
    assert {'invalid_run_dir_name', 'run_json_corrupt', 'run_required_file_missing', 'symlink_outside_root',
            'symlink_run_dir_skipped', 'duplicate_run_id', 'run_entry_not_directory'} <= codes
    duplicate = next(warning for warning in page.discovery_warnings if warning.code == 'duplicate_run_id')
    assert duplicate.entry == 'gf_20990101-000000_cccccc'
    assert 'golden-copy' in duplicate.detail and 'golden' in duplicate.detail
    assert 'secret-token' not in page.model_dump_json()
    assert str(tmp_path) not in page.model_dump_json()

    same_time = [item.run_id for item in page.items if item.created_at == '2026-01-01T00:00:00+00:00']
    assert same_time == ['gf_20990101-000000_aaaaaa', 'gf_20990101-000000_bbbbbb']
    again = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='-created_at')
    assert [item.run_id for item in again.items] == [item.run_id for item in page.items]

    first = service.list_runs(page=1, page_size=1, run_type=None, status=None, integrity_status=None, sort='run_id')
    second = service.list_runs(page=2, page_size=1, run_type=None, status=None, integrity_status=None, sort='run_id')
    assert first.total == page.total and first.items[0].run_id < second.items[0].run_id
    tc_only = service.list_runs(page=1, page_size=20, run_type='tc_regression', status=None, integrity_status=None, sort='run_id')
    assert {item.run_id for item in tc_only.items} == {'rg_20990101-000000_aaaaaa', 'rg_20990101-000000_bbbbbb'}
    incomplete = service.list_runs(page=1, page_size=20, run_type=None, status='INCOMPLETE', integrity_status=None, sort='run_id')
    assert {item.run_id for item in incomplete.items} == {'gf_20990101-000000_eeeeee', 'gf_20990101-000000_ffffff', 'rg_20990101-000000_bbbbbb'}
    unverified = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status='UNVERIFIED', sort='run_id')
    assert {item.run_id for item in unverified.items} >= {'gf_20990101-000000_aaaaaa', 'rg_20990101-000000_aaaaaa'}

    datasets = service.list_datasets(page=1, page_size=20, dataset_type=None, sort='dataset_id')
    DatasetListPage.model_validate(datasets.model_dump())
    by_type = {item.dataset_type: item for item in datasets.items}
    assert by_type['golden'].dataset_version is None
    assert by_type['golden'].freeze_status == 'UNDECLARED'
    assert by_type['golden'].dataset_hash == _sha(GOLD_PATH)
    assert by_type['golden'].dataset_hash != (by_type['golden'].dataset_version or '')
    assert by_type['golden'].source == GOLDEN_REF
    assert by_type['tc'].dataset_version == 'typical-suite-v1'
    assert by_type['tc'].dataset_hash == _sha(suite)
    assert by_type['tc'].freeze_status == 'UNDECLARED'
    assert by_type['tc'].case_count == 2
    assert by_type['golden'].hash_matched_run_count == 4
    assert by_type['golden'].weak_path_run_count == 0
    assert by_type['golden'].hash_mismatch_run_count == 1
    assert by_type['golden'].related_run_count == 4
    assert by_type['tc'].hash_matched_run_count == 1
    assert by_type['tc'].weak_path_run_count == 0
    assert by_type['tc'].hash_mismatch_run_count == 1
    assert str(tmp_path) not in datasets.model_dump_json()
    assert '/' not in by_type['tc'].source or not by_type['tc'].source.startswith('/')


def test_empty_root_is_an_empty_page(tmp_path):
    root = tmp_path / 'empty'
    root.mkdir()
    service = build_evaluation_admin([EvaluationRoot('golden', root, 'golden')], [], None)
    page = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='-created_at')
    assert page.items == [] and page.total == 0 and page.discovery_warnings == []


def test_missing_root_is_503_and_one_bad_run_does_not_drop_the_other(tmp_path):
    missing = build_evaluation_admin([EvaluationRoot('golden', tmp_path / 'nope', 'golden')], [], None)
    with pytest.raises(Exception) as error:
        missing.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='-created_at')
    assert error.value.error.code == 'EVALUATION_ROOTS_UNAVAILABLE'
    root = tmp_path / 'golden'
    root.mkdir()
    _legacy(root / 'gf_20990101-000000_aaaaaa', 'gf_20990101-000000_aaaaaa', '2026-01-01T00:00:00+00:00', '0' * 64)
    (root / 'gf_20990101-000000_bbbbbb').mkdir()
    (root / 'gf_20990101-000000_bbbbbb' / 'summary.json').write_text('{')
    service = build_evaluation_admin(
        [EvaluationRoot('golden', root, 'golden'), EvaluationRoot('tc', tmp_path / 'missing-tc', 'tc_regression')], [], None)
    page = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='run_id')
    assert [item.run_id for item in page.items] == ['gf_20990101-000000_aaaaaa']
    assert any(warning.code == 'run_json_corrupt' for warning in page.discovery_warnings)
    assert any(warning.code == 'root_unavailable' and warning.root_id == 'tc' for warning in page.discovery_warnings)


def test_http_contract_prefixes_and_existing_routes(tmp_path):
    golden = tmp_path / 'golden'
    tc = tmp_path / 'tc'
    golden.mkdir()
    tc.mkdir()
    _legacy(golden / 'gf_20990101-000000_aaaaaa', 'gf_20990101-000000_aaaaaa', '2026-01-01T00:00:00+00:00', _sha(GOLD_PATH))
    regression = tmp_path / 'data' / 'regression' / 'runs' / 'rg_20990101-000000_cccccc'
    _tc(regression, finished=True, sha='2' * 64, started='2026-01-01T00:00:00+00:00')
    app = create_app(Settings(
        tmp_path / 'data', admin_read_token='read', evaluation_golden_runs=golden, evaluation_tc_runs=tc,
        evaluation_golden_dataset=GOLD_PATH, evaluation_tc_dataset=TC_CASES))
    with TestClient(app) as client:
        denied = client.get('/api/v1/admin/evaluations/runs')
        assert denied.status_code == 403 and denied.json()['error']['code'] == 'ADMIN_ACCESS_DENIED'
        runs = client.get('/api/v1/admin/evaluations/runs', headers=AUTH)
        datasets = client.get('/admin/evaluations/datasets', headers=AUTH)
        assert runs.status_code == 200 and runs.headers['cache-control'] == 'no-store'
        assert datasets.status_code == 200
        run_page = RunListPage.model_validate(runs.json())
        dataset_page = DatasetListPage.model_validate(datasets.json())
        assert run_page.items[0].run_id == 'gf_20990101-000000_aaaaaa'
        assert dataset_page.total == 2
        assert all(item.freeze_status == 'UNDECLARED' for item in dataset_page.items)
        assert client.get('/api/v1/admin/evaluations/runs', headers=AUTH, params={'page': 0}).status_code == 422
        assert client.get('/api/v1/admin/evaluations/runs', headers=AUTH, params={'page_size': 101}).status_code == 422
        assert client.get('/api/v1/admin/evaluations/runs', headers=AUTH, params={'sort': 'name'}).status_code == 422
        body = runs.text + datasets.text
        assert str(tmp_path) not in body and str(REPO) not in body
        same = client.get('/admin/evaluations/runs', headers=AUTH)
        assert same.json() == runs.json()
        other = client.get('/api/v1/admin/evaluations/datasets', headers=AUTH)
        assert other.json() == datasets.json()
        regression_page = client.get('/admin/regression-runs', headers=AUTH)
        mirrored = client.get('/api/v1/admin/regression-runs', headers=AUTH)
        assert regression_page.status_code == 200 and regression_page.json() == mirrored.json()
        assert regression_page.json()['items'][0]['run_id'] == 'rg_20990101-000000_cccccc'
        traces = client.get('/admin/runs', headers=AUTH)
        assert traces.status_code == 200 and 'coverage_notice' in traces.json()
        assert 'discovery_warnings' not in traces.json()
    bare = create_app(Settings(tmp_path / 'bare', admin_read_token='read'))
    with TestClient(bare) as client:
        missing = client.get('/api/v1/admin/evaluations/runs', headers=AUTH)
        assert missing.status_code == 503 and missing.json()['error']['code'] == 'EVALUATION_ADMIN_UNAVAILABLE'


def test_historical_directories_are_unchanged_by_discovery(monkeypatch):
    def refuse_sqlite(*_args, **_kwargs):
        raise AssertionError('SQLite must not be opened')
    monkeypatch.setattr(sqlite3, 'connect', refuse_sqlite)
    before = {HISTORICAL_GOLDEN: _snapshot(HISTORICAL_GOLDEN), HISTORICAL_TC: _snapshot(HISTORICAL_TC),
              GOLD_PATH: _sha(GOLD_PATH), TC_CASES: _sha(TC_CASES)}
    service = build_evaluation_admin(
        [EvaluationRoot('golden', HISTORICAL_GOLDEN, 'golden'), EvaluationRoot('tc', HISTORICAL_TC, 'tc_regression')],
        [DatasetSource('golden', GOLD_PATH, GOLDEN_REF, 'golden'), DatasetSource('tc', TC_CASES, TC_REF, 'tc')],
        GOLD_PATH)
    runs = service.list_runs(page=1, page_size=20, run_type=None, status=None, integrity_status=None, sort='run_id')
    datasets = service.list_datasets(page=1, page_size=20, dataset_type=None, sort='dataset_id')
    assert {item.run_id for item in runs.items} == {
        'gf_20261112-143310_a5cca5', 'gf_20261112-143406_cde1fd', 'rg_20261112-133157_f04289'}
    direct = {path.name: read_run(path) for path in sorted(HISTORICAL_GOLDEN.iterdir()) if path.is_dir()}
    tc_dir = next(path for path in HISTORICAL_TC.iterdir() if path.is_dir())
    direct[tc_dir.name] = read_run(tc_dir)
    for item in runs.items:
        view = direct[item.run_id].run
        assert item.created_at == view.created_at
        assert item.lifecycle_status == view.status
        assert item.integrity_status == view.integrity.status
        assert item.dataset_hash == view.dataset_hash
        assert item.agent_version is None and item.dataset_version is None
    golden = next(item for item in datasets.items if item.dataset_type == 'golden')
    tc = next(item for item in datasets.items if item.dataset_type == 'tc')
    assert golden.freeze_status == tc.freeze_status == 'UNDECLARED'
    assert golden.dataset_version is None and golden.dataset_hash == before[GOLD_PATH]
    assert tc.dataset_id == 'typical-suite-v1' and tc.dataset_hash == before[TC_CASES]
    assert golden.hash_matched_run_count == 2 and tc.hash_matched_run_count == 1
    assert _snapshot(HISTORICAL_GOLDEN) == before[HISTORICAL_GOLDEN]
    assert _snapshot(HISTORICAL_TC) == before[HISTORICAL_TC]
