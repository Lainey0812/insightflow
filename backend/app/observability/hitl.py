"""Observe actual HITL commands only; commits and authorization remain in PlanReviewService."""
from contextlib import closing
from contextvars import ContextVar
from functools import wraps

from app.domain.errors import AppError
from app.observability.context import bind_trace
from app.observability.recorder import SpanHandle, error_code
from app.observability.workflow import preparation_context

_receipt = ContextVar('hitl_observation_receipt', default=None)


def mark_approval_replay():
    """Called at the existing idempotent branch; no database or Trace IO here."""
    receipt = _receipt.get()
    if receipt is not None:
        receipt['replay'] = True


def hitl_validation_role():
    receipt = _receipt.get()
    return 'hitl_' + receipt['command'] if receipt is not None else 'initial_plan_save'


def observe_hitl(command):
    def decorate(method):
        @wraps(method)
        def wrapped(self, session_id, request):
            observer = getattr(self, 'observations', None)
            if observer is None:
                return method(self, session_id, request)
            return observer.perform(command, session_id, request,
                                    lambda: method(self, session_id, request))
        return wrapped
    return decorate


class HITLObserver:
    def __init__(self, sessions, identities, recorder):
        self.sessions, self.identities, self.recorder = sessions, identities, recorder

    def _context(self, session_id):
        state = self.sessions.get(session_id)
        if state.workflow_id is None and state.root_run_id is None:
            self.identities.require_unregistered(session_id)
            return None  # Historical operations do not acquire a fabricated Workflow.
        identity = self.identities.resolve(state)
        return preparation_context(self.recorder, session_id, identity, explicit_only=True)

    def _proof(self, command, result):
        """Read exact immutable facts after the service's transaction has exited."""
        identity = self.identities.resolve(result)
        plan = result.review_plan
        with closing(self.sessions.database.connect()) as conn:
            conn.execute('BEGIN')
            stored = conn.execute('SELECT record FROM plan_versions WHERE session_id=? AND plan_version=?',
                                  (result.id, plan.plan_version)).fetchone()
            if not stored or stored['record'] != plan.model_dump_json():
                raise ValueError('Committed PlanVersion unavailable')
            attributes = {'workflow_id':identity.workflow_id,'root_run_id':identity.root_run_id,
                'plan_id':plan.plan_id,'plan_version':plan.plan_version,
                'dataset_id':plan.dataset_id,'dataset_version':plan.dataset_version,
                'validation_version':plan.validation_version}
            if command == 'approve':
                approval = result.engine_approval
                row = conn.execute('SELECT record FROM plan_approvals WHERE session_id=? AND approval_id=?',
                                   (result.id, approval.approval_id)).fetchone()
                from app.domain.plan_review import ReviewApproval
                if not row or ReviewApproval.model_validate_json(row['record']).snapshot != approval:
                    raise ValueError('Committed Approval unavailable')
                attributes['approval_id'] = approval.approval_id
            return attributes

    def perform(self, command, session_id, request, action):
        # Every observation read/write is fail-open. Execute the business action exactly once.
        ok, trace = self.recorder.call(lambda: self._context(session_id))
        if not ok or trace is None or trace.run is None:
            if not ok or (trace is not None and trace.run is None):
                self.recorder.workflow_gap(session_id)
            return action()
        attributes = {'command':command,'plan_id':request.plan_id,'plan_version':request.plan_version,
                      'session_revision':request.expected_revision}
        _, handle = self.recorder.call(lambda: SpanHandle(trace, 'hitl', attributes))
        trace.active = handle
        receipt = {'replay':False,'command':command}
        token = _receipt.set(receipt)
        try:
            with bind_trace(trace):
                try:
                    result = action()
                except BaseException as exc:
                    self.recorder.call(lambda: trace.event('hitl.denied' if isinstance(exc, AppError) else 'hitl.failed',
                        handle.record.span_id if handle and handle.record else None,
                        command=command,error_code=error_code(exc)))
                    if handle:
                        self.recorder.call(lambda: handle.finish(exc))
                    raise
                def finish():
                    proof = self._proof(command, result)
                    outcome = 'replayed' if receipt['replay'] else ('approved' if command == 'approve' else 'revised')
                    if handle:
                        handle.attributes(**proof,command=command,outcome=outcome)
                        handle.event('hitl.' + outcome,**proof,command=command,outcome=outcome)
                        handle.finish()
                observed, _ = self.recorder.call(finish)
                if not observed:
                    self.recorder.workflow_gap(session_id)
                    if handle:
                        self.recorder.call(lambda: handle.finish(AppError('TRACE_COMMIT_UNVERIFIED',
                            '业务操作已返回，观测无法核验提交证据。')))
                return result
        finally:
            _receipt.reset(token)
