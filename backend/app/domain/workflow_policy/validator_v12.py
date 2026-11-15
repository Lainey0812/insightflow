"""C19-A/B policy checkpoints. No business transaction or Trace writer is wired."""
from typing import Literal
from pydantic import ValidationError
from app.domain.enums import SessionStatus as S
from .catalogue_v12 import SPECS_V12
from .models import ExpectedTransition, PolicyCommand, PolicyDecision, PolicySnapshot
from .report_commit import (CommitRecords, CompletionSpan, ReportAuthorization, reconcile_report_commit)
from .validator import (ASYNC, REPORT, Rejected, WorkflowPolicyValidator, one, require, same_binding)


class PolicySnapshotV12(PolicySnapshot):
    policy_scope: Literal['native_v1.2', 'legacy_session_v1'] = 'native_v1.2'
    validated_evidence_ids: tuple[str, ...] = ()
    authorization: ReportAuthorization | None = None
    commit_records: CommitRecords | None = None
    completion_span: CompletionSpan | None = None


class WorkflowPolicyValidatorV12(WorkflowPolicyValidator):
    policy_scope = 'native_v1.2'
    command_specs = SPECS_V12
    async_commands = ASYNC | {'C19-A'}

    def validate(self, snapshot: PolicySnapshotV12 | dict, command: PolicyCommand | dict) -> PolicyDecision:
        identity, scope = 'unknown', self.policy_scope
        try:
            s = PolicySnapshotV12.model_validate(snapshot)
            scope = s.policy_scope
            c = PolicyCommand.model_validate(command)
            identity = c.command_id
            require(scope == self.policy_scope, 'POLICY_LEGACY_DELEGATED')
            require(c.command_id != 'C19', 'POLICY_CONTRACT_SUPERSEDED', 'C19-A', 'C19-B')
            if c.command_id == 'C19-B':
                return self._observe(s, c)
            return super()._validate(s, c)
        except ValidationError:
            return PolicyDecision(decision='deny', reason_code='POLICY_INVALID_INPUT', action='none',
                                  policy_scope=scope, command_id=identity)
        except Rejected as error:
            return PolicyDecision(decision='deny', reason_code=error.code, action='none',
                policy_scope=scope, command_id=identity, detail_fields=error.fields)

    def _report_extension(self, s, c, plan, validation, execution, generation):
        if c.command_id != 'C19-A':
            return False
        report = one(c.facts, 'report')
        same_binding(report.binding, s.binding, REPORT)
        require(one(s.facts, 'report', False) is None and generation.report_id is None,
                'POLICY_REPORT_ALREADY_DELIVERED')
        require(execution.execution_outcome in {'success', 'partial_success'} and
                report.report_status in {'complete', 'partial'} and report.goal_coverage is not None,
                'POLICY_REPORT_INVALID')
        require(bool(report.evidence_ids) and report.valid_core_insight_count > 0 and
                set(report.evidence_ids) <= set(s.validated_evidence_ids), 'POLICY_REPORT_EVIDENCE_INVALID')
        failed_core = {t.task_id for t in execution.tasks if t.status != 'success'} & set(plan.core_task_ids)
        require(not (report.goal_coverage == 'complete' and (validation.coverage != 'complete' or failed_core)),
                'POLICY_REPORT_COVERAGE_INVALID')
        # Presence of an acknowledgement/proof is deliberately not a precondition.
        return True

    def _observe(self, s, c):
        require(not c.facts and c.next_active_execution_key is None and not c.remove_task_ids and
                not c.acknowledged_warnings, 'POLICY_OBSERVATION_INPUT_INVALID')
        require((c.session_id, c.workflow_id) == (s.session_id, s.workflow_id), 'POLICY_WORKFLOW_MISMATCH')
        require(s.exists and s.control_status == S.COMPLETED, 'POLICY_INVALID_CONTROL_STATE')
        require(s.authorization is not None, 'POLICY_COMMIT_NOT_CONFIRMED')
        auth = s.authorization
        require((auth.session_id, auth.workflow_id, auth.root_run_id) ==
                (s.session_id, s.workflow_id, s.root_run_id), 'POLICY_WORKFLOW_MISMATCH')
        require(c.binding == s.binding == auth.binding, 'POLICY_COMMAND_SUPERSEDED')
        require(c.expected_revision == auth.authorized_revision and c.active_execution_key == auth.authorized_active_key,
                'POLICY_COMMIT_AUTHORIZATION_MISMATCH')
        require(c.request_id == auth.request_id, 'POLICY_COMMIT_AUTHORIZATION_MISMATCH')
        result = reconcile_report_commit(auth, s.commit_records)
        require(result.accepted is True, 'POLICY_COMMIT_NOT_CONFIRMED', result.reason_code)
        require(s.revision >= result.committed_revision, 'POLICY_COMMIT_REVISION_UNCONFIRMED')
        span = s.completion_span
        require(span is not None, 'POLICY_OBSERVATION_MISSING')
        require((span.session_id, span.workflow_id, span.run_id) ==
                (auth.session_id, auth.workflow_id, auth.root_run_id), 'POLICY_OBSERVATION_MISMATCH')
        require(span.node_key == 'report_persistence' and span.parent_span_id is None,
                'POLICY_SPAN_NOT_DIRECT_ROOT')
        require(auth.persistence_span_id is not None and span.span_id == auth.persistence_span_id and
                span.binding == auth.binding and span.report_id == auth.report_id and
                span.report_digest == auth.report_digest and span.commit_request_id == auth.request_id and
                span.commit_payload_hash == auth.payload_hash and span.authorized_revision == auth.authorized_revision and
                span.authorized_active_key == auth.authorized_active_key, 'POLICY_OBSERVATION_MISMATCH')
        if span.status == 'complete':
            return PolicyDecision(decision='allow', reason_code='POLICY_OBSERVATION_ALREADY_COMPLETE', action='replay',
                policy_scope=s.policy_scope, command_id=c.command_id, replay_ref=span.span_id)
        require(span.status == 'running', 'POLICY_OBSERVATION_TERMINAL')
        spec = self.command_specs['C19-B']
        return PolicyDecision(decision='allow', reason_code='POLICY_OBSERVATION_ALLOWED', action='observe',
            policy_scope=s.policy_scope, command_id=c.command_id,
            expected_transition=ExpectedTransition(owner='span', source='running', target='complete'),
            required_evidence=(spec.required_evidence,))
