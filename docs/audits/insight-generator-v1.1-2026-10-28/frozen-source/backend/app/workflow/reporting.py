"""Report lifecycle downstream of Engine; never mutates execution or approval state."""
from app.domain.errors import AppError
from app.domain.models import WorkflowError


class ReportWorkflow:
    def __init__(self, sessions, datasets, executions, reports, service):
        self.sessions, self.datasets, self.executions = sessions, datasets, executions
        self.reports, self.service = reports, service

    def enqueue(self, execution_id, expected_attempt=None):
        result = self.executions.get(execution_id)
        if result.source != 'engine' or not result.session_id:
            raise AppError('REPORT_ENGINE_RESULT_REQUIRED', '报告主流程只接受服务端保存的真实计算结果。', 422)
        session = self.sessions.get(result.session_id)
        if session.workflow_kind != 'real_v1':
            raise AppError('REPORT_REAL_WORKFLOW_REQUIRED', '此入口仅用于真实分析会话。', 422)
        return self.reports.queue(execution_id, result.session_id, expected_attempt)

    async def generate(self, execution_id, attempt):
        if self.reports.start(execution_id, attempt) is None:
            return
        try:
            execution = self.executions.complete(execution_id)
            approval = self.executions.approved_snapshot(execution_id)
            session = self.sessions.get(execution.session_id)
            plan = approval.validated_plan.plan
            if (approval.status != 'approved' or approval.approval_id != execution.approval_id or
                    approval.session_id != execution.session_id or
                    (plan.plan_id, plan.plan_version, plan.dataset_id, plan.dataset_version) !=
                    (execution.plan_id, execution.plan_version, execution.dataset_id, execution.dataset_version)):
                raise AppError('REPORT_APPROVAL_MISMATCH', '执行结果与保存的批准快照不一致。', 422)
            profile = self.datasets.profile(execution.dataset_id, execution.dataset_version)
            report = await self.service.generate(approval.intent, approval.validated_plan, execution, profile,
                approved_snapshot=approval, original_query=session.user_goal)
            if report.llm and report.llm.is_mock:
                raise AppError('REPORT_MOCK_LLM_REJECTED', '真实报告不能使用 Mock 洞察，计算结果已保留。', 502)
            from app.reporting.prompt import PROMPT_VERSION
            self.reports.finish(execution_id, attempt, report=report, audit={
                'session_id': execution.session_id, 'execution_id': execution_id,
                'approval_id': approval.approval_id, 'dataset_id': execution.dataset_id,
                'dataset_version': execution.dataset_version, 'plan_id': plan.plan_id,
                'plan_version': plan.plan_version, 'prompt_version': PROMPT_VERSION,
                'schema_version': 'analysis-report-v1', 'original_query': session.user_goal,
                'constraints_confirmed': approval.constraints_confirmed})
        except AppError as exc:
            error = exc.error.model_copy(update={'retryable': True})
            self.reports.finish(execution_id, attempt, error=error)
        except Exception:
            self.reports.finish(execution_id, attempt, error=WorkflowError(
                code='REPORT_GENERATION_FAILED', message='报告生成失败，原始计算结果已保存，可重试。', retryable=True))
