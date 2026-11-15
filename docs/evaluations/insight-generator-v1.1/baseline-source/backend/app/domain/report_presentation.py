"""Deterministic report view model; the persisted AnalysisReport remains unchanged."""
from typing import Literal
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


class ReportPresentation(PlanModel):
    presentation_version: Literal['business-report-v1'] = 'business-report-v1'
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
