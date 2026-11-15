from typing import Literal

from pydantic import Field

from .analysis_plan import AnalysisTask, Name, PlanModel, Text
from .dataset_profile import DatasetRef
from .execution import Cell, ResultTable
from .intent import LLMMetadata
from .provenance import Provenance


class Evidence(PlanModel):
    evidence_id: Name
    task_id: Name
    data_ref: Name
    result_field: Name
    evidence_type: Literal["metric", "ranking", "maximum", "minimum", "proportion", "difference", "change_rate", "comparison", "coverage"]
    value: dict[str, Cell]
    scope: Text
    calculation: Text
    statement: Text
    source_row_indices: list[int]
    related_result_refs: list[Name] = Field(default_factory=list)


class ChartSpec(PlanModel):
    chart_id: Name
    task_id: Name
    title: Text
    chart_type: Literal["bar", "line", "pie", "kpi", "table"]
    dimension: Name | None
    metrics: list[Name]
    data_ref: Name
    supported_chart_types: list[Literal["bar", "line", "pie", "kpi", "table"]]
    evidence_refs: list[Name]
    display_limit: int = Field(ge=1, le=50)
    order: Literal["value_desc", "dimension_asc", "original"]
    note: Text | None


class Insight(PlanModel):
    insight_id: Name
    task_id: Name
    fact: Text
    finding: Text
    implication: Text
    recommendation: Text
    evidence_refs: list[Name]
    limitations: list[Text]


class Summary(PlanModel):
    headline: Text
    overview: Text
    evidence_refs: list[Name]


class KeyMetric(PlanModel):
    label: Text
    value: Cell
    unit: str | None
    evidence_ref: Name


class Recommendation(PlanModel):
    text: Text
    evidence_refs: list[Name]


class UncompletedTask(PlanModel):
    task_id: Name
    title: Text
    priority: Literal["P0", "P1", "P2"]
    reason: Text


class AnalysisReport(DatasetRef, PlanModel):
    report_id: Name
    execution_id: Name
    plan_version: int
    report_status: Literal["complete", "partial", "unavailable"]
    goal_coverage: Literal["complete", "partial", "blocked"]
    analysis_goal: Text
    dataset_name: Text
    dataset_row_count: int
    execution_source: Literal["engine", "imported"]
    summary: Summary
    key_metrics: list[KeyMetric]
    insights: list[Insight]
    charts: list[ChartSpec]
    recommendations: list[Recommendation]
    limitations: list[Text]
    uncompleted_tasks: list[UncompletedTask]
    evidence: list[Evidence]
    result_data: dict[str, ResultTable]
    execution_metadata: dict[str, dict]
    task_metadata: dict[str, AnalysisTask]
    fact_validation: Literal["structured_facts_verified_interpretations_unverified"]
    llm: LLMMetadata | None
    provenance: Provenance
    preview_url: str
    download_url: str
    generated_at: str


class DraftInsight(PlanModel):
    primary_evidence_id: Name
    evidence_refs: list[Name] = Field(min_length=1, max_length=8)
    finding_type: Literal["highlight", "difference", "concentration", "trend", "coverage"]
    implication: Text
    recommendation: Text
    limitations: list[Text] = Field(max_length=5)


class InsightDraft(PlanModel):
    insights: list[DraftInsight] = Field(min_length=1, max_length=8)
