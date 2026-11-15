from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import AnalysisMode, Operation, SessionStatus
from .dataset_profile import DatasetProfile, DatasetRef, ProfileOptions
from .analysis_plan import ValidatedAnalysisPlan
from .provenance import Provenance
from .intent import IntentArtifact
from .execution import ApprovedExecutionSnapshot
from .plan_review import PlanVersion, ReviewStatus


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowError(BaseModel):
    code: str
    message: str
    node_name: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class FileInfo(BaseModel):
    id: str
    name: str
    size: int
    extension: str
    content_sha256: str | None = None


class Intent(BaseModel):
    """Legacy phase-one intent, retained only for old persisted sessions."""
    mode: AnalysisMode
    goal: str
    ambiguities: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class DataProfile(BaseModel):
    """Legacy phase-one payload, readable only for persisted mock sessions."""
    rows: int
    columns: list[str]
    quality_notes: list[str]
    provenance: Provenance = Field(default_factory=Provenance)


class AnalysisTask(BaseModel):
    id: str = Field(default_factory=uid)
    title: str
    description: str
    operation: Operation
    priority: int = 1


class Plan(BaseModel):
    version: int
    tasks: list[AnalysisTask]
    reason: str
    created_at: str = Field(default_factory=now)
    provenance: Provenance = Field(default_factory=Provenance)


class Message(BaseModel):
    id: str = Field(default_factory=uid)
    role: Literal["user", "assistant", "system"]
    kind: Literal["text", "plan", "report", "status", "error"] = "text"
    content: str
    plan_version: int | None = None
    created_at: str = Field(default_factory=now)


class NodeRun(BaseModel):
    run_id: str
    node_name: str
    status: Literal["success", "error"]
    provenance: Provenance = Field(default_factory=Provenance)
    error: WorkflowError | None = None
    finished_at: str = Field(default_factory=now)


class TaskResult(BaseModel):
    task_id: str
    operation: Operation
    title: str
    labels: list[str]
    values: list[float]
    evidence: str


class ExecutionResult(BaseModel):
    plan_version: int
    results: list[TaskResult]
    provenance: Provenance


class ReportSection(BaseModel):
    title: str
    insight: str
    evidence: str
    result: TaskResult
    chart_option: dict[str, Any]


class Report(BaseModel):
    title: str
    sections: list[ReportSection]
    provenance: Provenance
    generated_at: str = Field(default_factory=now)


class WorkflowEvent(BaseModel):
    status: SessionStatus
    recorded_at: str = Field(default_factory=now)


class ReportGeneration(BaseModel):
    # Per-attempt authorization snapshot, not an independent Attempt entity.
    workflow_binding: dict | None = None
    execution_id: str
    session_id: str
    status: Literal["queued", "generating", "completed", "failed", "unavailable"]
    attempt: int = Field(ge=1)
    report_id: str | None = None
    error: WorkflowError | None = None
    queued_at: str = Field(default_factory=now)
    started_at: str | None = None
    finished_at: str | None = None


class SessionState(BaseModel):
    # Optional only for legacy payload compatibility; assigned atomically for new real sessions.
    workflow_id: str | None = None
    root_run_id: str | None = None
    id: str = Field(default_factory=uid)
    title: str
    status: SessionStatus = SessionStatus.CREATED
    revision: int = 0
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    data_source: Literal["mock", "uploaded"] = "mock"
    workflow_kind: Literal["legacy_mock", "manual_review", "real_v1"] = "legacy_mock"
    profile_options: ProfileOptions = Field(default_factory=ProfileOptions)
    planner_result: ValidatedAnalysisPlan | None = None
    workflow_events: list[WorkflowEvent] = Field(default_factory=list)
    file: FileInfo
    user_goal: str
    analysis_mode: AnalysisMode
    intent: IntentArtifact | Intent | None = None
    intent_history: list[IntentArtifact] = Field(default_factory=list)
    clarification_answers: list[str] = Field(default_factory=list)
    profile: DatasetProfile | DataProfile | None = None
    dataset_ref: DatasetRef | None = None
    plans: list[Plan] = Field(default_factory=list)
    current_plan_version: int | None = None
    approved_plan_version: int | None = None
    node_runs: list[NodeRun] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    review_plan: PlanVersion | None = None
    review_status: ReviewStatus | None = None
    engine_approval: ApprovedExecutionSnapshot | None = None
    engine_execution_ids: list[str] = Field(default_factory=list)
    report_generations: list[ReportGeneration] = Field(default_factory=list)
    execution_result: ExecutionResult | None = None
    report: Report | None = None
    error: WorkflowError | None = None

    @property
    def current_plan(self) -> Plan:
        return next(p for p in self.plans if p.version == self.current_plan_version)


def record_status_event(state: SessionState, previous: SessionStatus | None) -> None:
    if state.workflow_kind == "real_v1" and state.status != previous:
        state.workflow_events.append(WorkflowEvent(status=state.status))
