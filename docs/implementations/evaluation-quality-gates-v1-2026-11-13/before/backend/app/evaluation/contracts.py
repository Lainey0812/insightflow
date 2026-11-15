"""Unified evaluation records shared by every agent adapter.

A record states what was observed. Values interpreted after the fact carry a
Derivation naming their sources, and historical raw results stay in ``legacy``.
Missing evidence stays None; it is never filled from current source constants.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionStatus = Literal['PENDING', 'RUNNING', 'WAITING_APPROVAL', 'COMPLETED', 'BLOCKED', 'FAILED', 'TIMEOUT', 'CANCELLED']
# WAITING_APPROVAL is a live pause that a person may still resolve. BLOCKED means the
# run stopped at a gate without proceeding; neither one means the agent crashed.
TERMINAL_STATUSES = frozenset({'COMPLETED', 'BLOCKED', 'FAILED', 'TIMEOUT', 'CANCELLED'})
Verdict = Literal['PASS', 'FAIL', 'NOT_EVALUATED', 'EVALUATOR_ERROR']
E2EVerdict = Literal['PASS', 'FAIL', 'NOT_EVALUATED', 'EVALUATOR_ERROR', 'INFRA_ERROR']
Scope = Literal['e2e', 'node']
Provenance = Literal['recorded', 'legacy_projection']
RunKind = Literal['golden', 'tc_regression']
RunStatus = Literal['FINISHED', 'INCOMPLETE']
FailureOrigin = Literal['agent', 'infrastructure']


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Derivation(Record):
    value: Any
    sources: list[str]
    basis: str


class EvaluatorRef(Record):
    evaluator_id: str
    evaluator_version: str | None
    config_sha256: str | None
    required: bool | None
    scope: Scope | None


class EvaluationRun(Record):
    schema_version: Literal['evaluation-run-v1'] = 'evaluation-run-v1'
    run_id: str
    run_kind: RunKind
    provenance: Provenance
    agent_id: str | None
    agent_version: str | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_hash: str | None
    evaluator_manifest: list[EvaluatorRef] | None
    execution_config: dict[str, Any]
    created_at: str | None
    finished_at: str | None
    status: RunStatus
    case_execution_refs: list[str]
    missing_case_ids: list[str] = Field(default_factory=list)
    not_started_case_ids: list[str] = Field(default_factory=list)
    projection: dict[str, Derivation] = Field(default_factory=dict)
    unverified: list[str] = Field(default_factory=list)
    legacy: dict[str, Any] | None = None


class CaseExecution(Record):
    schema_version: Literal['case-execution-v1'] = 'case-execution-v1'
    execution_id: str | None
    locator: str
    run_id: str
    case_id: str
    attempt: int | None
    execution_status: ExecutionStatus | None
    failure_origin: FailureOrigin | None
    workflow_id: str | None
    started_at: str | None
    finished_at: str | None
    record_ref: str | None
    output_ref: str | None
    trace_ref: str | None
    error_code: str | None
    blocking_stage: str | None
    expect_blocked: bool = False
    provenance: Provenance
    projection: dict[str, Derivation] = Field(default_factory=dict)
    unverified: list[str] = Field(default_factory=list)
    legacy: dict[str, Any] | None = None

    @property
    def terminal(self) -> bool:
        return self.execution_status in TERMINAL_STATUSES


class EvaluatorResult(Record):
    schema_version: Literal['evaluator-result-v1'] = 'evaluator-result-v1'
    evaluator_id: str
    evaluator_version: str | None
    evaluator_config_hash: str | None
    case_execution_ref: str
    evaluation_scope: Scope
    required: bool
    verdict: Verdict
    score: float | None = None
    failure_code: str | None = None
    reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    evaluated_at: str | None
    provenance: Provenance
    basis: str | None = None
    legacy: dict[str, Any] | None = None


class E2ESummary(Record):
    schema_version: Literal['e2e-summary-v1'] = 'e2e-summary-v1'
    case_execution_ref: str
    case_id: str
    verdict: E2EVerdict
    gate: str
    reason: str
    execution_status: ExecutionStatus | None
    execution_completed: bool | None
    task_condition_met: bool | None
    required_verdicts: dict[str, Verdict]
    optional_verdicts: dict[str, Verdict]
    provenance: Provenance
