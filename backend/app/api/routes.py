from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.session_access import issue_session_token, session_guard, visible_sessions

from app.domain.errors import AppError
from app.domain.enums import AnalysisMode, SessionStatus
from app.domain.models import Message, SessionState
from app.domain.dataset_profile import ProfileOptions
from app.domain.intent import IntentModel, Text
from pydantic import Field
from app.services.plan_review import ApprovalRequest, PlanReviewService, RevisionRequest
from app.services.report_export import render_report
from app.domain.plan_review import SavePlanRequest, PlanVersion
from app.domain.review_presentation import ReviewPresentation
from app.review.confirmed_scope import ScopeRequest, ScopeConfirmation
from app.storage.file_store import FileStore
from app.storage.session_repository import SessionRepository
from app.workflow.orchestrator import WorkflowOrchestrator


class ClarificationRequest(IntentModel):
    answer: Text
    expected_revision: int = Field(ge=0)


class RetryPreparationRequest(IntentModel):
    expected_revision: int = Field(ge=0)


def create_router(repository: SessionRepository, files: FileStore,
                  workflow: WorkflowOrchestrator, review: PlanReviewService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(session_guard(repository.database))])

    @router.get("/health")
    def health():
        return {"status": "ok", "service": "insightflow", "mode": "real", "version": "0.1.0",
                "capabilities": {"data_profiler": "real", "intent_parser": "v1", "analysis_planner": "v1_real_workflow",
                                 "plan_validator": "v1", "report_module": "v1_standalone", "planning_and_reports": "real_planning_report_not_connected", "chat_planning_and_reports": "real_until_execution_result", "legacy_chat": "mock_isolated",
                                 "hitl": "v1_real", "analysis_engine": "v1_real", "new_ui": "real_workflow_v1",
                                 "workflow": "v1_real_until_execution_result"}}

    @router.get("/sessions")
    def sessions(request: Request):
        return visible_sessions(repository.database, repository.list(), request)

    @router.post("/sessions", response_model=SessionState, status_code=201)
    async def create_session(file: Annotated[UploadFile, File()], background_tasks: BackgroundTasks,
                             goal: Annotated[str, Form(max_length=2000)] = "",
                             manual_review: Annotated[bool, Form()] = False,
                             real_workflow: Annotated[bool, Form()] = False,
                             mode: Annotated[AnalysisMode, Form()] = AnalysisMode.GOAL_DRIVEN,
                             header_row: Annotated[int, Form(ge=1, le=100_001)] = 1,
                             sheet_name: Annotated[str | None, Form(min_length=1, max_length=31)] = None,
                             encoding: Annotated[Literal["utf-8-sig", "gb18030"], Form()] = "utf-8-sig",
                             delimiter: Annotated[Literal[",", ";", "\t", "|"], Form()] = ","):
        if manual_review and real_workflow:
            raise AppError("WORKFLOW_MODE_CONFLICT", "不能同时选择人工导入与自动真实Workflow。", 422)
        if manual_review and not goal.strip():
            raise AppError("ANALYSIS_GOAL_REQUIRED", "真实审核会话需要明确业务目标，请填写后上传。", 422)
        metadata = await files.save(file)
        options = ProfileOptions(header_row=header_row, sheet_name=sheet_name, encoding=encoding, delimiter=delimiter)
        state = SessionState(title=goal.strip()[:28] or "未命名分析", file=metadata, user_goal=goal, analysis_mode=mode,
                             workflow_kind="real_v1" if real_workflow else "manual_review" if manual_review else "legacy_mock",
                             profile_options=options, data_source="uploaded" if real_workflow or manual_review else "mock",
                             review_status="awaiting_review" if real_workflow else None,
                             messages=[Message(role="user", content=goal)])
        try:
            if real_workflow:
                state = workflow.create_real_session(state)
            else:
                repository.create(state)
        except Exception:
            files.remove(metadata)
            raise
        if real_workflow:
            workflow.trace_created(state)
        token = issue_session_token(repository.database, state.id) if manual_review or real_workflow else None
        if real_workflow:
            background_tasks.add_task(workflow.prepare, state.id, real_workflow=True, identity=workflow.identity(state))
            return JSONResponse(status_code=201, content={**state.model_dump(mode="json"), "review_access_token": token})
        result = await workflow.prepare(state.id, options, manual_review=manual_review)
        if token:
            return JSONResponse(status_code=201, content={**result.model_dump(mode="json"), "review_access_token": token})
        return result

    @router.get("/sessions/{session_id}", response_model=SessionState)
    def get_session(session_id: str):
        return repository.get(session_id)

    @router.get("/sessions/{session_id}/plans")
    def get_plans(session_id: str):
        state = repository.get(session_id)
        return review.audit.versions(session_id) if state.review_plan else state.plans

    @router.post("/sessions/{session_id}/plans", response_model=SessionState)
    def save_plan(session_id: str, request: SavePlanRequest):
        if repository.get(session_id).workflow_kind == "real_v1":
            raise AppError("GENERATED_PLAN_MANAGED_BY_WORKFLOW", "真实主流程的初始计划由服务端模型生成；不能用人工JSON替换。", 409)
        return review.save_v1(session_id, request)

    @router.get("/sessions/{session_id}/plan", response_model=PlanVersion)
    def current_plan(session_id: str):
        record = repository.get(session_id).review_plan
        if record is None:
            raise AppError("REAL_PLAN_NOT_AVAILABLE", "该会话尚无真实 V1 计划。", 404)
        return record

    from app.review.analysis_basis import BasisRequest

    @router.post('/sessions/{session_id}/analysis-basis', response_model=SessionState)
    def update_analysis_basis(session_id: str, request: BasisRequest):
        return review.update_analysis_basis(session_id,request)

    @router.get('/sessions/{session_id}/review', response_model=ReviewPresentation)
    def review_presentation(session_id: str):
        return review.review_presentation(session_id)

    @router.get('/sessions/{session_id}/constraint-audits')
    def constraint_audits(session_id: str):
        repository.get(session_id)
        return review.audit.constraint_audits(session_id)

    @router.get("/sessions/{session_id}/plans/{version}", response_model=PlanVersion)
    def plan_version(session_id: str, version: int):
        repository.get(session_id)
        for record in review.audit.versions(session_id):
            if record.plan_version == version:
                return record
        raise AppError("PLAN_VERSION_NOT_FOUND", "本会话没有此计划版本。", 404)

    @router.get("/sessions/{session_id}/approvals")
    def approvals(session_id: str):
        repository.get(session_id)
        return [{**record.model_dump(mode="json"),
                 "execution_ids": [eid for eid in repository.get(session_id).engine_execution_ids
                    if review_execution_approval(eid) == record.approval_id]}
                for record in review.audit.approvals(session_id)]

    def review_execution_approval(execution_id):
        # Includes unfinished executions; the immutable execution snapshot already exists at claim time.
        from contextlib import closing
        import json
        with closing(repository.database.connect()) as conn:
            row = conn.execute("SELECT approval FROM executions WHERE id=?", (execution_id,)).fetchone()
        return json.loads(row["approval"])["approval_id"] if row else None

    @router.post('/sessions/{session_id}/review-answers', response_model=SessionState)
    async def answer_review(session_id: str, request: ClarificationRequest, background_tasks: BackgroundTasks):
        state = workflow.begin_review_answer(session_id, request.answer, request.expected_revision)
        background_tasks.add_task(workflow.prepare_real, session_id, workflow.identity(state))
        return state

    @router.post("/sessions/{session_id}/clarifications", response_model=SessionState)
    async def clarify_intent(session_id: str, request: ClarificationRequest, background_tasks: BackgroundTasks):
        if repository.get(session_id).workflow_kind == "real_v1":
            state = workflow.begin_real_clarification(session_id, request.answer, request.expected_revision)
            background_tasks.add_task(workflow.prepare_real, session_id, workflow.identity(state))
            return state
        return await workflow.clarify(session_id, request.answer, request.expected_revision)

    @router.post("/sessions/{session_id}/retry-preparation", response_model=SessionState)
    async def retry_preparation(session_id: str, request: RetryPreparationRequest, background_tasks: BackgroundTasks):
        state = workflow.begin_real_retry(session_id, request.expected_revision)
        background_tasks.add_task(workflow.prepare_real, session_id, workflow.identity(state))
        return state

    @router.post('/sessions/{session_id}/scope-preview')
    def scope_preview(session_id: str, request: ScopeRequest):
        return review.scope_preview(session_id, request)

    @router.post('/sessions/{session_id}/scope-confirmations', response_model=SessionState)
    def confirm_scope(session_id: str, request: ScopeConfirmation):
        return review.confirm_scope(session_id, request)

    @router.post("/sessions/{session_id}/plan-revisions", response_model=SessionState)
    def revise_plan(session_id: str, request: RevisionRequest):
        return review.revise(session_id, request)

    @router.post("/sessions/{session_id}/approvals", response_model=SessionState)
    def approve_plan(session_id: str, request: ApprovalRequest):
        return review.approve(session_id, request)

    @router.post("/sessions/{session_id}/execute", response_model=SessionState)
    async def execute(session_id: str, request: ApprovalRequest):
        return await workflow.execute(session_id, request)

    def completed_report(session_id: str):
        state = repository.get(session_id)
        if state.status != SessionStatus.COMPLETED or not state.report:
            raise AppError("REPORT_NOT_READY", "报告尚未生成，请先确认并执行分析计划。")
        return state.report

    @router.get("/sessions/{session_id}/report")
    def get_report(session_id: str):
        return completed_report(session_id)

    @router.get("/sessions/{session_id}/report/preview", response_class=HTMLResponse)
    def preview_report(session_id: str):
        return HTMLResponse(render_report(completed_report(session_id)))

    @router.get("/sessions/{session_id}/report/download", response_class=HTMLResponse)
    def download_report(session_id: str):
        report = completed_report(session_id)
        return HTMLResponse(render_report(report), headers={
            "Content-Disposition": f'attachment; filename="insightflow-report-{session_id}.html"'
        })

    return router
