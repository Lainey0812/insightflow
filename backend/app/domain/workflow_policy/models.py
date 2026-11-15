"""Internal trusted business projections, not a public request/LLM schema.

Repositories will eventually construct these projections inside their business
transaction. A pure policy cannot authenticate evidence, reserve idempotency keys,
or prove atomic persistence. No application adapter is introduced in Phase 03-B1.
"""
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from app.domain.enums import SessionStatus

Reference = Annotated[str, Field(min_length=1, pattern=r'.*\S.*')]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', revalidate_instances='always')


class Bindings(FrozenModel):
    dataset_id: Reference | None = None
    dataset_version: Reference | None = None
    plan_version_id: Reference | None = None
    plan_id: Reference | None = None
    plan_version: int | None = Field(default=None, ge=1, strict=True)
    validation_version: Reference | None = None
    approval_id: Reference | None = None
    execution_id: Reference | None = None
    execution_request_id: Reference | None = None
    report_attempt: int | None = Field(default=None, ge=1, strict=True)


class TaskFact(FrozenModel):
    task_id: str = Field(min_length=1)
    status: Literal['success', 'failed', 'skipped']
    result_ref: str | None = None
    error_code: str | None = None


class BusinessFact(FrozenModel):
    kind: Literal['input', 'message', 'profile', 'intent', 'candidate', 'plan', 'validation',
                  'approval', 'execution', 'task', 'generation', 'report', 'failure', 'answer', 'worker_fence']
    session_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    # Explicitly refuse projections sourced from UI, Trace or raw LLM assertions.
    source: Literal['business', 'deterministic'] = 'business'
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    binding: Bindings = Field(default_factory=Bindings)
    input_file_id: str | None = None
    content_hash: str | None = None
    profile_options_hash: str | None = None
    goal_hash: str | None = None
    answers_hash: str | None = None
    intent_hash: str | None = None
    candidate_hash: str | None = None
    source_candidate_hash: str | None = None
    capability_version: str | None = None
    next_action: Literal['proceed', 'clarify'] | None = None
    artifact_origin: Literal['llm', 'code'] | None = None
    questions: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()
    executable_task_ids: tuple[str, ...] = ()
    blocked_task_ids: tuple[str, ...] = ()
    core_task_ids: tuple[str, ...] = ()
    unmet_requirement_ids: tuple[str, ...] = ()
    unmet_core_task_ids: tuple[str, ...] = ()
    coverage: Literal['complete', 'partial', 'blocked'] | None = None
    constraints_verified: StrictBool = False
    blocking_uncertainty_ids: tuple[str, ...] = ()
    warning_ids: tuple[str, ...] = ()
    tasks: tuple[TaskFact, ...] = ()
    approval_status: Literal['approved', 'revoked'] | None = None
    execution_outcome: Literal['running', 'success', 'partial_success', 'failed'] | None = None
    generation_status: Literal['queued', 'generating', 'completed', 'failed', 'unavailable'] | None = None
    report_id: Reference | None = None
    report_status: Literal['complete', 'partial', 'unavailable'] | None = None
    goal_coverage: Literal['complete', 'partial', 'blocked'] | None = None
    evidence_ids: tuple[str, ...] = ()
    valid_core_insight_count: int = Field(default=0, ge=0, strict=True)
    error_code: str | None = None
    failed_phase: SessionStatus | None = None
    retryable: StrictBool = False
    operation_key: str | None = None

    @model_validator(mode='after')
    def unique_sets(self):
        for name in ('task_ids', 'executable_task_ids', 'blocked_task_ids', 'core_task_ids',
                     'unmet_requirement_ids', 'unmet_core_task_ids', 'blocking_uncertainty_ids', 'warning_ids', 'evidence_ids'):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f'Duplicate values in {name}')
        if len(self.tasks) != len({t.task_id for t in self.tasks}):
            raise ValueError('Duplicate task result')
        return self


class IdempotencyFact(FrozenModel):
    session_id: str
    workflow_id: str
    request_id: str
    command_id: str
    payload_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    status: Literal['in_progress', 'completed']
    # The branch after the original commit, not a permission to mutate it again.
    effective_binding: Bindings
    response_ref: str | None = None


class PolicySnapshot(FrozenModel):
    policy_scope: Literal['native_v1.1', 'native_v1.2', 'legacy_session_v1'] = 'native_v1.1'
    session_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    root_run_id: str = Field(min_length=1)
    exists: StrictBool = True
    revision: int = Field(ge=0, strict=True)
    control_status: SessionStatus | None
    active_execution_key: str | None = None
    binding: Bindings = Field(default_factory=Bindings)
    facts: tuple[BusinessFact, ...] = ()
    idempotency: tuple[IdempotencyFact, ...] = ()
    # Only a veto/consistency signal. It is never evidence of business success.
    observed_root_status: Literal['queued', 'running', 'waiting_input', 'waiting_approval',
                                  'complete', 'partial', 'unavailable', 'failed', 'interrupted'] | None = None
    capability_version: str | None = None
    origin_message_id: str | None = None
    authorized_input_file_ids: tuple[str, ...] = ()
    existing_workflow_ids: tuple[str, ...] = ()
    reserved_root_ids: tuple[str, ...] = ()


class PolicyCommand(FrozenModel):
    command_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0, strict=True)
    active_execution_key: str | None = None
    next_active_execution_key: str | None = None
    binding: Bindings = Field(default_factory=Bindings)
    facts: tuple[BusinessFact, ...] = ()
    remove_task_ids: tuple[str, ...] = ()
    acknowledged_warnings: tuple[str, ...] = ()
    recovery: StrictBool = False
    origin_message_id: str | None = None
    parent_workflow_id: str | None = None

    def payload_hash(self) -> str:
        # Compute from actual fields; never trust a supplied client payload hash.
        encoded = json.dumps(self.model_dump(mode='json'), ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()
        return sha256(encoded).hexdigest()


class ExpectedTransition(FrozenModel):
    owner: Literal['control', 'generation', 'creation', 'span']
    source: str | None
    target: str


class PolicyDecision(FrozenModel):
    decision: Literal['allow', 'deny']
    reason_code: str
    action: Literal['execute', 'observe', 'replay', 'none']
    policy_scope: Literal['native_v1.1', 'native_v1.2', 'legacy_session_v1']
    command_id: str
    expected_transition: ExpectedTransition | None = None
    required_evidence: tuple[str, ...] = ()
    replay_ref: str | None = None
    detail_fields: tuple[str, ...] = ()
