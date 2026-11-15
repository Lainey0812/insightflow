from fastapi import APIRouter, Depends
from app.api.session_access import session_guard
from fastapi.responses import HTMLResponse

from app.domain.analysis_plan import PlanModel, ValidatedAnalysisPlan
from app.domain.analysis_report import AnalysisReport
from app.domain.report_presentation import ReportPresentation
from app.reporting.presentation import build_presentation
from app.domain.execution import ExecutionResultV1
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, ParsedIntent
from app.reporting.export import render_report_v1
from app.services.analysis_report import AnalysisReportService
from app.storage.dataset_repository import DatasetRepository
from app.storage.report_repository import ReportRepository


class GenerateReportRequest(PlanModel):
    intent: IntentArtifact | ParsedIntent
    validated_plan: ValidatedAnalysisPlan
    execution: ExecutionResultV1


def create_report_router(service: AnalysisReportService, datasets: DatasetRepository, reports: ReportRepository, executions=None):
    router = APIRouter(prefix="/api/v1/reports", tags=["Report Module V1"], dependencies=[Depends(session_guard(reports.database))])

    @router.post("", response_model=AnalysisReport, status_code=201)
    async def generate(request: GenerateReportRequest):
        if request.execution.source == "engine":
            raise AppError("REPORT_EXTERNAL_SOURCE_REQUIRED", "独立接口仅接收明确标记为导入的计算结果；引擎来源需由内部工作流保证。", 422)
        profile = datasets.profile(request.execution.dataset_id, request.execution.dataset_version)
        report = await service.generate(request.intent, request.validated_plan, request.execution, profile)
        reports.save(report, request.model_dump(mode="json"))
        return report

    @router.get("/{report_id}", response_model=AnalysisReport)
    def get(report_id: str):
        return reports.get(report_id)

    @router.get("/{report_id}/presentation", response_model=ReportPresentation)
    def presentation(report_id: str):
        report = reports.get(report_id)
        profile = datasets.profile(report.dataset_id, report.dataset_version)
        return build_presentation(report, profile)

    @router.get("/{report_id}/download", response_class=HTMLResponse)
    def download(report_id: str):
        report = reports.get(report_id)
        profile = datasets.profile(report.dataset_id, report.dataset_version)
        return HTMLResponse(render_report_v1(report, build_presentation(report, profile)), headers={
            "Content-Disposition": f'attachment; filename="{report.report_id}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff"})

    if executions:
        @router.get("/{report_id}/execution", response_model=ExecutionResultV1)
        def source_execution(report_id: str):
            report = reports.get(report_id)
            if report.execution_source != "engine" or not reports.owner(report_id):
                raise AppError("REPORT_EXECUTION_UNAVAILABLE", "此导入报告没有服务端引擎执行记录。", 404)
            return executions.complete(report.execution_id)

    return router
