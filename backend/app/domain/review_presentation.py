"""Sidecar presentation contracts; no changes to plans or approval snapshots."""
from typing import Any, Literal
from pydantic import Field
from .analysis_plan import PlanModel


class ConstraintProof(PlanModel):
    source: str
    raw_text: str
    status: Literal['verified', 'unmapped', 'mismatch', 'ambiguous']
    category: str
    message: str
    field_ids: list[str] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)


class ConstraintAudit(PlanModel):
    audit_version: Literal['2.0', '2.1', '2.2', '2.3'] = '2.3'
    binding: dict[str, Any]
    digest: str
    all_verified: bool
    items: list[ConstraintProof]


class ReviewIssue(PlanModel):
    code: str
    message: str
    next_step: str


class ReviewCondition(PlanModel):
    label: str
    text: str
    verification: str
    source: str


class ReviewDirection(PlanModel):
    task_id: str
    title: str
    question: str
    importance: str
    reason: str
    readiness: str
    executable: bool
    details: list[str]
    gaps: list[str]
    can_remove: bool


class ReportCapacity(PlanModel):
    policy_version: str
    supported: bool
    metric_count: int
    core_metric_count: int
    estimated_batches: int
    max_groups_per_call: int
    max_groups: int
    max_batches: int
    estimated_metadata_bytes: int
    context_estimate_only: bool
    message: str


class ScopeQuestion(PlanModel):
    filter_index: int
    keyword: str
    field_id: str
    field_name: str


class ReviewPresentation(PlanModel):
    session_id: str
    revision: int
    plan_id: str
    plan_version: int
    goal: str
    coverage: str
    conditions: list[ReviewCondition]
    directions: list[ReviewDirection]
    issues: list[ReviewIssue]
    warnings: list[dict[str, str]]
    can_approve: bool
    can_execute: bool
    audit: ConstraintAudit
    technical_details: dict[str, Any]
    report_capacity: ReportCapacity | None = None

    analysis_basis: dict[str, Any] | None = None
    data_overview: dict[str, Any] | None = None
    scope_questions: list[ScopeQuestion] = Field(default_factory=list)
    confirmation_questions: list[str] = Field(default_factory=list)
