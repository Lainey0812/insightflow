from pydantic import BaseModel

from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.analysis_report import AnalysisReport
from app.domain.dataset_profile import DatasetProfile
from app.domain.execution import ExecutionResultV1
from app.domain.provenance import Provenance
from app.domain.intent import IntentArtifact, ParsedIntent
from app.services.analysis_report import AnalysisReportService
from .base import Node


class ReportV1Input(BaseModel):
    intent: IntentArtifact | ParsedIntent
    validated_plan: ValidatedAnalysisPlan
    execution: ExecutionResultV1
    profile: DatasetProfile


class ReportModuleNode(Node[ReportV1Input, AnalysisReport]):
    name = "report_module_v1"
    error_provenance = Provenance(source="uploaded", dataset="unavailable", notice="报告未生成，未伪造结果。")

    def __init__(self, service: AnalysisReportService):
        self.service = service

    async def process(self, payload: ReportV1Input):
        return await self.service.generate(payload.intent, payload.validated_plan, payload.execution, payload.profile)
