from datetime import datetime, timezone
from time import perf_counter

from app.domain.enums import SessionStatus as S
from app.domain.errors import AppError
from app.domain.execution import (ApprovedExecutionSnapshot, ExecutedTask, ExecutionError,
                                  ExecutionRequest, ExecutionResultV1)
from app.domain.models import now
from app.domain.provenance import Provenance
from app.execution.loader import DatasetLoader
from app.execution.task_runner import TaskRunner
from app.planning.validator import PlanValidator


class AnalysisEngineService:
    def __init__(self, sessions, datasets, files, executions, registry):
        self.sessions, self.datasets, self.executions, self.registry = sessions, datasets, executions, registry
        self.loader, self.runner = DatasetLoader(datasets, files), TaskRunner(registry)

    def check_approval(self, state, request):
        approval = state.engine_approval
        if state.status != S.APPROVED or approval is None:
            raise AppError("V1_APPROVAL_REQUIRED", "需要服务端保存的 V1 批准快照，旧 Mock 批准记录不能授权真实执行。", 409)
        if approval.status != "approved":
            raise AppError("APPROVAL_REVOKED", "该批准快照已撤销。", 409)
        if approval.session_id is not None and approval.session_id != state.id:
            raise AppError("APPROVAL_SESSION_MISMATCH", "审批不属于当前会话。", 403)
        if state.review_plan is not None:
            from contextlib import closing
            from app.domain.plan_review import ReviewApproval
            with closing(self.sessions.database.connect()) as conn:
                row = conn.execute("SELECT record FROM plan_approvals WHERE session_id=? AND approval_id=?",
                                   (state.id, approval.approval_id)).fetchone()
                latest = conn.execute("SELECT record FROM plan_versions WHERE session_id=? ORDER BY plan_version DESC LIMIT 1", (state.id,)).fetchone()
            if not latest or latest["record"] != state.review_plan.model_dump_json():
                raise AppError("PLAN_VERSION_MISMATCH", "会话计划不再是持久化的最新版本。", 409)
            if not row or ReviewApproval.model_validate_json(row["record"]).snapshot != approval or state.review_plan.validated_plan != approval.validated_plan:
                raise AppError("APPROVAL_SNAPSHOT_MISMATCH", "审批快照与不可变审批记录或最新计划不一致。", 409)
        plan = approval.validated_plan.plan
        if request.plan_id != plan.plan_id or request.plan_version != plan.plan_version:
            raise AppError("PLAN_VERSION_MISMATCH", "请求与批准的计划 ID 或版本不一致，不会切换到其他版本。", 409)
        if state.current_plan_version != plan.plan_version or state.approved_plan_version != plan.plan_version:
            raise AppError("PLAN_VERSION_MISMATCH", "该版本不再是会话当前批准的有效版本。", 409)
        ref = state.dataset_ref
        if ref is None or (ref.dataset_id,ref.dataset_version) != (plan.dataset_id,plan.dataset_version) or state.file.id != plan.dataset_id:
            raise AppError("DATASET_VERSION_MISMATCH", "会话、批准计划与数据集版本不一致。", 409)
        intent = approval.intent
        if intent.next_action != "proceed" or any(u.action == "clarify" for u in intent.uncertainties):
            raise AppError("BLOCKING_UNCERTAINTY", "仍有阻断性澄清事项，不能执行。", 409)
        known = {u.id for u in intent.uncertainties}
        if not set(approval.resolved_uncertainty_ids) <= known or any(u.action == "defer" and u.id not in approval.resolved_uncertainty_ids for u in intent.uncertainties):
            raise AppError("BLOCKING_UNCERTAINTY", "需要在审核或执行前解决的不确定性尚未确认。", 409)
        constraints = intent.constraints
        if (constraints.time_range or constraints.filters or constraints.metric_requirements or constraints.analysis_limits) and not approval.constraints_confirmed:
            raise AppError("UNCONFIRMED_CONSTRAINTS", "分析约束尚未由服务端审核确认，不能执行。", 409)
        saved = approval.validated_plan
        if saved.intent_snapshot is not None and saved.intent_snapshot != intent:
            raise AppError("APPROVAL_INTENT_MISMATCH", "批准意图与计划快照不一致。", 409)
        profile = self.datasets.profile(plan.dataset_id,plan.dataset_version)
        checked = PlanValidator(self.registry).validate(plan,profile)
        if (saved.registry_version != self.registry.version or saved.validation_version != checked.validation_version or
                saved.validation_results != checked.validation_results or saved.executable_task_ids != checked.executable_task_ids or
                saved.blocked_task_ids != checked.blocked_task_ids):
            raise AppError("PLAN_VALIDATION_STALE", "批准计划与当前确定性校验结果不一致，需要重新审核。", 409)
        if not checked.executable_task_ids:
            raise AppError("NO_EXECUTABLE_TASKS", "计划没有当前允许执行的任务。", 422,
                           details={"blocked_task_ids":checked.blocked_task_ids})
        if checked.coverage_status == "blocked":
            raise AppError("COVERAGE_BLOCKED", "核心业务目标覆盖不足，不能执行。", 422)
        if saved.coverage_status != checked.coverage_status or saved.unmet_core_requirements != checked.unmet_core_requirements:
            raise AppError("PLAN_VALIDATION_STALE", "批准的目标覆盖校验已失效。", 409)
        from contextlib import closing
        from app.review.analysis_basis import approved
        with closing(self.sessions.database.connect()) as conn:
            approved(conn,state.id,plan.plan_version,approval.approval_id,plan)
        return checked

    @staticmethod
    def skipped(task_id, code, message, step_id=None):
        return ExecutedTask(task_id=task_id,status="skipped",result=None,effective_row_count=0,valid_sample_count=None,
            sample_definition="未执行，不提供样本量。",scope="批准计划指定的数据集版本",calculation="未执行计算。",
            failure_reason=message,error=ExecutionError(code=code,message=message,task_id=task_id,step_id=step_id))

    @staticmethod
    def outcome(execution_id, request, approval, started_at, tasks, duration_ms, warnings=(), extra_errors=()):
        plan = approval.validated_plan.plan
        successful = sum(t.status == "success" for t in tasks)
        status = "failed" if not successful else ("success" if successful == len(tasks) else "partial_success")
        return ExecutionResultV1(execution_id=execution_id,session_id=request.session_id,
            execution_request_id=request.execution_request_id,approval_id=approval.approval_id,dataset_id=plan.dataset_id,dataset_version=plan.dataset_version,
            plan_id=plan.plan_id,plan_version=plan.plan_version,approved_plan_version=plan.plan_version,
            execution_status=status,source="engine",producer="insightflow-analysis-engine-v1",tasks=tasks,
            started_at=started_at,finished_at=now(),duration_ms=duration_ms,result_view="preview",
            errors=[t.error for t in tasks if t.error]+list(extra_errors),warnings=list(warnings),
            provenance=Provenance(source="uploaded",dataset=plan.dataset_id,dataset_version=plan.dataset_version,
                plan_version=plan.plan_version,notice="从指定版本上传文件读取，复用受控统计内核计算；完整结果与预览分开保存。"))

    def execute(self, request: ExecutionRequest) -> ExecutionResultV1:
        request = ExecutionRequest.model_validate(request.model_dump())
        replay = self.executions.replay(request)
        if replay is not None: return replay
        state = self.sessions.get(request.session_id)
        checked = self.check_approval(state,request)
        plan = checked.plan
        loaded = self.loader.load(plan.dataset_id,plan.dataset_version)
        claim = self.executions.claim(request,state.revision,self.check_approval)
        if isinstance(claim, ExecutionResultV1): return claim
        action = lambda: self._execute_claim(request,checked,loaded,claim)
        observer = getattr(self,'observations',None)
        return observer.execute(claim,action) if observer else action()

    def _execute_claim(self,request,checked,loaded,claim):
        plan = checked.plan
        from contextlib import closing
        from app.review.analysis_basis import approved
        with closing(self.sessions.database.connect()) as conn:
            basis = approved(conn, request.session_id, plan.plan_version, claim['approval'].approval_id, plan)
        timer, tasks = perf_counter(), []
        remaining_bytes, remaining_cells = 256 * 1024, 100_000
        validation = {v.task_id:v for v in checked.validation_results}
        for task in plan.tasks:
            result = validation[task.task_id]
            if not result.executable:
                issue = result.validation_issues[0] if result.validation_issues else None
                output = self.skipped(task.task_id,result.reason_code,
                    issue.message if issue else "该任务不能执行。",issue.step_id if issue else None)
                columns, rows, used = None, None, 0
            else:
                output, columns, rows, used = self.runner.run(task,loaded,remaining_bytes,remaining_cells)
            if output.execution_metadata is not None:
                output.execution_metadata.analysis_basis = ({**{key:basis[key] for key in (
                    'version','digest','plan_id','plan_version','dataset_id','dataset_version','row_grain','entity_field_id','declaration_source')},
                    'metrics':[metric for metric in basis['metrics'] if metric['task_id'] == task.task_id]} if basis else None)
            self.executions.save_task(claim["execution_id"],output,columns,rows)
            tasks.append(output)
            remaining_bytes -= used
            if output.result: remaining_cells -= len(output.result.rows) * len(output.result.columns)
        result = self.outcome(claim["execution_id"],request,claim["approval"],claim["started_at"],tasks,
            (perf_counter()-timer)*1000,warnings=[i.message[:2000] for i in loaded.profile.quality_issues[:20]])
        self.executions.finish(result)
        return result

    def recover_interrupted(self):
        # Existing deployment is explicitly single-process. Never resume/replay calculations automatically.
        for record in self.executions.running():
            request = ExecutionRequest.model_validate_json(record["request"])
            approval = ApprovedExecutionSnapshot.model_validate_json(record["approval"])
            import json
            completed = [ExecutedTask.model_validate(item) for item in json.loads(record["progress"])]
            completed_ids = {task.task_id for task in completed}
            tasks = completed + [self.skipped(task.task_id,"EXECUTION_INTERRUPTED","服务中断，该任务没有已保存的完成结果。")
                                 for task in approval.validated_plan.plan.tasks if task.task_id not in completed_ids]
            elapsed = max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(record["started_at"])).total_seconds()*1000)
            result = self.outcome(record["id"],request,approval,record["started_at"],tasks,elapsed,
                warnings=["服务重启中断执行；保留已保存结果，未自动重跑。"],
                extra_errors=[ExecutionError(code="EXECUTION_INTERRUPTED",message="执行因服务中断结束。")])
            self.executions.finish(result,recovering=True)
