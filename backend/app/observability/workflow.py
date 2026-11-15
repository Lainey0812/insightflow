"""Workflow preparation observations over the existing Trace repository."""
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.tracing import RunManifest, TraceRun
from app.observability.recorder import TraceContext, error_code, safe_error_message
from app.observability.provenance import digest, git_snapshot
from pathlib import Path


def register_root(recorder, state, parser, planner, binding=None):
    def create():
        refs = {}
        versions = {}
        models = {}
        for name, service in [('intent_parser', parser), ('analysis_planner', planner)]:
            source = getattr(service, 'prompt_source', None)
            if source:
                refs[name] = source.snapshot.template_snapshot_id
                versions[name] = source.version
            provider = getattr(service, 'provider', None)
            models[name] = {'provider': type(provider).__name__, 'model': getattr(provider, 'model', None),
                            'timeout_seconds': getattr(service, 'timeout_seconds', None),
                            'enable_thinking': getattr(service, 'enable_thinking', None),
                            'temperature': getattr(provider, 'temperature', None),
                            'top_p': getattr(provider, 'top_p', None),
                            'max_tokens': getattr(provider, 'max_tokens', None)}
        if binding and state.status.value != 'CREATED':
            # A repaired identity is not evidence of historical prompt/config usage.
            refs, versions, models = {}, {}, {}
        identity = binding.root_run_id if binding else 'run_' + uuid4().hex
        run = TraceRun(run_id=identity, kind='workflow', workflow_run_id=identity,
            session_id=state.id, attempt=1, owner_instance=recorder.owner_instance, status='running',
            business_revision=state.revision, queued_at=state.created_at,
            integrity='incomplete' if binding and state.status.value != 'CREATED' else 'observed',
            manifest=RunManifest(schema_version='workflow-trace-v0.3.1', capture_scope='workflow_preparation',
                bindings={'session_id': state.id, 'file_id': state.file.id,
                          **({'workflow_id': binding.workflow_id, 'root_run_id': binding.root_run_id} if binding else {})}, versions=versions,
                git=git_snapshot(Path(__file__).resolve().parents[3]),
                input_sha256={'user_goal': digest(state.user_goal)},
                prompt_template_snapshots=refs, model_config_snapshot=models))
        return (recorder.repository.create_registered_root(run, binding) if binding
                else recorder.repository.create(run))
    ok, run = recorder.call(create)
    if not ok:
        recorder.workflow_gap(state.id)
    return run


def preparation_context(recorder, session_id, identity=None, explicit_only=False):
    def load():
        if identity:
            run = recorder.repository.get(identity.root_run_id)
            if run and (run.session_id != identity.session_id or
                        run.manifest.bindings.get('workflow_id') != identity.workflow_id):
                raise ValueError('Preparation Root identity mismatch')
            return run
        return None if explicit_only else recorder.repository.workflow(session_id)
    ok, run = recorder.call(load)
    if not ok:
        recorder.workflow_gap(session_id)
    trace = TraceContext(recorder, run)
    trace.workflow_identity = identity
    return trace


def start_preparation(trace, revision):
    if not trace.run:
        return
    run = trace.run
    previous = run.status
    if previous == 'running' and run.started_at:
        # A second dispatch must not take ownership of an active observation.
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=revision)
        trace.run = None
        return
    fresh = run.started_at is None
    run.status, run.business_revision = 'running', revision
    run.started_at = run.started_at or datetime.now(timezone.utc).isoformat()
    run.finished_at, run.duration_ms, run.error_code, run.error_message = None, None, None, None
    accepted = trace.call(lambda: trace.owner.repository.update_run(run))
    if accepted:
        trace.event('workflow.started' if fresh else 'workflow.resumed',
                    status='running', previous_status=previous, session_revision=revision)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=revision)
        trace.run = None


def checkpoint(trace, state):
    if not trace.run:
        return
    mapping = {'WAITING_FOR_CLARIFICATION': 'suspended', 'AWAITING_APPROVAL': 'suspended', 'FAILED': 'error'}
    status = mapping.get(state.status.value, 'running')
    run = trace.run
    run.status, run.business_revision = status, state.revision
    if status == 'error':
        run.finished_at = datetime.now(timezone.utc).isoformat()
        # The root's elapsed wall time is not a node computation duration.
        run.duration_ms = None
        run.error_code = error_code(state.error.code) if state.error else 'WORKFLOW_PREPARATION_FAILED'
        run.error_message = safe_error_message(run.error_code)
    if trace.gaps:
        run.integrity = 'incomplete'
    accepted = trace.call(lambda: trace.owner.repository.update_run(run))
    if accepted:
        trace.event('workflow.' + status, status=status, session_revision=state.revision,
                    error_code=run.error_code, error_message=run.error_message)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=state.revision)


def interrupt(trace, error):
    if not trace.run:
        return
    trace.run.status = 'suspended'
    trace.run.error_code = error_code(error)
    trace.run.error_message = safe_error_message(trace.run.error_code)
    trace.run.finished_at = datetime.now(timezone.utc).isoformat()
    trace.run.duration_ms = None
    accepted = trace.call(lambda: trace.owner.repository.update_run(trace.run))
    if accepted:
        trace.event('workflow.interrupted', error_code=trace.run.error_code)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK')
