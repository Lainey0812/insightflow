from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictStr, model_validator

from .dataset_profile import DatasetRef, LogicalType, PhysicalType
from .enums import AnalysisMode
from .provenance import Provenance

# Equivalent nonblank validation that also works with constrained decoders which
# interpret JSON Schema patterns as full matches rather than substring searches.
NONBLANK_PATTERN = r"[\s\S]*\S[\s\S]*"
Text = Annotated[StrictStr, Field(min_length=1, max_length=2000, pattern=NONBLANK_PATTERN)]


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextColumn(IntentModel):
    field_id: str
    name: str
    physical_type: PhysicalType
    logical_type: LogicalType


class DatasetContext(IntentModel):
    dataset_name: str
    row_count: int = Field(gt=0, strict=True)
    columns: list[ContextColumn]
    # Profiler column samples are NOT aligned rows. V1 sends no row values.
    sample_rows: list[dict[str, str]] = Field(default_factory=list, max_length=0)


class AnalysisGoal(IntentModel):
    analysis_object: Text | None
    business_goal: Text | None
    decision_goal: Text | None


class UnverifiedConstraint(IntentModel):
    raw_text: Text
    validation_status: Literal["unverified"]


class IntentConstraints(IntentModel):
    time_range: UnverifiedConstraint | None
    filters: list[UnverifiedConstraint]
    metric_requirements: list[UnverifiedConstraint]
    analysis_limits: list[UnverifiedConstraint]


class Uncertainty(IntentModel):
    id: Annotated[StrictStr, Field(min_length=1, max_length=64, pattern=NONBLANK_PATTERN)]
    # Keep canonical storage names so immutable HITL snapshots retain their digest.
    description: Text = Field(validation_alias=AliasChoices("issue", "description"), serialization_alias="issue")
    impact: Text = Field(validation_alias=AliasChoices("reason", "impact"), serialization_alias="reason")
    action: Literal["clarify", "defer", "annotate"]
    resolve_at: Literal["before_planning", "plan_approval", "before_execution"]

    @property
    def issue(self) -> str:
        return self.description

    @property
    def reason(self) -> str:
        return self.impact

    @model_validator(mode="after")
    def validate_resolution(self) -> "Uncertainty":
        if self.action == "clarify" and self.resolve_at != "before_planning":
            raise ValueError("clarify must resolve before_planning")
        if self.action == "defer" and self.resolve_at == "before_planning":
            raise ValueError("defer must resolve at plan_approval or before_execution")
        return self


class ParsedIntent(IntentModel):
    # All model-produced fields are required, including nullable values and empty arrays.
    analysis_mode: AnalysisMode
    next_action: Literal["proceed", "clarify"]
    analysis_goal: AnalysisGoal
    constraints: IntentConstraints
    uncertainties: list[Uncertainty]
    clarification_questions: list[Text] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_flow(self) -> "ParsedIntent":
        ids = [item.id for item in self.uncertainties]
        if len(ids) != len(set(ids)):
            raise ValueError("Uncertainty IDs must be unique")
        blockers = any(item.action == "clarify" for item in self.uncertainties)
        if self.analysis_mode == AnalysisMode.UNDETERMINED and self.next_action != "clarify":
            raise ValueError("undetermined must clarify")
        if blockers and self.next_action != "clarify":
            raise ValueError("Blocking uncertainty must clarify")
        if self.next_action == "clarify" and (not blockers or not self.clarification_questions):
            raise ValueError("clarify needs a blocking uncertainty and targeted questions")
        if self.next_action == "proceed" and self.clarification_questions:
            raise ValueError("proceed must not contain clarification questions")
        if self.next_action == "proceed" and not self.analysis_goal.business_goal:
            raise ValueError("Proceed needs a business goal")
        if len(self.clarification_questions) != len(set(self.clarification_questions)):
            raise ValueError("Clarification questions must not repeat")
        return self


# Public business name; same model, not a second incompatible Intent contract.
IntentResult = ParsedIntent


class LLMMetadata(IntentModel):
    provider: str
    model: str | None
    is_mock: bool


class IntentArtifact(ParsedIntent):
    user_query: str
    clarification_answers: list[str]
    dataset_ref: DatasetRef
    parse_origin: Literal["llm", "input_guard"]
    llm: LLMMetadata | None
    provenance: Provenance
    parser_version: Literal["1.0", "1.1"] = "1.0"
    prompt_version: str | None = None
    llm_attempts: int | None = Field(default=None, ge=0, le=3)
    parse_id: str | None = None
