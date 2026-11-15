from typing import Literal

from fastapi import APIRouter, Query, Depends, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from app.domain.models import ReportGeneration
from app.api.session_access import session_guard

from app.domain.execution import ExecutionRequest, ExecutionResultV1, ResultTable


class GenerateExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_attempt: int | None = Field(default=None, ge=1, strict=True)


def create_execution_router(engine, executions, reporting=None):
    router = APIRouter(prefix="/api/v1/executions",tags=["Analysis Engine V1"], dependencies=[Depends(session_guard(executions.database))])

    @router.post("",response_model=ExecutionResultV1)
    def execute(request: ExecutionRequest, background: BackgroundTasks):
        # Only four identifiers are accepted. Plan bodies, paths and approval flags are forbidden.
        result = engine.execute(request)
        if reporting and reporting.sessions.get(request.session_id).workflow_kind == "real_v1":
            record, fresh = reporting.enqueue(result.execution_id)
            if fresh:
                background.add_task(reporting.generate, result.execution_id, record.attempt)
        return result

    @router.get("/{execution_id}",response_model=ExecutionResultV1)
    def get(execution_id: str, view: Literal["preview","complete"]="preview"):
        return executions.complete(execution_id) if view == "complete" else executions.get(execution_id)

    @router.get("/{execution_id}/results/{result_id}",response_model=ResultTable)
    def table(execution_id: str,result_id: str,offset: int=Query(0,ge=0),limit: int=Query(5000,ge=1,le=5000)):
        return executions.get_table(execution_id,result_id,offset,limit)

    if reporting:
        @router.get("/{execution_id}/report", response_model=ReportGeneration | None)
        def report_status(execution_id: str):
            executions.get(execution_id)
            return reporting.reports.generation(execution_id)

        @router.post("/{execution_id}/report", response_model=ReportGeneration, status_code=202)
        def generate_report(execution_id: str, request: GenerateExecutionReport, background: BackgroundTasks):
            record, fresh = reporting.enqueue(execution_id, request.expected_attempt)
            if fresh:
                background.add_task(reporting.generate, execution_id, record.attempt)
            return record

    return router
