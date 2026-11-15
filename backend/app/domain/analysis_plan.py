"""V1 planning contracts, separate from the legacy sales-demo Plan."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .dataset_profile import DatasetRef
from .intent import LLMMetadata, ParsedIntent
from .provenance import Provenance

Name = Annotated[StrictStr, Field(min_length=1, max_length=120, pattern=r"\S")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=2000, pattern=r"\S")]


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnalysisStep(PlanModel):
    step_id: Name
    operation: Name
    # Unknown operations/parameters remain inspectable and become F0, never executable.
    params: dict[str, Any]


class AnalysisTask(PlanModel):
    task_id: Name
    title: Text
    business_question: Text
    priority: Literal["P0", "P1", "P2"]
    priority_reason: Text
    requirement_ids: list[Name]
    depends_on: list[Name]
    missing_inputs: list[Text] = Field(default_factory=list, max_length=10)
    steps: list[AnalysisStep] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_ids(self):
        if not self.steps and not self.missing_inputs:
            raise ValueError("A task needs steps or explicit missing inputs")
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)) or len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("Step and requirement IDs must be unique within a task")
        return self


class CoreRequirement(PlanModel):
    requirement_id: Name
    description: Text


class AnalysisPlan(DatasetRef, PlanModel):
    plan_id: Name
    plan_version: int = Field(ge=1, strict=True)
    tasks: list[AnalysisTask] = Field(max_length=10)
    # Authoritative goal supplied by application code, not an LLM completion claim.
    core_requirements: list[CoreRequirement] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_ids(self):
        for ids in ([t.task_id for t in self.tasks], [r.requirement_id for r in self.core_requirements]):
            if len(ids) != len(set(ids)):
                raise ValueError("Task and core requirement IDs must be unique")
        return self


class PlannerDraft(PlanModel):
    tasks: list[AnalysisTask] = Field(min_length=1, max_length=10)


ReasonCode = Literal["READY", "MISSING_FIELD", "INVALID_DATA", "UNSUPPORTED_OPERATION",
                     "REQUIRES_TRANSFORMATION", "INVALID_FIELD_REFERENCE", "TYPE_MISMATCH",
                     "INVALID_OPERATION_ORDER", "UNSUPPORTED_DEPENDENCY", "INVALID_SCHEMA",
                     "DATASET_VERSION_MISMATCH", "UNKNOWN_REQUIREMENT", "CORE_NOT_COVERED"]


class ValidationIssue(PlanModel):
    code: ReasonCode
    message: Text
    step_id: Name | None = None
    field: Name | None = None


class ValidationResult(PlanModel):
    task_id: Name
    feasibility: Literal["F0", "F1", "F2"]
    reason_code: ReasonCode
    validation_issues: list[ValidationIssue]
    executable: bool


class UnmetCoreRequirement(PlanModel):
    requirement_id: Name
    description: Text
    task_ids: list[Name]
    reason_codes: list[ReasonCode]


class ValidatedAnalysisPlan(PlanModel):
    plan: AnalysisPlan
    validation_results: list[ValidationResult]
    unmet_core_requirements: list[UnmetCoreRequirement]
    coverage_status: Literal["complete", "partial", "blocked"]
    executable_task_ids: list[Name]
    blocked_task_ids: list[Name]
    fully_executable: bool
    validation_version: Literal["1.0"] = "1.0"
    registry_version: str
    # A validation result is eligibility metadata, never user approval / execution permission.
    approval_required: Literal[True] = True
    llm: LLMMetadata | None = None
    provenance: Provenance
    intent_snapshot: ParsedIntent | None = None
