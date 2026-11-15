"""Read contracts for the dormant Phase 02-A store, not a new state machine."""
from pydantic import BaseModel, ConfigDict
from app.domain.plan_review import PlanVersion


class WorkflowView(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    workflow_id: str
    session_id: str
    root_run_id: str
    origin_message_id: str | None
    parent_workflow_id: str | None
    input_file_id: str | None
    dataset_id: str | None
    dataset_version: str | None
    goal_text: str
    control_status: str
    control_context: dict
    revision: int
    current_plan_version_id: str | None
    current_approval_id: str | None
    current_execution_id: str | None
    origin: str
    created_at: str
    updated_at: str


class WorkflowPlanView(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    workflow_id: str
    plan_version_id: str
    source_kind: str
    version: PlanVersion
