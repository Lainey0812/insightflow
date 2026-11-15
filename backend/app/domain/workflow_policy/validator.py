"""Side-effect-free command policy for trusted transaction snapshots.

No filesystem, Repository, LLM, Trace recorder or runtime service is imported.
An allow is conditional on the future writer atomically enforcing the same CAS,
references, evidence and idempotency reservation. C19 is deliberately blocked:
its frozen accepted=True precondition requires a contract timing clarification.
"""
from pydantic import ValidationError
from app.domain.enums import SessionStatus as S
from .catalogue import SPECS
from .models import (Bindings, BusinessFact, ExpectedTransition, PolicyCommand,
                     PolicyDecision, PolicySnapshot)

DATASET = ('dataset_id', 'dataset_version')
PLAN = DATASET + ('plan_version_id', 'plan_id', 'plan_version', 'validation_version')
APPROVAL = PLAN + ('approval_id',)
EXECUTION = APPROVAL + ('execution_id', 'execution_request_id')
REPORT = EXECUTION + ('report_attempt',)
PREPARATION = {S.CREATED, S.PROFILING, S.PARSING_INTENT, S.PLANNING, S.VALIDATING}
NEW_KEY = {'C01', 'C05', 'C11', 'C17', 'C22'}
ASYNC = {'C02', 'C03', 'C04', 'C06', 'C07', 'C12', 'C13', 'C14', 'C18', 'C20', 'C23'}
UNSUPPORTED = {'RESUME_ENGINE', 'RESUME_ENGINE_TASK', 'RESUME_ENGINE_STEP',
               'RESUME_REPORT', 'RESUME_REPORT_CANDIDATE', 'REOPEN_ROOT'}


class Rejected(Exception):
    def __init__(self, code, *fields):
        self.code, self.fields = code, tuple(fields)


def require(condition, code, *fields):
    if not condition:
        raise Rejected(code, *fields)


def one(facts, kind, required=True):
    matches = [f for f in facts if f.kind == kind]
    require(len(matches) <= 1, 'POLICY_AMBIGUOUS_EVIDENCE', kind)
    if required:
        require(bool(matches), 'POLICY_MISSING_EVIDENCE', kind)
    return matches[0] if matches else None


def same_binding(actual, expected, names, *, mandatory=True):
    for name in names:
        left, right = getattr(actual, name), getattr(expected, name)
        if mandatory:
            require(left is not None and right is not None, 'POLICY_MISSING_REFERENCE', name)
        require(left == right, 'POLICY_REFERENCE_MISMATCH', name)


def approval(plan, fact):
    same_binding(fact.binding, plan.binding, PLAN)
    require(fact.approval_status == 'approved' and fact.binding.approval_id == fact.fact_id and
            fact.intent_hash == plan.intent_hash,
            'POLICY_APPROVAL_INVALID', 'approval_id')


def plan_validation(plan, validation):
    same_binding(validation.binding, plan.binding, PLAN)
    require(validation.candidate_hash == plan.digest and validation.capability_version,
            'POLICY_VALIDATION_MISMATCH', 'candidate_hash', 'capability_version')
    tasks = set(plan.task_ids)
    executable, blocked = set(validation.executable_task_ids), set(validation.blocked_task_ids)
    require(not executable & blocked and executable | blocked == tasks,
            'POLICY_VALIDATION_MISMATCH', 'task_ids')
    require(set(plan.core_task_ids) <= tasks and validation.coverage is not None,
            'POLICY_VALIDATION_MISMATCH', 'coverage')
    missing_core = set(plan.core_task_ids) & blocked
    require(set(validation.unmet_core_task_ids) == missing_core and
            (not missing_core or validation.coverage != 'complete'),
            'POLICY_CORE_REQUIREMENT_LOST')
    require(not missing_core or bool(validation.unmet_requirement_ids), 'POLICY_CORE_REQUIREMENT_LOST')
    require(validation.coverage != 'complete' or not validation.unmet_requirement_ids,
            'POLICY_VALIDATION_MISMATCH', 'unmet_requirement_ids')


def outcome(fact, plan, blocked=()):
    require(set(t.task_id for t in fact.tasks) == set(plan.task_ids) and bool(fact.tasks),
            'POLICY_EXECUTION_INVALID', 'task_ids')
    for task in fact.tasks:
        require(task.task_id not in blocked or task.status == 'skipped', 'POLICY_BLOCKED_TASK_EXECUTED', task.task_id)
        require(bool(task.result_ref) if task.status == 'success' else bool(task.error_code),
                'POLICY_MISSING_EVIDENCE', task.task_id)
    successes = sum(t.status == 'success' for t in fact.tasks)
    expected = 'success' if successes == len(fact.tasks) else 'partial_success' if successes else 'failed'
    require(fact.execution_outcome == expected, 'POLICY_EXECUTION_INVALID', 'execution_outcome')
    return expected


class WorkflowPolicyValidator:
    policy_scope = 'native_v1.1'
    command_specs = SPECS
    async_commands = ASYNC

    def validate(self, snapshot: PolicySnapshot | dict, command: PolicyCommand | dict) -> PolicyDecision:
        identity, scope = 'unknown', self.policy_scope
        try:
            snapshot = PolicySnapshot.model_validate(snapshot)
            scope = snapshot.policy_scope
            command = PolicyCommand.model_validate(command)
            identity = command.command_id
            return self._validate(snapshot, command)
        except ValidationError:
            return PolicyDecision(decision='deny', reason_code='POLICY_INVALID_INPUT', action='none',
                                  policy_scope=scope, command_id=identity)
        except Rejected as error:
            return PolicyDecision(decision='deny', reason_code=error.code, action='none',
                                  policy_scope=scope, command_id=identity, detail_fields=error.fields)

    def _validate(self, s, c):
        require(s.policy_scope == self.policy_scope, 'POLICY_LEGACY_DELEGATED')
        require(c.command_id not in UNSUPPORTED, 'POLICY_UNSUPPORTED_OPERATION', 'command_id')
        require(c.command_id in self.command_specs, 'POLICY_UNKNOWN_COMMAND', 'command_id')
        spec = self.command_specs[c.command_id]
        require((c.session_id, c.workflow_id) == (s.session_id, s.workflow_id), 'POLICY_WORKFLOW_MISMATCH')
        for fact in s.facts + c.facts:
            require((fact.session_id, fact.workflow_id) == (s.session_id, s.workflow_id),
                    'POLICY_WORKFLOW_MISMATCH', fact.kind)
        require(c.command_id != 'C19', 'POLICY_CONTRACT_CONFLICT', 'C19.accepted')
        previous = [r for r in s.idempotency if r.request_id == c.request_id]
        require(len(previous) <= 1, 'POLICY_AMBIGUOUS_IDEMPOTENCY')
        if previous:
            saved = previous[0]
            require((saved.session_id, saved.workflow_id) == (s.session_id, s.workflow_id),
                    'POLICY_WORKFLOW_MISMATCH', 'idempotency')
            require(saved.command_id == c.command_id and saved.payload_hash == c.payload_hash(),
                    'POLICY_IDEMPOTENCY_CONFLICT')
            require(saved.effective_binding == s.binding, 'POLICY_COMMAND_SUPERSEDED')
            require(saved.status == 'completed', 'POLICY_COMMAND_IN_PROGRESS')
            require(bool(saved.response_ref), 'POLICY_MISSING_EVIDENCE', 'response_ref')
            return PolicyDecision(decision='allow', reason_code='POLICY_IDEMPOTENT_REPLAY', action='replay',
                policy_scope=s.policy_scope, command_id=c.command_id, replay_ref=saved.response_ref)
        require(s.observed_root_status != 'complete', 'POLICY_ROOT_CLOSED')
        require(s.observed_root_status != 'unavailable', 'POLICY_ROOT_CLOSED')
        require(c.expected_revision == s.revision, 'POLICY_STALE_REVISION')
        require(c.active_execution_key == s.active_execution_key, 'POLICY_STALE_ACTIVE_KEY')
        require(c.binding == s.binding, 'POLICY_REFERENCE_MISMATCH', 'current_binding')
        if spec.owner == 'creation':
            require(not s.exists and s.control_status is None and s.revision == 0,
                    'POLICY_WORKFLOW_ALREADY_EXISTS')
        else:
            require(s.exists, 'POLICY_WORKFLOW_MISSING')
            if spec.owner == 'control':
                require(s.control_status is not None and s.control_status.value == spec.source,
                        'POLICY_INVALID_CONTROL_STATE')
            else:
                require(s.control_status in {S.COMPLETED, S.FAILED}, 'POLICY_INVALID_CONTROL_STATE')
                gen = one(s.facts, 'generation', required=False)
                if c.command_id == 'C22' and gen and gen.generation_status in {'unavailable', 'completed'}:
                    raise Rejected('POLICY_REPORT_RETRY_UNSUPPORTED')
                require(gen is None or gen.generation_status is not None, 'POLICY_MISSING_EVIDENCE', 'generation_status')
                require((gen.generation_status if gen else None) == spec.source,
                        'POLICY_INVALID_GENERATION_STATE')
        for kind in spec.proposed_fact_kinds:
            one(c.facts, kind)
        if c.command_id in NEW_KEY or c.command_id.startswith('C16-') or c.recovery:
            require(bool(c.next_active_execution_key) and c.next_active_execution_key != s.active_execution_key,
                    'POLICY_NEW_ACTIVE_KEY_REQUIRED')
        if c.command_id in self.async_commands or c.command_id.startswith(('C15-', 'C21-')):
            require(bool(s.active_execution_key), 'POLICY_MISSING_ACTIVE_KEY')
            for fact in c.facts:
                if fact.kind != 'worker_fence':
                    require(fact.operation_key == s.active_execution_key, 'POLICY_STALE_ACTIVE_KEY', fact.kind)
        if c.recovery:
            require(c.command_id.startswith(('C15-', 'C21-')), 'POLICY_RECOVER_UNSUPPORTED')
            fence = one(c.facts, 'worker_fence')
            require(fence.operation_key == s.active_execution_key, 'POLICY_WORKER_NOT_FENCED')
        self._preconditions(s, c)
        return PolicyDecision(decision='allow', reason_code='POLICY_ALLOWED', action='execute',
            policy_scope=s.policy_scope, command_id=c.command_id,
            expected_transition=ExpectedTransition(owner=spec.owner, source=spec.source, target=spec.target),
            required_evidence=(spec.required_evidence,))

    def _preconditions(self, s, c):
        code = c.command_id
        current_input = one(s.facts, 'input', required=code != 'C24')
        if current_input:
            require(all((current_input.input_file_id, current_input.content_hash, current_input.goal_hash,
                         current_input.profile_options_hash)), 'POLICY_MISSING_EVIDENCE', 'fixed_input')
        if code in {'C01', 'C24'}:
            proposed = one(c.facts, 'input')
            require(all((proposed.input_file_id, proposed.content_hash, proposed.goal_hash,
                         proposed.profile_options_hash)), 'POLICY_MISSING_EVIDENCE', 'fixed_input')
            if current_input:
                require(proposed == current_input, 'POLICY_INPUT_CHANGED')
            if code == 'C24':
                require(not s.binding.model_dump(exclude_none=True), 'POLICY_INVALID_CREATION')
                message = one(c.facts, 'message')
                require(c.workflow_id not in s.existing_workflow_ids and s.root_run_id not in s.reserved_root_ids,
                        'POLICY_CREATION_CONFLICT')
                require(bool(c.origin_message_id) and message.fact_id == c.origin_message_id == s.origin_message_id,
                        'POLICY_ORIGIN_MESSAGE_MISMATCH')
                require(proposed.input_file_id in s.authorized_input_file_ids, 'POLICY_INPUT_NOT_AUTHORIZED')
                require(c.parent_workflow_id is None or (c.parent_workflow_id != c.workflow_id and
                        c.parent_workflow_id in s.existing_workflow_ids), 'POLICY_PARENT_WORKFLOW_MISMATCH')
            return
        if code == 'C02':
            profile = one(c.facts, 'profile')
            self._profile_input(profile, current_input)
            require(profile.binding.dataset_id == current_input.input_file_id and profile.binding.dataset_version,
                    'POLICY_REFERENCE_MISMATCH', 'profile.dataset')
            if s.binding.dataset_id:
                same_binding(profile.binding, s.binding, DATASET)
            return
        if code.startswith('C15-'):
            failure = one(c.facts, 'failure')
            require(failure.error_code and failure.failed_phase == s.control_status,
                    'POLICY_FAILURE_INVALID')
            require(not any(one(s.facts, k, False) for k in ('plan', 'approval', 'execution', 'generation')),
                    'POLICY_PREPARATION_RETRY_FORBIDDEN')
            return
        if code.startswith('C16-'):
            require(not any(one(s.facts, k, False) for k in ('plan', 'approval', 'execution', 'generation')) and
                    not any(getattr(s.binding, k) is not None for k in PLAN[len(DATASET):] + ('approval_id', 'execution_id')),
                    'POLICY_PREPARATION_RETRY_FORBIDDEN')
            failure = one(s.facts, 'failure')
            require(failure.retryable and failure.failed_phase in PREPARATION, 'POLICY_NOT_RETRYABLE')
            candidate, intent, profile = (one(s.facts, k, False) for k in ('candidate', 'intent', 'profile'))
            if profile:
                self._profile_input(profile, current_input)
                same_binding(profile.binding, s.binding, DATASET)
            if intent:
                same_binding(intent.binding, s.binding, DATASET)
                require(intent.artifact_origin == 'llm' and intent.goal_hash == current_input.goal_hash, 'POLICY_CHECKPOINT_INVALID')
            if candidate:
                same_binding(candidate.binding, s.binding, DATASET)
                require(candidate.artifact_origin == 'llm' and candidate.capability_version == s.capability_version and
                        intent is not None and intent.answers_hash == current_input.answers_hash, 'POLICY_CHECKPOINT_INVALID')
                require(intent is not None and intent.next_action == 'proceed' and candidate.intent_hash == intent.digest,
                        'POLICY_CHECKPOINT_INVALID')
                target = 'VALIDATING'
            elif intent and intent.next_action == 'proceed' and intent.answers_hash == current_input.answers_hash:
                target = 'PLANNING'
            else:
                target = 'PARSING_INTENT' if profile else 'PROFILING'
            require(self.command_specs[code].target == target, 'POLICY_CHECKPOINT_INVALID', target)
            return
        profile = one(s.facts, 'profile')
        self._profile_input(profile, current_input)
        same_binding(profile.binding, s.binding, DATASET)
        if code in {'C03', 'C04'}:
            intent = one(c.facts, 'intent')
            same_binding(intent.binding, s.binding, DATASET)
            require(intent.artifact_origin == 'llm', 'POLICY_REAL_LLM_ARTIFACT_REQUIRED')
            require(intent.goal_hash == current_input.goal_hash and intent.answers_hash == current_input.answers_hash,
                    'POLICY_INPUT_CHANGED', 'intent')
            require(intent.next_action == ('proceed' if code == 'C03' else 'clarify'), 'POLICY_INTENT_DECISION_MISMATCH')
            require(bool(intent.questions) == (code == 'C04'), 'POLICY_INTENT_DECISION_MISMATCH', 'questions')
            return
        intent = one(s.facts, 'intent')
        same_binding(intent.binding, s.binding, DATASET)
        if code == 'C05':
            answer = one(c.facts, 'answer')
            same_binding(answer.binding, s.binding, DATASET)
            require(intent.next_action == 'clarify' and bool(intent.questions) and answer.goal_hash == current_input.goal_hash,
                    'POLICY_CLARIFICATION_INVALID')
            require(bool(answer.answers_hash) and answer.answers_hash != current_input.answers_hash,
                    'POLICY_CLARIFICATION_INVALID', 'answers_hash')
            return
        require(intent.next_action == 'proceed' and intent.goal_hash == current_input.goal_hash and
                intent.answers_hash == current_input.answers_hash, 'POLICY_INTENT_BLOCKED')
        if code == 'C06':
            candidate = one(c.facts, 'candidate')
            same_binding(candidate.binding, s.binding, DATASET)
            require(candidate.intent_hash == intent.digest and candidate.artifact_origin == 'llm' and candidate.capability_version and
                    candidate.capability_version == s.capability_version,
                    'POLICY_CANDIDATE_MISMATCH')
            return
        if code in {'C07', 'C08', 'C09'}:
            proposed, validation = one(c.facts, 'plan'), one(c.facts, 'validation')
            same_binding(proposed.binding, s.binding, DATASET)
            plan_validation(proposed, validation)
            require(validation.capability_version == s.capability_version, 'POLICY_VALIDATION_MISMATCH', 'capability_version')
            require(proposed.binding.plan_version_id == proposed.fact_id and proposed.intent_hash == intent.digest,
                    'POLICY_REFERENCE_MISMATCH', 'proposed_plan')
            require(not one(s.facts, 'execution', False) and not one(s.facts, 'generation', False) and
                    s.binding.execution_id is None, 'POLICY_PLAN_ALREADY_EXECUTED')
            if code == 'C07':
                require(one(s.facts, 'plan', False) is None and s.binding.plan_version_id is None and
                        one(s.facts, 'approval', False) is None and s.binding.approval_id is None,
                        'POLICY_PLAN_ALREADY_EXISTS')
                candidate = one(s.facts, 'candidate')
                require(candidate.capability_version == validation.capability_version == s.capability_version,
                        'POLICY_CANDIDATE_MISMATCH', 'capability_version')
                require(candidate.intent_hash == intent.digest and candidate.task_ids == proposed.task_ids and
                        candidate.core_task_ids == proposed.core_task_ids and proposed.binding.plan_version == 1 and
                        candidate.binding.plan_id == proposed.binding.plan_id and candidate.digest == validation.source_candidate_hash,
                        'POLICY_CANDIDATE_MISMATCH')
            else:
                old = one(s.facts, 'plan')
                same_binding(old.binding, s.binding, PLAN)
                removed = set(c.remove_task_ids)
                require(removed and len(removed) == len(c.remove_task_ids) and removed <= set(old.task_ids),
                        'POLICY_TASK_SELECTION_INVALID')
                require(set(proposed.task_ids) == set(old.task_ids) - removed and
                        set(proposed.core_task_ids) == set(old.core_task_ids) - removed,
                        'POLICY_TASK_SELECTION_INVALID')
                require(proposed.binding.plan_version == old.binding.plan_version + 1 and
                        proposed.binding.plan_id == old.binding.plan_id and proposed.fact_id != old.fact_id,
                        'POLICY_PLAN_VERSION_INVALID')
                if code == 'C09':
                    approved = one(s.facts, 'approval')
                    approval(old, approved)
                    same_binding(approved.binding, s.binding, APPROVAL)
            return
        plan, validation = one(s.facts, 'plan'), one(s.facts, 'validation')
        same_binding(plan.binding, s.binding, PLAN)
        plan_validation(plan, validation)
        if code in {'C10', 'C11'}:
            require(validation.capability_version == s.capability_version, 'POLICY_VALIDATION_MISMATCH', 'capability_version')
        if code == 'C10':
            require(validation.coverage != 'blocked' and bool(validation.executable_task_ids), 'POLICY_COVERAGE_BLOCKED')
            require(validation.constraints_verified and not validation.blocking_uncertainty_ids and
                    not intent.blocking_uncertainty_ids, 'POLICY_APPROVAL_BLOCKED')
            require(set(c.acknowledged_warnings) == set(validation.warning_ids) and
                    len(c.acknowledged_warnings) == len(set(c.acknowledged_warnings)), 'POLICY_WARNINGS_NOT_ACKNOWLEDGED')
            require(s.binding.approval_id is None and not one(s.facts, 'execution', False), 'POLICY_APPROVAL_SUPERSEDED')
            proposed_approval = one(c.facts, 'approval')
            approval(plan, proposed_approval)
            require(set(proposed_approval.warning_ids) == set(validation.warning_ids), 'POLICY_WARNINGS_NOT_ACKNOWLEDGED')
            return
        approved = one(s.facts, 'approval')
        approval(plan, approved)
        same_binding(approved.binding, s.binding, APPROVAL)
        require(validation.coverage != 'blocked' and validation.executable_task_ids and validation.constraints_verified and
                not validation.blocking_uncertainty_ids and not intent.blocking_uncertainty_ids, 'POLICY_APPROVAL_BLOCKED')
        if code == 'C11':
            require(s.binding.execution_id is None and not one(s.facts, 'execution', False), 'POLICY_EXECUTION_ALREADY_EXISTS')
            new = one(c.facts, 'execution')
            same_binding(new.binding, s.binding, APPROVAL)
            require(new.fact_id == new.binding.execution_id and new.binding.execution_request_id == c.request_id and
                    new.execution_outcome == 'running' and not new.tasks and new.operation_key == c.next_active_execution_key,
                    'POLICY_EXECUTION_INVALID')
            return
        execution = one(s.facts, 'execution')
        same_binding(execution.binding, s.binding, EXECUTION)
        require(execution.fact_id == s.binding.execution_id, 'POLICY_REFERENCE_MISMATCH', 'execution_id')
        if code in {'C12', 'C13', 'C14', 'C23'}:
            require(execution.execution_outcome == 'running', 'POLICY_EXECUTION_NOT_RUNNING')
            if code == 'C23':
                task = one(c.facts, 'task')
                same_binding(task.binding, s.binding, EXECUTION)
                require(len(task.tasks) == 1 and task.tasks[0].task_id in plan.task_ids, 'POLICY_TASK_SELECTION_INVALID')
                row = task.tasks[0]
                require(row.task_id not in validation.blocked_task_ids or row.status == 'skipped',
                        'POLICY_BLOCKED_TASK_EXECUTED', row.task_id)
                require(row.task_id not in {t.task_id for t in execution.tasks}, 'POLICY_TASK_ALREADY_RECORDED')
                require(bool(row.result_ref) if row.status == 'success' else bool(row.error_code),
                        'POLICY_MISSING_EVIDENCE', row.task_id)
            else:
                result = one(c.facts, 'execution')
                same_binding(result.binding, s.binding, EXECUTION)
                result_outcome = outcome(result, plan, validation.blocked_task_ids)
                require(result_outcome == {'C12': 'success', 'C13': 'partial_success', 'C14': 'failed'}[code],
                        'POLICY_EXECUTION_INVALID', 'command_outcome')
                old_tasks = {t.task_id: t for t in execution.tasks}
                require(all(old_tasks.get(t.task_id, t) == t for t in result.tasks), 'POLICY_SAVED_TASK_CHANGED')
            return
        result_outcome = outcome(execution, plan, validation.blocked_task_ids)
        require(s.control_status == (S.FAILED if result_outcome == 'failed' else S.COMPLETED),
                'POLICY_EXECUTION_STATE_CONFLICT')
        if code in {'C17', 'C18', 'C22'}:
            proposed = one(c.facts, 'generation')
            same_binding(proposed.binding, s.binding, EXECUTION)
            current = one(s.facts, 'generation', False)
            if code != 'C17':
                require(s.binding.report_attempt is not None, 'POLICY_MISSING_REFERENCE', 'report_attempt')
            expected_attempt = 1 if code == 'C17' else s.binding.report_attempt + (1 if code == 'C22' else 0)
            require(proposed.binding.report_attempt == expected_attempt and
                    proposed.generation_status == self.command_specs[code].target, 'POLICY_REPORT_ATTEMPT_MISMATCH')
            require(not one(s.facts, 'report', False), 'POLICY_REPORT_ALREADY_DELIVERED')
            if current:
                same_binding(current.binding, s.binding, REPORT)
            if code == 'C22':
                require(s.observed_root_status in {None, 'running', 'partial', 'failed', 'interrupted'},
                        'POLICY_ROOT_STATE_CONFLICT')
                require(proposed.operation_key == c.next_active_execution_key, 'POLICY_STALE_ACTIVE_KEY')
            elif code == 'C17':
                require(s.binding.report_attempt is None and proposed.operation_key == c.next_active_execution_key,
                        'POLICY_REPORT_ATTEMPT_MISMATCH')
            return
        generation = one(s.facts, 'generation')
        same_binding(generation.binding, s.binding, REPORT)
        if self._report_extension(s, c, plan, validation, execution, generation):
            return
        if code.startswith('C21-'):
            failure = one(c.facts, 'failure')
            same_binding(failure.binding, s.binding, REPORT)
            require(bool(failure.error_code), 'POLICY_FAILURE_INVALID')
            return
        if code == 'C20':
            report = one(c.facts, 'report')
            same_binding(report.binding, s.binding, REPORT)
            require((not report.valid_core_insight_count or bool(report.evidence_ids)) and
                    report.report_status == 'unavailable' and
                    (not report.evidence_ids or report.valid_core_insight_count == 0) and bool(report.error_code),
                    'POLICY_REPORT_UNAVAILABLE_INVALID')
            return
        raise Rejected('POLICY_COMMAND_NOT_IMPLEMENTED')

    def _report_extension(self, s, c, plan, validation, execution, generation):
        return False

    @staticmethod
    def _profile_input(profile: BusinessFact, current_input: BusinessFact):
        require(all(getattr(profile, name) == getattr(current_input, name) for name in
                    ('input_file_id', 'content_hash', 'profile_options_hash')), 'POLICY_INPUT_CHANGED', 'profile')
