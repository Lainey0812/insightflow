"""Report lifecycle downstream of Engine; never mutates execution or approval state."""
from app.domain.errors import AppError
from app.domain.models import WorkflowError
from app.observability.recorder import TraceRecorder


class ReportWorkflow:
    def __init__(self, sessions, datasets, executions, reports, service, traces=None):
        self.sessions, self.datasets, self.executions = sessions, datasets, executions
        self.reports, self.service = reports, service
        self.traces = traces or TraceRecorder()

    def enqueue(self, execution_id, expected_attempt=None):
        result = self.executions.get(execution_id)
        if result.source != 'engine' or not result.session_id:
            raise AppError('REPORT_ENGINE_RESULT_REQUIRED', '报告主流程只接受服务端保存的真实计算结果。', 422)
        session = self.sessions.get(result.session_id)
        if session.workflow_kind != 'real_v1':
            raise AppError('REPORT_REAL_WORKFLOW_REQUIRED', '此入口仅用于真实分析会话。', 422)
        previous = self.reports.generation(execution_id)
        if expected_attempt is not None and previous and previous.error and not previous.error.retryable:
            raise AppError('REPORT_RETRY_NOT_SUPPORTED', '当前失败需要调整分析范围，重复生成不能解决；计算结果仍可查看。', 409)
        record, fresh = self.reports.queue(execution_id, result.session_id, expected_attempt)
        if fresh:
            self.traces.queue(result, record, lambda: self.executions.approved_snapshot(execution_id), self.service,
                input_reader=lambda: (self.executions.complete(execution_id),
                    self.executions.approved_snapshot(execution_id),
                    self.datasets.profile(result.dataset_id,result.dataset_version),session.user_goal))
        return record, fresh

    async def generate(self, execution_id, attempt):
        generation = self.reports.start(execution_id, attempt)
        if generation is None:
            return
        trace = self.traces.start(execution_id, attempt)
        observer = getattr(self,'observations',None)
        if observer:
            trace = observer.reporting(execution_id,attempt,trace,generation.workflow_binding)
        closed = False
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
            trace.verify_inputs(execution,approval,profile,session.user_goal)
            report = await self.service.generate(approval.intent, approval.validated_plan, execution, profile,
                approved_snapshot=approval, original_query=session.user_goal, trace=trace)
            if report.llm and report.llm.is_mock:
                raise AppError('REPORT_MOCK_LLM_REJECTED', '真实报告不能使用 Mock 洞察，计算结果已保留。', 502)
            from app.reporting.prompt import PROMPT_VERSION
            if getattr(self.service,'prompt_source',None):
                PROMPT_VERSION = self.service.prompt_source.version
            with trace.span('report_persistence') as persistence:
                span_id = persistence.record.span_id if persistence.record else None
                audit = {
                    'session_id': execution.session_id, 'execution_id': execution_id,
                    'approval_id': approval.approval_id, 'dataset_id': execution.dataset_id,
                    'dataset_version': execution.dataset_version, 'plan_id': plan.plan_id,
                    'plan_version': plan.plan_version, 'prompt_version': PROMPT_VERSION,
                    'schema_version': 'analysis-report-v1', 'original_query': session.user_goal,
                    'constraints_confirmed': approval.constraints_confirmed, 'persistence_span_id':span_id}
                try:
                    accepted = self.reports.finish(execution_id,attempt,report=report,audit=audit)
                except Exception:
                    if not self.reports.committed(execution_id,attempt,report.report_id,span_id):
                        raise
                    accepted = True
                if accepted:
                    accepted = self.reports.committed(execution_id,attempt,report.report_id,span_id)
                persistence.attributes(report_id=report.report_id)
                if not accepted:
                    raise AppError('REPORT_STALE_CALLBACK', '报告尝试已被替代，未提交旧报告。', 409)
            from app.observability.snapshots import report_projection
            trace.snapshot('report',report,lambda:report_projection(report))
            trace.finish(report.report_status, report=report)
            closed = True
        except AppError as exc:
            error = exc.error.model_copy(update={'retryable': exc.error.code not in {'REPORT_TOTAL_CAPACITY_EXCEEDED','REPORT_CONTEXT_TOO_LARGE','REPORT_INPUT_TOO_LARGE'}})
            accepted = False if error.code == 'REPORT_STALE_CALLBACK' else self.reports.finish(execution_id, attempt, error=error)
            if accepted:
                trace.finish('failed', error=exc)
            else:
                trace.event('report.callback_ignored', error_code='REPORT_STALE_CALLBACK')
                trace.finish('interrupted', error=AppError('REPORT_STALE_CALLBACK', '旧报告回调未提交。', 409))
            closed = True
        except Exception:
            accepted = self.reports.finish(execution_id, attempt, error=WorkflowError(
                code='REPORT_GENERATION_FAILED', message='报告生成失败，原始计算结果已保存，可重试。', retryable=True))
            if not accepted:
                trace.event('report.callback_ignored', error_code='REPORT_STALE_CALLBACK')
                trace.finish('interrupted', error=AppError('REPORT_STALE_CALLBACK', '旧报告回调未提交。', 409))
                closed = True
        except BaseException as exc:
            trace.finish('interrupted', error=exc)
            closed = True
            raise
        finally:
            if not closed:
                trace.finish('failed', error=AppError('REPORT_GENERATION_FAILED', '报告尝试未正常完成。'))
