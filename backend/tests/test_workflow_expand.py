"""Expand-only structures tested in isolated databases; no production writers."""
from contextlib import closing
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.plan_review import PlanVersion, ReviewApproval
from app.main import create_app
from app.observability.provenance import digest
from app.storage.workflow_expand import (KINDS, ExpandError, apply_expand, inspect_expand,
    connect, schema, specification, statements)
from app.storage.workflow_reader import WorkflowReader
from test_report_workflow import Provider, run as report_run

PATHS = {'business': 'insightflow.sqlite3', 'trace': 'observability/trace.sqlite3',
         'registry': 'prompt_registry/registry.sqlite3'}
NOW = '2026-10-30T00:00:00Z'


def raw_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def insert(conn, table, data):
    columns = ','.join(data)
    conn.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in data)})', tuple(data.values()))


@pytest.fixture
def legacy(tmp_path):
    app = create_app(Settings(tmp_path), Provider(), bootstrap_identity=False)
    with TestClient(app) as client:
        _, execution, session = report_run(client)
        yield tmp_path, app, client, execution, session


def expand_all(path):
    return {kind: apply_expand(path / PATHS[kind], kind) for kind in KINDS}


def contents(conn, names):
    return {name: [tuple(r) for r in conn.execute(f'SELECT * FROM {name} ORDER BY rowid')] for name in names}


@pytest.mark.parametrize('kind', KINDS)
def test_expand_preserves_all_legacy_schema_rows_and_is_idempotent(legacy, kind):
    directory, _, _, _, _ = legacy
    path = directory / PATHS[kind]
    with closing(connect(path, readonly=True)) as c:
        before = schema(c)
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        rows = contents(c, names)
    assert inspect_expand(path, kind)['status'] == 'pending'
    assert apply_expand(path, kind)['status'] == 'applied'
    with closing(connect(path)) as c:
        assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert contents(c, names) == rows
        after = schema(c)
        assert all(after.get(key) == value for key, value in before.items())
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        for key in specification(kind)[1]:
            if key[0] == 'table' and key[1] != 'workflow_expand_migrations':
                assert c.execute(f'SELECT COUNT(*) FROM {key[1]}').fetchone()[0] == 0
    assert apply_expand(path, kind)['status'] == 'already_applied'
    with closing(connect(path)) as c:
        assert schema(c) == after
        assert c.execute('SELECT COUNT(*) FROM workflow_expand_migrations').fetchone()[0] == 1


@pytest.mark.parametrize('fault', ['partial', 'column', 'extra_trigger', 'checksum', 'missing_version'])
def test_partial_or_drift_is_detected_without_repair(legacy, fault):
    directory, _, _, _, _ = legacy
    path = directory / PATHS['business']
    if fault in {'partial', 'checksum', 'missing_version'}:
        with closing(connect(path)) as c, c:
            source, _, _ = specification('business')
            pieces = list(statements(source))
            for statement in pieces[:1] if fault == 'partial' else pieces:
                c.execute(statement)
            if fault == 'checksum':
                c.execute('INSERT INTO workflow_expand_migrations VALUES (?,?,?,?)', ('phase02a-expand-001', 'business', 'wrong', NOW))
    else:
        apply_expand(path, 'business')
        with closing(connect(path)) as c, c:
            if fault == 'column':
                c.execute('ALTER TABLE business_workflows ADD COLUMN unexpected TEXT')
            else:
                c.execute("CREATE TRIGGER unexpected_trigger BEFORE DELETE ON business_workflows BEGIN SELECT RAISE(ABORT,'unexpected'); END")
    with closing(connect(path, readonly=True)) as c:
        before = schema(c)
    with pytest.raises(ExpandError) as error:
        apply_expand(path, 'business')
    assert error.value.code in {'EXPAND_PARTIAL_SCHEMA', 'EXPAND_SCHEMA_MISMATCH', 'EXPAND_CHECKSUM_MISMATCH'}
    with closing(connect(path, readonly=True)) as c:
        assert schema(c) == before


@pytest.mark.parametrize('kind', KINDS)
def test_failed_validation_rolls_back_ddl_and_version(legacy, monkeypatch, kind):
    from app.storage import workflow_expand as module
    directory, _, _, _, _ = legacy
    path = directory / PATHS[kind]
    with closing(connect(path, readonly=True)) as c:
        before = schema(c)
    original = module._state
    calls = 0
    def fail_after_ddl(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ExpandError('INJECTED', 'fail before commit')
        return original(*args)
    monkeypatch.setattr(module, '_state', fail_after_ddl)
    with pytest.raises(ExpandError, match='fail before commit'):
        apply_expand(path, kind)
    with closing(connect(path, readonly=True)) as c:
        assert schema(c) == before
    monkeypatch.setattr(module, '_state', original)
    assert apply_expand(path, kind)['status'] == 'applied'


def seed_workflows(legacy):
    directory, app, _, execution, session = legacy
    expand_all(directory)
    db = directory / PATHS['business']
    sid = session['id']
    workflow_rows, plans = {}, {}
    with closing(connect(db)) as c, c:
        c.execute('BEGIN IMMEDIATE')
        insert(c, 'session_datasets', {'session_id': sid, 'dataset_id': session['dataset_ref']['dataset_id'], 'created_at': NOW})
        for index, name in enumerate(['a', 'b'], 1):
            insert(c, 'session_messages', {'message_id': 'message-'+name, 'session_id': sid, 'sequence': index,
                'role': 'user', 'kind': 'text', 'content': 'goal '+name, 'created_at': NOW})
            row = {'workflow_id': 'wf-'+name, 'session_id': sid,
                'root_run_id': app.state.traces.repository.workflow(sid).run_id if name == 'a' else 'reserved-root-b',
                'origin_message_id': 'message-'+name, 'input_file_id': session['dataset_ref']['dataset_id'],
                **session['dataset_ref'], 'goal_text': 'goal '+name, 'goal_sha256': raw_hash('goal '+name),
                'control_status': 'CREATED', 'control_context': '{}', 'creation_request_id': 'create-'+name,
                'creation_payload_hash': 'a'*64, 'origin': 'native', 'created_at': NOW, 'updated_at': NOW,
                'materialized_at': NOW, 'provenance': '{}'}
            insert(c, 'business_workflows', row)
            workflow_rows[name] = row
            original = c.execute('SELECT record FROM plan_versions WHERE session_id=? AND plan_version=1', (sid,)).fetchone()[0]
            plan = PlanVersion.model_validate_json(original)
            if name == 'b':
                plan.plan_id = 'independent-plan-b'
                plan.validated_plan.plan.plan_id = plan.plan_id
            raw = original if name == 'a' else plan.model_dump_json()
            version = {'plan_version_id': 'pv-'+name, 'workflow_id': row['workflow_id'], 'session_id': sid,
                'plan_version': 1, 'plan_id': plan.plan_id, 'dataset_id': plan.dataset_id,
                'dataset_version': plan.dataset_version, 'validation_version': plan.validation_version,
                'payload_hash': raw_hash(raw), 'registered_at': NOW, 'source_kind': 'legacy_ref' if name == 'a' else 'native',
                'legacy_session_id': sid if name == 'a' else None, 'legacy_plan_version': 1 if name == 'a' else None,
                'record_json': None if name == 'a' else raw}
            insert(c, 'workflow_plan_versions', version)
            plans[name] = plan
        approval_row = c.execute('SELECT * FROM plan_approvals WHERE session_id=?', (sid,)).fetchone()
        approval = ReviewApproval.model_validate_json(approval_row['record'])
        insert(c, 'workflow_approval_links', {'approval_id': approval.approval_id, 'workflow_id': 'wf-a', 'session_id': sid,
            'plan_version_id': 'pv-a', 'client_request_id': 'confirm-1', 'payload_hash': 'b'*64,
            'snapshot_hash': digest(approval.snapshot), 'source_kind': 'legacy_ref', 'registered_at': NOW})
        second = approval.model_copy(deep=True)
        second.approval_id, second.approval_request_id = 'approval-b', 'effective-b'
        second.plan_id = plans['b'].plan_id
        second.snapshot.approval_id = second.approval_id
        second.snapshot.validated_plan = plans['b'].validated_plan
        insert(c, 'plan_approvals', {'approval_id': second.approval_id, 'session_id': sid,
            'request_id': 'effective-b', 'request': '{}', 'record': second.model_dump_json()})
        insert(c, 'workflow_approval_links', {'approval_id': second.approval_id, 'workflow_id': 'wf-b', 'session_id': sid,
            'plan_version_id': 'pv-b', 'client_request_id': 'confirm-1', 'payload_hash': 'c'*64,
            'snapshot_hash': digest(second.snapshot), 'source_kind': 'native', 'registered_at': NOW})
        insert(c, 'workflow_execution_links', {'execution_id': execution['execution_id'], 'workflow_id': 'wf-a', 'session_id': sid,
            'approval_id': approval.approval_id, 'plan_version_id': 'pv-a', 'dispatch_key': 'dispatch-a',
            'client_request_id': 'execute-1', 'payload_hash': 'd'*64, 'source_kind': 'legacy_ref', 'registered_at': NOW})
        job = session['report_generations'][0]
        insert(c, 'workflow_report_links', {'report_id': job['report_id'], 'workflow_id': 'wf-a', 'session_id': sid,
            'execution_id': execution['execution_id'], 'accepted_report_attempt': job['attempt'],
            'source_kind': 'legacy_ref', 'registered_at': NOW})
    return workflow_rows, plans, approval


@pytest.mark.parametrize('field,value', [('workflow_id', 'wf-a'), ('workflow_id', None),
    ('root_run_id', 'same-root'), ('creation_request_id', 'create-a')])
def test_workflow_creation_identity_and_idempotency_constraints(legacy, field, value):
    rows, _, _ = seed_workflows(legacy)
    row = rows['b'] | {'workflow_id': 'wf-c', 'root_run_id': 'reserved-root-c', 'creation_request_id': 'create-c'}
    row[field] = rows['a']['root_run_id'] if field == 'root_run_id' else value
    with closing(connect(legacy[0] / PATHS['business'])) as c:
        with pytest.raises(sqlite3.IntegrityError), c:
            insert(c, 'business_workflows', row)
        assert c.execute('SELECT COUNT(*) FROM business_workflows').fetchone()[0] == 2


def test_independent_v1_and_readonly_legacy_native_resolver(legacy):
    _, plans, approval = seed_workflows(legacy)
    directory, _, client, execution, session = legacy
    reader = WorkflowReader(directory / PATHS['business'])
    assert len(reader.list(session['id'])) == 2
    assert reader.plan('wf-a', 1).version == plans['a']
    assert reader.plan('wf-b', 1).version == plans['b']
    assert reader.approval('wf-a', approval.approval_id) == approval
    assert reader.approval('wf-b', 'approval-b').plan_id == plans['b'].plan_id
    assert reader.execution('wf-a', execution['execution_id'])['result'].execution_id == execution['execution_id']
    report_id = session['report_generations'][0]['report_id']
    assert reader.report('wf-a', report_id).report_id == report_id
    with pytest.raises(AppError):
        reader.execution('wf-b', execution['execution_id'])
    with pytest.raises(AppError):
        reader.report('wf-b', report_id)
    # This test-only seeded new store has not become the old API's authority.
    assert client.get('/api/v1/sessions/'+session['id']).json() == session
    assert client.get('/api/v1/sessions/'+session['id']+'/plans/1').json()['plan_id'] == plans['a'].plan_id
    with reader.snapshot() as conn:
        assert conn.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            conn.execute('UPDATE business_workflows SET revision=revision+1')


@pytest.mark.parametrize('field,value', [('current_plan_version_id','pv-b'), ('current_approval_id','approval-b')])
def test_current_pointer_composite_fk_rejects_other_workflow(legacy, field, value):
    seed_workflows(legacy)
    with closing(connect(legacy[0] / PATHS['business'])) as c:
        with pytest.raises(sqlite3.IntegrityError), c:
            c.execute(f'UPDATE business_workflows SET {field}=?,revision=revision+1 WHERE workflow_id=?', (value, 'wf-a'))


def test_origin_parent_and_dataset_require_same_session(legacy):
    rows, _, _ = seed_workflows(legacy)
    with closing(connect(legacy[0] / PATHS['business'])) as c:
        original = c.execute('SELECT * FROM sessions LIMIT 1').fetchone()
        with c:
            body = json.loads(original['state'])
            body['id'] = 'other-session'
            c.execute('INSERT INTO sessions VALUES (?,?,?)', ('other-session', original['updated_at'], json.dumps(body)))
            insert(c, 'session_messages', {'message_id':'other-message','session_id':'other-session','sequence':1,
                'role':'user','kind':'text','content':'other','created_at':NOW})
        for changes in [{'origin_message_id':'other-message'}, {'session_id':'other-session','parent_workflow_id':'wf-a'}]:
            row = rows['b'] | {'workflow_id':'wf-c','root_run_id':'root-c','creation_request_id':'create-c'} | changes
            with pytest.raises(sqlite3.IntegrityError), c:
                insert(c, 'business_workflows', row)


def test_new_fact_and_failed_link_rollback_in_one_transaction(legacy):
    _, _, approval = seed_workflows(legacy)
    sid = legacy[4]['id']
    changed = approval.model_copy(deep=True)
    changed.approval_id = changed.snapshot.approval_id = 'transaction-test'
    with closing(connect(legacy[0] / PATHS['business'])) as c:
        with pytest.raises(sqlite3.IntegrityError), c:
            c.execute('BEGIN IMMEDIATE')
            insert(c, 'plan_approvals', {'approval_id':changed.approval_id,'session_id':sid,'request_id':'tx-test',
                'request':'{}','record':changed.model_dump_json()})
            insert(c, 'workflow_approval_links', {'approval_id':changed.approval_id,'workflow_id':'wf-a','session_id':sid,
                'plan_version_id':'pv-b','client_request_id':'tx-test','payload_hash':'e'*64,
                'snapshot_hash':digest(changed.snapshot),'source_kind':'native','registered_at':NOW})
        assert not c.execute('SELECT 1 FROM plan_approvals WHERE approval_id=?', ('transaction-test',)).fetchone()


@pytest.mark.parametrize('table', ['workflow_plan_versions','workflow_approval_links','workflow_execution_links','workflow_report_links'])
def test_new_history_bindings_are_immutable(legacy, table):
    seed_workflows(legacy)
    with closing(connect(legacy[0] / PATHS['business'])) as c:
        with pytest.raises(sqlite3.IntegrityError), c:
            c.execute(f'DELETE FROM {table}')


def test_three_database_failure_is_resumable_without_distributed_claim(legacy, monkeypatch):
    from app.storage import workflow_expand as module
    directory = legacy[0]
    assert apply_expand(directory / PATHS['business'], 'business')['status'] == 'applied'
    original = module._state
    calls = 0
    def fail_trace(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ExpandError('INJECTED', 'trace transaction failed')
        return original(*args)
    monkeypatch.setattr(module, '_state', fail_trace)
    with pytest.raises(ExpandError):
        apply_expand(directory / PATHS['trace'], 'trace')
    monkeypatch.setattr(module, '_state', original)
    results = expand_all(directory)
    assert results['business']['status'] == 'already_applied'
    assert results['trace']['status'] == results['registry']['status'] == 'applied'


def test_missing_database_reader_never_creates_files(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        WorkflowReader(path).get('none')
    assert not path.exists()


def maintenance_cli():
    path = Path(__file__).resolve().parents[1] / 'scripts/expand_business_workflow.py'
    spec = importlib.util.spec_from_file_location('phase02a_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sqlite_backup_includes_committed_wal_and_never_overwrites(legacy):
    directory = legacy[0]
    cli = maintenance_cli()
    path = directory / PATHS['business']
    backup = directory / 'backup.sqlite3'
    with closing(connect(path)) as c:
        c.execute('CREATE TABLE wal_probe (id INTEGER PRIMARY KEY,value TEXT)')
        c.execute("INSERT INTO wal_probe VALUES (1,'committed in WAL')")
        c.commit()
        assert path.with_name(path.name+'-wal').exists()
        result = cli.backup_database(path, backup)
        assert result['verified']
        with closing(connect(backup, readonly=True)) as saved:
            assert saved.execute('SELECT value FROM wal_probe').fetchone()[0] == 'committed in WAL'
        checksum = hashlib.sha256(backup.read_bytes()).hexdigest()
        with pytest.raises(FileExistsError):
            cli.backup_database(path, backup)
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == checksum
        assert backup.stat().st_mode & 0o777 == 0o600


def test_cli_requires_maintenance_and_rejects_active_tasks(legacy):
    directory, app, _, _, session = legacy
    cli = maintenance_cli()
    assert all(v['status']=='pending' for v in cli.run(directory)['databases'].values())
    backup = directory / 'backup'
    with pytest.raises(ExpandError) as error:
        cli.run(directory, apply=True, backup_dir=backup)
    assert error.value.code == 'EXPAND_MAINTENANCE_REQUIRED' and not backup.exists()
    def active(s):
        s.status = type(s.status).PLANNING
    app.state.repository.mutate(session['id'], active)
    with pytest.raises(ExpandError) as error:
        cli.run(directory, apply=True, backup_dir=backup, maintenance=True)
    assert error.value.code == 'EXPAND_ACTIVE_WORK' and not backup.exists()


def test_cli_backup_apply_partial_failure_and_safe_rerun(legacy, monkeypatch):
    directory = legacy[0]
    cli = maintenance_cli()
    apply = cli.apply_expand
    def fail_trace(path, kind):
        if kind == 'trace':
            raise ExpandError('INJECTED', 'trace temporarily unavailable')
        return apply(path, kind)
    monkeypatch.setattr(cli, 'apply_expand', fail_trace)
    result = cli.run(directory, apply=True, backup_dir=directory/'backup-first', maintenance=True)
    assert not result['complete']
    assert result['databases']['business']['status']=='applied'
    assert result['databases']['trace']['status']=='failed'
    assert result['databases']['registry']['status']=='pending'
    assert all(x['verified'] for x in result['backups'].values())
    monkeypatch.setattr(cli, 'apply_expand', apply)
    again = cli.run(directory, apply=True, backup_dir=directory/'backup-rerun', maintenance=True)
    assert again['complete'] and again['databases']['business']['status']=='already_applied'
    assert WorkflowReader(directory/PATHS['business']).list(legacy[4]['id']) == []


def test_trace_links_and_original_session_unique_root_are_preserved(legacy):
    seed_workflows(legacy)
    directory, app, _, execution, session = legacy
    repo = app.state.traces.repository
    root = repo.workflow(session['id'])
    with closing(connect(directory/PATHS['trace'])) as c:
        with c:
            insert(c, 'trace_workflow_links', {'run_id':root.run_id,'workflow_id':'wf-a','session_id':session['id'],
                'kind':'workflow','evidence':'{}','registered_at':NOW})
        with pytest.raises(sqlite3.IntegrityError), c:
            insert(c, 'trace_workflow_links', {'run_id':repo.attempt(execution['execution_id'],1).run_id,
                'workflow_id':'wf-b','session_id':'wrong-session','kind':'report_generation','evidence':'{}','registered_at':NOW})
        with pytest.raises(sqlite3.IntegrityError), c:
            duplicate = root.model_copy(update={'run_id':'duplicate-root','workflow_run_id':'duplicate-root'})
            c.execute('INSERT INTO trace_runs VALUES (?,?,?,?,?,?)',
                (duplicate.run_id,None,1,duplicate.queued_at,duplicate.status,duplicate.model_dump_json()))
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_session_unique'").fetchone()
    links = WorkflowReader(directory/PATHS['business']).observation_links('wf-a', directory/PATHS['trace'], kind='trace')
    assert len(links)==1 and links[0]['run_id']==root.run_id
    assert root == repo.get(root.run_id)


def test_registry_links_do_not_fabricate_run_or_rewrite_calls(tmp_path):
    from test_workflow_trace_v031 import http_provider
    from workflow_v1_fixtures import create_real
    provider, _ = http_provider()
    app = create_app(Settings(tmp_path), provider)
    with TestClient(app) as client:
        state = create_real(client)
        expand_all(tmp_path)
        path = tmp_path/PATHS['registry']
        with closing(connect(path)) as c:
            call = c.execute('SELECT * FROM llm_calls LIMIT 1').fetchone()
            before = tuple(call)
            with c:
                insert(c, 'llm_call_workflow_links', {'call_id':call['id'],'workflow_id':'unverified-wf',
                    'session_id':state['id'],'run_id':call['run_id'],'span_id':call['span_id'],
                    'root_run_id':call['run_id'],'evidence':'{}','registered_at':NOW})
            with pytest.raises(sqlite3.IntegrityError), c:
                insert(c, 'llm_call_workflow_links', {'call_id':call['id'],'workflow_id':'other',
                    'session_id':state['id'],'run_id':'invented','span_id':call['span_id'],
                    'evidence':'{}','registered_at':NOW})
            assert tuple(c.execute('SELECT * FROM llm_calls WHERE id=?',(call['id'],)).fetchone()) == before
        # Sidecar metadata alone cannot establish a Business Workflow owner.
        with pytest.raises(AppError):
            WorkflowReader(tmp_path/PATHS['business']).observation_links('unverified-wf', path, kind='registry')
