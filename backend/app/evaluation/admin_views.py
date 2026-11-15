"""Response models for the evaluation discovery lists and the detail and evidence views.

Fields the run or dataset did not record stay null. Counts come from the Phase 1 RunView.
A dataset is tied to a run by a verified hash match, or only by the configured run root when the
run recorded no hash (a weak path link). A run that recorded a different hash is a mismatch.
"""
from typing import Any, Literal

from pydantic import Field

from .contracts import (Derivation, E2EVerdict, ExecutionStatus, FailureOrigin, FileCheckStatus, FileRole, IntegrityStatus,
                        Provenance, Record, Requirement, RunStatus, Scope, Verdict)

RunType = Literal['golden', 'tc_regression']
DatasetType = Literal['golden', 'tc']
FreezeStatus = Literal['UNDECLARED']


class DiscoveryWarningModel(Record):
    code: str
    root_id: str | None = None
    entry: str | None = None
    detail: str | None = None


class RunListItem(Record):
    run_id: str
    run_type: RunType
    created_at: str | None
    lifecycle_status: RunStatus
    integrity_status: IntegrityStatus | None
    agent_id: str | None
    agent_version: str | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_hash: str | None
    case_count: int
    evaluated_case_count: int


class RunListPage(Record):
    items: list[RunListItem]
    total: int
    page: int
    page_size: int
    discovery_warnings: list[DiscoveryWarningModel]


class DatasetListItem(Record):
    dataset_id: str
    dataset_version: str | None
    dataset_hash: str
    dataset_type: DatasetType
    case_count: int
    source: str
    freeze_status: FreezeStatus
    related_run_count: int
    hash_matched_run_count: int
    weak_path_run_count: int
    hash_mismatch_run_count: int = 0


class DatasetListPage(Record):
    items: list[DatasetListItem]
    total: int
    page: int
    page_size: int
    discovery_warnings: list[DiscoveryWarningModel] = Field(default_factory=list)


Relation = Literal['hash_match', 'weak_path', 'hash_mismatch']
TrustLabel = Literal['verified', 'partial_verified', 'unverified', 'incomplete', 'none']
CaseState = Literal['present', 'missing', 'not_started', 'unreadable']
Attribution = Literal['none', 'agent_execution', 'business_quality', 'evaluator_error', 'evaluation_infrastructure',
                      'undetermined', 'evidence_integrity', 'not_executed']
SlotState = Literal['recorded', 'not_recorded', 'not_applicable']
EvidenceStatus = Literal['AVAILABLE', 'NOT_RECORDED', 'UNAVAILABLE']
EvidenceIntegrity = Literal['ok', 'mismatch', 'missing', 'outside_run', 'unexpected_ref', 'not_in_manifest',
                            'unverified', 'incomplete', 'not_applicable']
EvaluatorRole = Literal['oracle', 'must_forbid', 'node_fidelity', 'legacy_oracle', 'tc_checks', 'other']


class FileCheckView(Record):
    ref: str | None
    role: FileRole
    case_id: str | None
    status: FileCheckStatus


class IntegrityView(Record):
    status: IntegrityStatus | None
    trusted: bool
    notice: str
    reasons: list[str]
    basis: str | None
    files: list[FileCheckView]
    case_status: dict[str, IntegrityStatus]


class EvaluatorManifestItem(Record):
    evaluator_id: str
    evaluator_version: str | None
    config_sha256: str | None
    required: bool | None
    requirement: Requirement | None
    scope: Scope | None


class Rate(Record):
    numerator: int
    denominator: int
    rate: float | None


class EvaluatorHealth(Record):
    evaluator_id: str
    counts: dict[str, int]
    error_rate: Rate
    not_evaluated_rate: Rate


class TrustedMetrics(Record):
    trust: TrustLabel
    trusted: bool
    notice: str
    oracle_evaluator_id: str | None
    included_case_ids: list[str]
    excluded: list[dict[str, str]]
    counts: dict[str, Any] | None
    e2e_confirmed_success_rate: Rate | None
    decidable_pass_rate: Rate | None
    evaluation_coverage: Rate | None
    execution_completion_rate: Rate | None
    evaluators: list[EvaluatorHealth]


class Attributed(Record):
    value: Attribution
    basis: str


class CaseSummary(Record):
    case_id: str
    case_state: CaseState
    execution_status: ExecutionStatus | None
    blocking_stage: str | None
    failure_origin: FailureOrigin | None
    e2e_verdict: E2EVerdict | None
    e2e_gate: str | None
    e2e_reason: str | None
    attribution: Attributed
    case_integrity: IntegrityStatus | None
    provenance: Provenance | None


class CaseCounts(Record):
    total: int
    present: int
    missing: int
    not_started: int
    unreadable: int


class RunDetail(Record):
    run_id: str
    run_type: RunType
    provenance: Provenance
    provenance_notice: str
    agent_id: str | None
    agent_version: str | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_hash: str | None
    lifecycle_status: RunStatus
    created_at: str | None
    finished_at: str | None
    execution_config: dict[str, Any]
    unverified_fields: list[str]
    projection: dict[str, Derivation]
    integrity: IntegrityView
    evaluator_manifest: list[EvaluatorManifestItem] | None
    evaluator_manifest_notice: str | None
    case_counts: CaseCounts
    missing_case_ids: list[str]
    not_started_case_ids: list[str]
    unreadable_case_ids: list[str]
    recorded_distribution: dict[str, dict[str, int]]
    metrics: TrustedMetrics
    cases: list[CaseSummary]
    redactions: list[dict[str, Any]]


class EvaluatorResultView(Record):
    evaluator_id: str
    role: EvaluatorRole
    evaluator_version: str | None
    evaluator_config_hash: str | None
    required: bool
    requirement: Requirement | None
    scope: Scope
    verdict: Verdict
    failure_code: str | None
    reason: str | None
    evidence_refs: list[str]
    evaluated_at: str | None
    provenance: Provenance
    basis: str | None
    legacy_label: dict[str, Any] | None


class EvaluatorSlot(Record):
    state: SlotState
    evaluator_id: str | None
    verdict: Verdict | None
    notice: str | None


class ExecutionView(Record):
    execution_id: str | None
    attempt: int | None
    execution_status: ExecutionStatus | None
    failure_origin: FailureOrigin | None
    blocking_stage: str | None
    error_code: str | None
    expect_blocked: bool
    started_at: str | None
    finished_at: str | None
    workflow_id: str | None
    workflow_store: Literal['isolated_run_store']
    workflow_linkable: bool
    provenance: Provenance
    projection: dict[str, Derivation]
    unverified_fields: list[str]


class E2EView(Record):
    verdict: E2EVerdict
    gate: str
    reason: str
    task_condition_met: bool | None
    required_verdicts: dict[str, Verdict]
    optional_verdicts: dict[str, Verdict]
    trusted: bool


class Availability(Record):
    available: bool
    ref: str | None
    integrity: EvidenceIntegrity
    notice: str | None


class EvidenceIndexItem(Record):
    kind: str
    status: EvidenceStatus
    reason: str | None


class CaseDetail(Record):
    run_id: str
    run_type: RunType
    case_id: str
    case_state: CaseState
    case_state_reason: str | None
    case_integrity: IntegrityStatus | None
    case_files: list[FileCheckView]
    execution: ExecutionView | None
    e2e: E2EView | None
    attribution: Attributed
    evaluators: list[EvaluatorResultView]
    slots: dict[str, EvaluatorSlot]
    execution_record: Availability
    final_output: Availability
    evidence: list[EvidenceIndexItem]
    legacy_labels: dict[str, Any] | None
    redactions: list[dict[str, Any]]


class EvidenceIntegrityView(Record):
    status: EvidenceIntegrity
    trusted: bool
    expected_sha256: str | None
    actual_sha256: str | None


class EvidenceLimits(Record):
    max_file_bytes: int
    max_response_bytes: int
    max_values: int
    max_depth: int


class EvidenceView(Record):
    run_id: str
    case_id: str
    kind: str
    status: EvidenceStatus
    reason: str | None
    ref: str | None
    integrity: EvidenceIntegrityView
    file_size_bytes: int | None
    file_sha256: str | None
    limits: EvidenceLimits
    depth_truncated_paths: list[str]
    redactions: list[dict[str, Any]]
    content: Any


class RelatedRun(Record):
    run_id: str
    run_type: RunType
    created_at: str | None
    lifecycle_status: RunStatus
    integrity_status: IntegrityStatus | None
    recorded_dataset_id: str | None
    recorded_dataset_hash: str | None
    relation: Relation


class HashVariant(Record):
    dataset_hash: str
    matches_current_source: bool
    run_count: int


class DatasetDetail(Record):
    dataset_id: str
    dataset_type: DatasetType
    dataset_version: str | None
    dataset_hash: str
    case_count: int
    source: str
    freeze_status: FreezeStatus
    freeze_notice: str
    hash_variants: list[HashVariant]
    related_runs: list[RelatedRun]
    discovery_warnings: list[DiscoveryWarningModel]
