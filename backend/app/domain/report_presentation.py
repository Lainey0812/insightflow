"""Deterministic report view model; the persisted AnalysisReport remains unchanged."""
from typing import Literal
from pydantic import Field
from .analysis_plan import PlanModel
from .analysis_report import Evidence


class PresentationMetric(PlanModel):
    label: str
    display_value: str
    caption: str
    evidence_refs: list[str]


class PresentationFinding(PlanModel):
    title: str
    body: str
    evidence_refs: list[str]


class DatasetOverview(PlanModel):
    """Upload-wide profile facts, never a filtered row-validity estimate."""
    field_count: int = Field(ge=1)
    missing_cell_count: int = Field(ge=0)
    duplicate_row_count: int = Field(ge=0)


class ReportPresentation(PlanModel):
    presentation_version: Literal['business-report-v1', 'business-report-v1.1'] = 'business-report-v1'
    report_id: str
    kind: Literal['ranking', 'general']
    title: str
    subtitle: str
    executive_summary: str
    key_metrics: list[PresentationMetric]
    findings: list[PresentationFinding]
    recommendations: list[str]
    data_notes: list[str]
    scope: list[str]
    evidence: list[Evidence]

    dataset_overview: DatasetOverview | None = None
