"""Concurrency and stale callback regressions over real temporary repositories."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.models import WorkflowError
from app.domain.tracing import RunManifest, TraceRun, TraceSpan
from app.main import create_app
from app.observability.recorder import TraceContext, TraceRecorder
from app.observability.workflow import checkpoint, interrupt, start_preparation
from app.storage.trace_repository import TraceRepository
from test_report_workflow import Provider, run as report_run
from workflow_v1_fixtures import ControlledWorkflowProvider, create_real


def root_record(identity='root'):
    return TraceRun(run_id=identity, session_id='session', workflow_run_id=identity,
        kind='workflow', owner_instance='test', attempt=1, status='running',
        business_revision=1, queued_at='2026-10-30T00:00:00Z', manifest=RunManifest())


def test_atomic_concurrent_root_callbacks_have_one_winner(tmp_path):
    repo = TraceRepository(tmp_path)
    original = repo.create(root_record())
    callbacks = [original.model_copy(deep=True), original.model_copy(deep=True)]
    callbacks[0].status = 'waiting_approval'
    callbacks[1].status = 'failed'
    barrier = Barrier(2)
    def apply(candidate):
        barrier.wait(timeout=5)
        return repo.update_run(candidate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(apply, callbacks))
    assert sorted(outcomes) == [False, True]
    winner = callbacks[outcomes.index(True)]
    saved = repo.get(original.run_id)
    assert saved == winner and saved.observation_revision == 1
    assert repo.update_run(callbacks[outcomes.index(False)]) is False
    assert repo.get(saved.run_id) == saved


def test_new_business_revision_cannot_be_overwritten_by_old_or_null_revision(tmp_path):
    repo = TraceRepository(tmp_path)
    old = repo.create(root_record())
    newer = old.model_copy(update={'business_revision': 20, 'status': 'waiting_approval'})
    assert repo.update_run(newer)
    old.status, old.business_revision = 'failed', 10
    assert repo.update_run(old) is False
    fresh = repo.get(old.run_id)
    fresh.status, fresh.business_revision = 'failed', None
    assert repo.update_run(fresh) is False
    assert repo.get(old.run_id) == newer


def test_same_business_revision_stale_checkpoint_and_interrupt_are_only_ignored_events(tmp_path):
    repo = TraceRepository(tmp_path)
    original = repo.create(root_record())
    recorder = TraceRecorder(repo)
    stale = TraceContext(recorder, original.model_copy(deep=True))
    current = original.model_copy(update={'status': 'waiting_approval'})
    assert repo.update_run(current)
    # Both callbacks carry the same business revision, but an obsolete CAS token.
    interrupt(stale, AppError('LLM_TIMEOUT', 'late'))
    checkpoint(stale, SimpleNamespace(status=SimpleNamespace(value='FAILED'), revision=1,
        error=WorkflowError(code='LLM_TIMEOUT', message='late')))
    assert repo.get(original.run_id) == current
    events = repo.run_events(original.run_id)
    assert [e.event_type for e in events] == ['workflow.callback_ignored', 'workflow.callback_ignored']
    assert not any(e.event_type in {'workflow.interrupted', 'workflow.failed'} for e in events)


def test_retry_keeps_root_and_historical_span_but_requires_new_business_revision(tmp_path):
    repo = TraceRepository(tmp_path)
    old = repo.create(root_record())
    span = TraceSpan(span_id='old-node', run_id=old.run_id, name='analysis_planner',
        node_key='analysis_planner', node_attempt=1, status='failed',
        started_at=old.queued_at, error_code='LLM_TIMEOUT')
    repo.save_span(span)
    old.status = 'failed'
    assert repo.update_run(old)
    failed = repo.get(old.run_id)
    same_revision = failed.model_copy(update={'status': 'running'})
    assert repo.update_run(same_revision) is False
    ctx = TraceContext(TraceRecorder(repo), failed)
    start_preparation(ctx, 2)
    saved = repo.get(old.run_id)
    assert saved.status == 'running' and saved.business_revision == 2
    assert saved.run_id == old.run_id and saved.attempt == 1
    assert repo.span(span.span_id) == span
    # Even a newly read object cannot regress a closed preparation to failed.
    saved.status = 'waiting_approval'
    assert repo.update_run(saved)
    late = repo.get(old.run_id)
    late.status = 'failed'
    assert repo.update_run(late) is False


def test_legacy_json_default_token_and_report_terminal_compatibility(tmp_path):
    repo = TraceRepository(tmp_path)
    legacy = root_record()
    repo.create(legacy)
    with repo.connect() as conn:
        payload = legacy.model_dump()
        payload.pop('observation_revision')
        conn.execute('UPDATE trace_runs SET record=? WHERE id=?', (json.dumps(payload), legacy.run_id))
        tables_before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    loaded = repo.get(legacy.run_id)
    assert loaded.observation_revision == 0
    loaded.status = 'failed'
    assert repo.update_run(loaded)
    report = TraceRun(run_id='report', session_id='session', execution_id='exec', attempt=1,
        owner_instance='test', status='queued', queued_at=legacy.queued_at, manifest=RunManifest())
    report = repo.create(report)
    report.status = 'running'
    assert repo.update_run(report)
    report.status = 'partial'
    assert repo.update_run(report)
    partial = repo.get(report.run_id)
    report.status = 'running'
    assert repo.update_run(report) is False
    assert repo.get(report.run_id) == partial
    assert repo.get(legacy.run_id).manifest == legacy.manifest
    with repo.connect() as conn:
        assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == tables_before


@pytest.mark.parametrize('late_error', [False, True])
def test_late_planner_result_or_error_cannot_modify_resumed_session(tmp_path, late_error):
    provider = ControlledWorkflowProvider()
    app = create_app(Settings(tmp_path), provider)
    with TestClient(app) as client:
        workflow = app.state.workflow
        prepare = workflow.prepare_real
        async def defer(_, identity=None):
            pass
        workflow.prepare_real = defer
        initial = create_real(client)
        workflow.prepare_real = prepare
        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()
            generate = provider.generate
            held = False
            async def delayed(request):
                nonlocal held
                value = await generate(request)
                if request.purpose == 'analysis_planner_v1' and not held:
                    held = True
                    started.set()
                    await release.wait()
                    if late_error:
                        raise AppError('LLM_TIMEOUT', 'obsolete model error', 504)
                return value
            provider.generate = delayed
            old_task = asyncio.create_task(prepare(initial['id']))
            await asyncio.wait_for(started.wait(), 5)
            interrupted = workflow.fail_real(initial['id'], WorkflowError(
                code='PROCESS_INTERRUPTED', message='test recovery', retryable=True))
            app.state.traces.recover()
            resumed = workflow.begin_real_retry(initial['id'], interrupted.revision)
            assert resumed.id == initial['id']
            await prepare(initial['id'])
            current = app.state.repository.get(initial['id'])
            root = app.state.traces.repository.workflow(initial['id'])
            assert current.status.value == 'AWAITING_APPROVAL'
            release.set()
            await asyncio.wait_for(old_task, 5)
            assert app.state.repository.get(initial['id']) == current
            assert app.state.traces.repository.workflow(initial['id']) == root
            spans = app.state.traces.repository.spans(root.run_id)
            planner = [s for s in spans if s.name == 'analysis_planner']
            assert [(s.node_attempt, s.status) for s in planner] == [(1, 'suspended'), (2, 'success')]
            assert len([r for r in app.state.traces.repository.runs()[0] if r.kind == 'workflow']) == 1
        asyncio.run(scenario())


@pytest.mark.parametrize('recover_trace', [False, True])
@pytest.mark.parametrize('late_error', [False, True])
def test_report_trace_success_requires_accepted_commit(tmp_path, recover_trace, late_error):
    app = create_app(Settings(tmp_path), Provider())
    with TestClient(app) as client:
        service = app.state.report_service
        generate = service.generate
        old_report_ids = []
        async def superseded(*args, **kwargs):
            report = await generate(*args, **kwargs)
            old_report_ids.append(report.report_id)
            app.state.reports.recover_interrupted()
            if recover_trace:
                app.state.traces.recover()
            record, fresh = app.state.report_workflow.enqueue(report.execution_id, 1)
            assert fresh and record.attempt == 2
            if late_error:
                raise AppError('LLM_TIMEOUT', 'late report failure', 504)
            return report
        service.generate = superseded
        _, execution, session = report_run(client)
        eid = execution['execution_id']
        repo = app.state.traces.repository
        generation = app.state.reports.generation(eid)
        assert generation.attempt == 2 and generation.status == 'queued'
        old = repo.attempt(eid, 1)
        assert old.status == 'suspended' and old.report_id is None
        assert not any(s.kind == 'report' for s in repo.snapshots(old.run_id))
        with app.state.repository.database.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM analysis_reports WHERE id=?', (old_report_ids[0],)).fetchone()[0] == 0
        if not recover_trace and not late_error:
            assert any(s.name == 'report_persistence' and s.status == 'error' and
                s.error_code == 'REPORT_STALE_CALLBACK' for s in repo.spans(old.run_id))
        assert not any(e.event_type == 'run.finished' and e.payload.get('report_status') == 'complete'
            for e in repo.run_events(old.run_id))
        old_saved = repo.get(old.run_id)
        service.generate = generate
        asyncio.run(app.state.report_workflow.generate(eid, 2))
        new = repo.attempt(eid, 2)
        job = app.state.reports.generation(eid)
        assert job.status == 'completed' and new.status == 'success'
        assert job.report_id == new.report_id == app.state.reports.get(job.report_id).report_id
        assert new.retry_of_run_id == old.run_id and new.workflow_run_id == old.workflow_run_id
        assert repo.get(old.run_id) == old_saved
        assert app.state.executions.get(eid).execution_status == 'success'
        assert app.state.repository.get(session['id']).status.value == 'COMPLETED'
