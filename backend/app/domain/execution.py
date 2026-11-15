"""Shared Engine and Report execution contracts; imported reports remain compatible."""
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from .analysis_plan import Name, PlanModel, Text, ValidatedAnalysisPlan
from .intent import ParsedIntent
from .provenance import Provenance
from .dataset_profile import DatasetRef, LogicalType

Cell = Annotated[StrictStr, Field(max_length=10 * 1024 * 1024)] | StrictInt | StrictFloat | StrictBool | None
NonNegative = Annotated[int, Field(strict=True, ge=0)]


class ResultColumn(PlanModel):
    field: Name
    label: Text
    logical_type: LogicalType
    role: Literal["dimension", "metric"]
    unit: Annotated[StrictStr, Field(max_length=40)] | None


class TotalReference(PlanModel):
    metric_field: Name
    result_id: Name
    result_field: Name


class ResultTable(PlanModel):
    result_id: Name
    # Profiler permits 256 source columns; a task can append at most 20 derived fields.
    columns: list[ResultColumn] = Field(min_length=1, max_length=276)
    rows: list[dict[str, Cell]] = Field(max_length=5000)
    truncated: bool = Field(strict=True)
    total_result_rows: NonNegative
    row_offset: NonNegative = 0
    total_refs: list[TotalReference] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def structure(self):
        fields = [column.field for column in self.columns]
        if len(fields) != len(set(fields)) or any(set(row) != set(fields) for row in self.rows):
            raise ValueError("Unique columns and exact row fields required")
        if self.total_result_rows < len(self.rows) or (self.truncated != (self.total_result_rows > len(self.rows))):
            raise ValueError("Truncation metadata inconsistent")
        for column in self.columns:
            for row in self.rows:
                value = row[column.field]
                if value is None:
                    continue
                kind = column.logical_type
                valid = ((kind == LogicalType.INTEGER and isinstance(value, int) and not isinstance(value, bool)) or
                         (kind == LogicalType.NUMBER and isinstance(value, (int, float)) and not isinstance(value, bool)) or
                         (kind == LogicalType.BOOLEAN and isinstance(value, bool)) or
                         (kind == LogicalType.MIXED) or
                         (kind in {LogicalType.TEXT, LogicalType.DATE, LogicalType.DATETIME, LogicalType.TIME} and isinstance(value, str)))
                if not valid:
                    raise ValueError("Result values must agree with logical types")
        ids = [ref.metric_field for ref in self.total_refs]
        if len(ids) != len(set(ids)) or not set(ids) <= set(fields):
            raise ValueError("Total reference metric must be unique and exist")
        return self


class ExecutionError(PlanModel):
    code: Name
    message: Text
    task_id: Name | None = None
    step_id: Name | None = None


class StepExecutionLog(PlanModel):
    step_id: Name
    operation: Name
    status: Literal["success", "failed"]
    input_row_count: NonNegative
    output_row_count: NonNegative | None
    duration_ms: float = Field(ge=0)
    warnings: list[Text] = Field(default_factory=list)
    error: ExecutionError | None = None


class SampleField(PlanModel):
    field: Name
    label: Text
    missing_count: NonNegative


class MetricParticipation(PlanModel):
    function: Literal['count', 'sum', 'avg', 'median', 'min', 'max', 'distinct_count']
    field: Name | None
    label: Text
    basis: Literal['rows', 'non_null_values', 'distinct_non_null_values']
    participating_count: NonNegative

    @model_validator(mode='after')
    def basis_matches_function(self):
        expected = ('rows' if self.function == 'count' and self.field is None else
                    'distinct_non_null_values' if self.function == 'distinct_count' else 'non_null_values')
        if self.basis != expected or (self.field is None and self.function != 'count'):
            raise ValueError('Metric participation must match the actual function and source field')
        return self


class SampleStatistics(PlanModel):
    version: Literal['execution-sample-v1'] = 'execution-sample-v1'
    scope: Literal['before_single_aggregate'] = 'before_single_aggregate'
    aggregate_step_id: Name
    input_row_count: NonNegative
    key_fields: list[SampleField]
    complete_row_count: NonNegative | None
    missing_row_count: NonNegative | None
    metrics: dict[Name, MetricParticipation]

    @model_validator(mode='after')
    def consistent_counts(self):
        fields = [field.field for field in self.key_fields]
        if len(fields) != len(set(fields)):
            raise ValueError('Key fields must be unique')
        if not fields:
            if self.complete_row_count is not None or self.missing_row_count is not None:
                raise ValueError('Field-free counts have no joint completeness statistic')
        elif (self.complete_row_count is None or self.missing_row_count is None or
              self.complete_row_count + self.missing_row_count != self.input_row_count):
            raise ValueError('Complete and missing rows must partition aggregate input')
        if any(field.missing_count > self.input_row_count for field in self.key_fields):
            raise ValueError('Field missing count exceeds aggregate input')
        if fields and (max(field.missing_count for field in self.key_fields) > self.missing_row_count or
                       self.missing_row_count > sum(field.missing_count for field in self.key_fields)):
            raise ValueError('Joint missing rows must agree with field missing counts')
        for metric in self.metrics.values():
            if metric.participating_count > self.input_row_count:
                raise ValueError('Metric sample count exceeds aggregate input')
            if metric.basis == 'rows' and metric.participating_count != self.input_row_count:
                raise ValueError('Row count includes every input row')
            if metric.field is not None and metric.field not in fields:
                raise ValueError('Metric source must be a key field')
            if metric.field is not None:
                missing = next(f.missing_count for f in self.key_fields if f.field == metric.field)
                if metric.participating_count != self.input_row_count - missing:
                    raise ValueError('Participant count describes non-null source records, not distinct output')
        return self


class TaskExecutionMetadata(PlanModel):
    input_row_count: NonNegative
    started_at: Text
    finished_at: Text
    duration_ms: float = Field(ge=0)
    preview_row_count: NonNegative
    metric_valid_counts: dict[str, NonNegative] = Field(default_factory=dict)
    sample_statistics: SampleStatistics | None = None
    analysis_basis: dict | None = None
    steps: list[StepExecutionLog] = Field(default_factory=list)
    warnings: list[Text] = Field(default_factory=list)


class ApprovedExecutionSnapshot(PlanModel):
    """Server-owned approved snapshot. Never accepted by the execution HTTP endpoint."""
    approval_id: Name
    approved_at: Text
    status: Literal["approved", "revoked"] = "approved"
    validated_plan: ValidatedAnalysisPlan
    intent: ParsedIntent
    resolved_uncertainty_ids: list[Name] = Field(default_factory=list)
    constraints_confirmed: bool = Field(default=False, strict=True)
    session_id: Name | None = None
    acknowledged_warnings: list[Name] = Field(default_factory=list)


class ExecutionRequest(PlanModel):
    session_id: Name
    plan_id: Name
    plan_version: int = Field(ge=1, strict=True)
    execution_request_id: Name


class ExecutedTask(PlanModel):
    task_id: Name
    status: Literal["success", "failed", "skipped"]
    result: ResultTable | None
    effective_row_count: NonNegative
    valid_sample_count: NonNegative | None
    sample_definition: Text
    scope: Text
    calculation: Text
    failure_reason: Text | None
    result_id: Name | None = None
    result_ref: Name | None = None
    row_count: NonNegative | None = None
    execution_metadata: TaskExecutionMetadata | None = None
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "success" and (self.result is None or self.failure_reason is not None):
            raise ValueError("Success requires result and no failure reason")
        if self.status != "success" and (self.result is not None or self.failure_reason is None):
            raise ValueError("Incomplete tasks need reason and no result")
        samples = self.execution_metadata.sample_statistics if self.execution_metadata else None
        if samples and (self.status != 'success' or samples.input_row_count != self.effective_row_count):
            raise ValueError('Sample statistics must belong to the successful aggregate input')
        if self.valid_sample_count is not None and self.valid_sample_count > self.effective_row_count:
            raise ValueError("Valid samples cannot exceed effective rows")
        if self.result_id is not None and (self.result is None or self.result_id != self.result.result_id):
            raise ValueError("Result ID must match result table")
        if self.row_count is not None and self.result is not None and self.row_count != self.result.total_result_rows:
            raise ValueError("Full result row count inconsistent")
        return self


class ExecutionResultV1(DatasetRef, PlanModel):
    execution_id: Name
    plan_id: Name
    plan_version: int = Field(strict=True, ge=1)
    approved_plan_version: int = Field(strict=True, ge=1)
    execution_status: Literal["success", "partial_success", "failed"]
    source: Literal["engine", "imported", "mock"]
    producer: Text
    session_id: Name | None = None
    execution_request_id: Name | None = None
    approval_id: Name | None = None
    started_at: Text | None = None
    finished_at: Text | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    result_view: Literal["preview", "complete"] | None = None
    provenance: Provenance | None = None
    errors: list[ExecutionError] = Field(default_factory=list)
    warnings: list[Text] = Field(default_factory=list)
    tasks: list[ExecutedTask] = Field(max_length=10)

    @model_validator(mode="after")
    def outcome(self):
        ids = [task.task_id for task in self.tasks]
        result_ids = [task.result.result_id for task in self.tasks if task.result]
        if len(ids) != len(set(ids)) or len(result_ids) != len(set(result_ids)):
            raise ValueError("Task and result IDs must be unique")
        successful = sum(task.status == "success" for task in self.tasks)
        expected = "failed" if not successful else ("success" if successful == len(self.tasks) else "partial_success")
        if self.execution_status != expected:
            raise ValueError("Execution status inconsistent with task outcomes")
        if sum(len(t.result.rows) * len(t.result.columns) for t in self.tasks if t.result) > 100_000:
            raise ValueError("Execution results exceed report size limit")
        return self
