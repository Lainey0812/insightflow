"""Immutable HITL audit contracts. Validation never implies approval."""
from typing import Literal
from pydantic import Field
from .analysis_plan import PlanModel, Name, Text, AnalysisPlan, ValidatedAnalysisPlan
from .dataset_profile import DatasetRef
from .intent import ParsedIntent
from .execution import ApprovedExecutionSnapshot

ReviewStatus = Literal["awaiting_review", "validating", "awaiting_approval", "approved", "executing", "completed", "execution_failed"]

class PlanVersion(PlanModel):
    session_id: Name
    plan_id: Name
    plan_version: int = Field(ge=1, strict=True)
    dataset_id: Name
    dataset_version: str
    validation_version: str
    created_at: str
    change_type: Literal["created", "tasks_deleted", "basis_updated", "tasks_edited", "scope_confirmed", "review_answered"]
    change_summary: Text
    validated_plan: ValidatedAnalysisPlan

class SavePlanRequest(PlanModel):
    expected_revision: int = Field(ge=0, strict=True)
    plan: AnalysisPlan
    intent: ParsedIntent

class ReviewApproval(PlanModel):
    approval_id: Name
    approval_request_id: Name
    session_id: Name
    plan_id: Name
    plan_version: int = Field(ge=1, strict=True)
    validation_version: str
    dataset_id: Name
    dataset_version: str
    approved_at: str
    approval_status: Literal["approved"] = "approved"
    acknowledged_warnings: list[str]
    snapshot: ApprovedExecutionSnapshot
