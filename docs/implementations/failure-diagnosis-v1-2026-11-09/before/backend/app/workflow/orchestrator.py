from typing import Any

from app.domain.errors import AppError
from app.domain.enums import SessionStatus as S
from app.domain.models import Message, NodeRun, SessionState, WorkflowError, now
from app.domain.dataset_profile import DatasetProfile, DatasetRef, ProfileOptions
from app.domain.node_contracts import NodeInput, NodeOutput
from app.nodes.analysis_engine import MockAnalysisEngine
from app.nodes.analysis_planner import MockAnalysisPlanner, PlannerInput
from app.nodes.data_profiler import DataProfilerNode, ProfileInput
from app.nodes.intent_parser import IntentInput, IntentParserNode
from app.nodes.report_module import MockReportModule
from app.nodes.planner_v1 import AnalysisPlannerNode, PlannerV1Input
from app.domain.plan_review import PlanVersion
from app.services.plan_review import ApprovalRequest
from app.services.data_profiler import DataProfilerService
from app.services.intent_parser import IntentParserService
from app.storage.session_repository import SessionRepository
from .transitions import transition
from app.observability.recorder import TraceRecorder
from app.observability.context import bind_trace
from app.observability.workflow import register_root, preparation_context, start_preparation, checkpoint, interrupt


class NodeFailure(Exception):
    def __init__(self, error: WorkflowError):
        self.error = error


class WorkflowOrchestrator:
    def __init__(self, repository: SessionRepository, parser: IntentParserService, profiler: DataProfilerService,
                 real_planner=None, review=None, traces=None, identities=None):
        self.identities = identities
        self.repository = repository
        self.datasets = profiler.datasets
        self.intent_parser = IntentParserNode(parser)
        self.data_profiler = DataProfilerNode(profiler)
        self.planner = MockAnalysisPlanner()
        self.engine = MockAnalysisEngine()
        self.reporter = MockReportModule()
        self.real_planner = AnalysisPlannerNode(real_planner) if real_planner else None
        self.review = review
        self.traces = traces or TraceRecorder()

    def create_real_session(self, state):
        if self.identities:
            return self.identities.create(state, 'prepare:' + state.id)
        self.repository.create(state)
        return state

    def identity(self, state):
        if self.identities:
            if state.workflow_id or state.root_run_id:
                return self.identities.resolve(state)
            self.identities.require_unregistered(state.id)
        return None

    def trace_created(self, state):
        identity = self.identity(state)
        # Historical Sessions are not backfilled or assigned a guessed Root.
        if self.identities and identity is None:
            return None
        return register_root(self.traces, state, self.intent_parser.parser,
                      self.real_planner.planner if self.real_planner else None, identity)

    async def observed_node(self, trace, name, node, request, guard=None):
        with trace.span(name, {'node_name': node.name}) as span:
            data = self.real_output(await node.run(request), guard)
            if name == 'intent_parser':
                span.attributes(next_action=data.next_action)
            elif name == 'analysis_planner':
                span.attributes(coverage_status=data.coverage_status,
                                executable_count=len(data.executable_task_ids), blocked_count=len(data.blocked_task_ids))
            elif name == 'data_profiler':
                span.attributes(dataset_id=data.dataset_id, dataset_version=data.dataset_version,
                                row_count=data.row_count, column_count=data.column_count)
            return data

    def record(self, output: NodeOutput[Any], guard=None) -> Any:
        def change(state: SessionState):
            state.node_runs.append(NodeRun(run_id=output.run_id, node_name=output.node_name,
                                           status=output.status, provenance=output.provenance,
                                           error=output.error))
        state = self.repository.mutate(output.session_id, change, guard['revision'] if guard is not None else None)
        if guard is not None:
            guard['revision'] = state.revision
        if output.status == "error":
            raise NodeFailure(output.error)
        return output.data

    def fail(self, session_id: str, error: WorkflowError) -> SessionState:
        def change(state: SessionState):
            transition(state, S.FAILED)
            state.error = error
            state.messages.append(Message(role="assistant", kind="error", content=error.message))
        return self.repository.mutate(session_id, change)

    async def prepare(self, session_id: str, profile_options: ProfileOptions | None = None, manual_review: bool = False,
                      real_workflow: bool = False, identity=None) -> SessionState:
        if real_workflow:
            return await self.prepare_real(session_id, identity)
        def start(state: SessionState):
            transition(state, S.PREPARING)
            state.messages.append(Message(role="assistant", kind="status",
                content="正在计算真实数据画像，再根据字段上下文理解分析需求。"))
        state = self.repository.mutate(session_id, start)
        try:
            profile = self.record(await self.data_profiler.run(NodeInput(session_id=session_id,
                payload=ProfileInput(file=state.file, options=profile_options or ProfileOptions()))))

            def save_profile(current: SessionState):
                current.profile = profile
                current.dataset_ref = DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version)
                current.messages.append(Message(role="assistant", kind="status",
                    content=f"真实数据画像完成：表头第 {profile.options.header_row} 行，{profile.row_count} 行数据、{profile.column_count} 列，"
                            f"发现 {len(profile.quality_issues)} 项质量提示。" + ("请提交真实结构化计划进行审核。" if manual_review else "后续计划与报告仍为 Mock 示例。")))
            self.repository.mutate(session_id, save_profile)
            if manual_review:
                def await_plan(current):
                    current.status = S.AWAITING_APPROVAL
                    current.review_status = "awaiting_review"
                    current.data_source = "uploaded"
                    current.messages.append(Message(role="assistant", kind="status",
                        content="真实画像已就绪。请提交结构化 AnalysisPlan 和原始目标对应的意图；本入口不调用 LLM 或 Mock Planner。"))
                return self.repository.mutate(session_id, await_plan)
            return await self._interpret_and_plan(session_id, profile)
        except NodeFailure as exc:
            return self.fail(session_id, exc.error)

    async def _interpret_and_plan(self, session_id: str, profile: DatasetProfile) -> SessionState:
        state = self.repository.get(session_id)
        intent = self.record(await self.intent_parser.run(NodeInput(session_id=session_id,
            payload=IntentInput(user_query=state.user_goal, profile=profile,
                                clarification_answers=state.clarification_answers))))

        def save_intent(current: SessionState):
            current.intent = intent
            current.intent_history.append(intent)
            current.analysis_mode = intent.analysis_mode
            if intent.next_action == "clarify":
                transition(current, S.WAITING_FOR_CLARIFICATION)
                questions = "\n".join(f"{i}. {q}" for i, q in enumerate(intent.clarification_questions, 1))
                current.messages.append(Message(role="assistant", content="需要先确认以下信息：\n" + questions))
        state = self.repository.mutate(session_id, save_intent)
        if intent.next_action == "clarify":
            return state
        plan = self.record(await self.planner.run(NodeInput(session_id=session_id,
            payload=PlannerInput(intent=intent, profile=profile))))

        def ready(current: SessionState):
            current.plans.append(plan)
            current.current_plan_version = plan.version
            transition(current, S.AWAITING_APPROVAL)
            current.messages.append(Message(role="assistant", kind="plan", plan_version=plan.version,
                content="分析意图已确认，下面是 Mock 计划。你可以删除任务或要求修改，确认后再执行示例分析。"))
        return self.repository.mutate(session_id, ready)

    async def clarify(self, session_id: str, answer: str, expected_revision: int) -> SessionState:
        state = self.repository.get(session_id)
        if state.status != S.WAITING_FOR_CLARIFICATION or state.dataset_ref is None:
            raise AppError("CLARIFICATION_NOT_ALLOWED", "当前会话不在等待澄清状态。")
        ref = state.dataset_ref
        profile = self.datasets.profile(ref.dataset_id, ref.dataset_version)

        def resume(current: SessionState):
            if current.status != S.WAITING_FOR_CLARIFICATION:
                raise AppError("CLARIFICATION_NOT_ALLOWED", "当前会话不在等待澄清状态。")
            transition(current, S.PREPARING)
            current.clarification_answers.append(answer)
            current.messages.append(Message(role="user", content=answer))
        self.repository.mutate(session_id, resume, expected_revision)
        try:
            return await self._interpret_and_plan(session_id, profile)
        except NodeFailure as exc:
            return self.fail(session_id, exc.error)

    async def execute(self, session_id: str, request: ApprovalRequest) -> SessionState:
        def claim(state: SessionState):
            if state.engine_approval is not None or state.review_plan is not None or state.review_status is not None:
                raise AppError("V1_EXECUTION_ENDPOINT_REQUIRED", "V1 计划必须通过真实执行入口执行。", 409)
            if (state.status != S.APPROVED or request.plan_version != state.current_plan_version
                    or request.plan_version != state.approved_plan_version):
                raise AppError("APPROVAL_REQUIRED", "必须先批准当前计划版本，且每个会话只能执行一次。")
            transition(state, S.RUNNING)
            state.messages.append(Message(role="assistant", kind="status",
                                          content="计划已确认，正在执行固定示例计算并生成报告。"))
        state = self.repository.mutate(session_id, claim, request.expected_revision)
        try:
            result = self.record(await self.engine.run(NodeInput(session_id=session_id, payload=state.current_plan)))

            def save_result(current: SessionState):
                current.execution_result = result
            self.repository.mutate(session_id, save_result)
            report = self.record(await self.reporter.run(NodeInput(session_id=session_id, payload=result)))

            def complete(current: SessionState):
                current.report = report
                transition(current, S.COMPLETED)
                current.messages.append(Message(role="assistant", kind="report",
                    content="示例分析已完成。报告包含图表、结论和对应的数据依据，可直接预览或下载。"))
            return self.repository.mutate(session_id, complete)
        except NodeFailure as exc:
            return self.fail(session_id, exc.error)

    def recover_interrupted(self) -> None:
        # Single-process local deployment. HITL sessions remain resumable after restart.
        for item in self.repository.list():
            if (item["status"] in {S.PROFILING, S.PARSING_INTENT, S.PLANNING, S.VALIDATING} or
                    item["status"] == S.CREATED and self.repository.get(item["id"]).workflow_kind == "real_v1"):
                self.fail_real(item["id"], WorkflowError(code="PROCESS_INTERRUPTED", retryable=True,
                    message="服务重启中断了准备阶段，已有检查点已保存；请点击重试准备，不会自动执行。"))
            elif item["status"] in {S.PREPARING, S.RUNNING}:
                self.fail(item["id"], WorkflowError(code="PROCESS_INTERRUPTED",
                    message="上次处理因服务重启中断，请新建会话重新提交。"))

    def real_output(self, output, guard=None):
        """A scripted/Mock service can never silently enter the real workflow."""
        if output.status == "success":
            llm = getattr(output.data, "llm", None)
            if output.provenance.source == "mock" or (llm is not None and llm.is_mock):
                raise NodeFailure(WorkflowError(code="MOCK_SOURCE_FORBIDDEN", node_name=output.node_name,
                    message="真实流程拒绝Mock节点输出，未生成批准或执行结果。"))
        return self.record(output, guard)

    def fail_real(self, session_id, error, guard=None):
        state = self.repository.get(session_id)
        safe = error.model_copy(deep=True)
        safe.details = {**safe.details, "workflow_stage": state.status.value}
        safe.retryable = safe.retryable or state.status in {S.PARSING_INTENT, S.PLANNING, S.VALIDATING}
        if guard is None:
            return self.fail(session_id, safe)
        def fail_current(current):
            transition(current, S.FAILED)
            current.error = safe
            current.messages.append(Message(role='assistant', kind='error', content=safe.message))
        return self.preparation_mutate(session_id, fail_current, guard)

    def preparation_mutate(self, session_id, change, guard):
        # Reuse the business revision as an optimistic callback fence. This is
        # local dispatch state, not a persisted Attempt or a new Trace layer.
        state = self.repository.mutate(session_id, change, guard['revision'])
        guard['revision'] = state.revision
        return state

    async def prepare_real(self, session_id, identity=None):
        state = self.repository.get(session_id)
        registered = self.identity(state)
        if identity is not None and identity != registered:
            raise AppError('WORKFLOW_IDENTITY_MISMATCH', '准备任务身份与业务登记不一致。', 409)
        identity = registered
        if identity:
            self.trace_created(state)  # Idempotent repair of a missing physical Root/link.
        guard = {'revision': self.repository.get(session_id).revision}
        trace = preparation_context(self.traces, session_id, identity, explicit_only=self.identities is not None)
        with bind_trace(trace):
            start_preparation(trace, guard['revision'])
            try:
                result = await self._prepare_real(session_id, trace, guard)
                checkpoint(trace, result)
                return result
            except AppError as error:
                if error.error.code == 'STALE_SESSION':
                    trace.event('workflow.callback_ignored', error_code='STALE_SESSION', session_revision=guard['revision'])
                    return self.repository.get(session_id)
                interrupt(trace, error)
                raise
            except BaseException as error:
                if self.repository.get(session_id).revision == guard['revision']:
                    interrupt(trace, error)
                else:
                    trace.event('workflow.callback_ignored', error_code='STALE_SESSION', session_revision=guard['revision'])
                raise

    async def _prepare_real(self, session_id, trace, guard):
        """Checkpointed real branch; approval/execution remain the existing services."""
        try:
            state = self.repository.get(session_id)
            if state.revision != guard['revision']:
                raise AppError('STALE_SESSION', '准备回调已过期，当前流程未修改。', 409)
            if state.workflow_kind != "real_v1":
                raise AppError("REAL_WORKFLOW_REQUIRED", "当前会话不属于真实Workflow。", 409)
            if state.status == S.CREATED:
                def start(current):
                    if current.status != S.CREATED:
                        raise AppError("WORKFLOW_ALREADY_STARTED", "该流程已经启动。", 409)
                    transition(current, S.PROFILING)
                    current.messages.append(Message(role="assistant", kind="status", content="正在解析上传文件并计算真实数据画像。"))
                state = self.preparation_mutate(session_id, start, guard)
            if state.status == S.PROFILING:
                profile = await self.observed_node(trace, 'data_profiler', self.data_profiler, NodeInput(session_id=session_id,
                    payload=ProfileInput(file=state.file, options=state.profile_options)), guard)
                def profiled(current):
                    current.profile = profile
                    current.dataset_ref = DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version)
                    transition(current, S.PARSING_INTENT)
                    current.messages.append(Message(role="assistant", kind="status", content=
                        f"真实画像完成：{profile.row_count}行、{profile.column_count}列；正在理解分析需求。"))
                state = self.preparation_mutate(session_id, profiled, guard)
            if state.status == S.PARSING_INTENT:
                ref = state.dataset_ref
                profile = self.datasets.profile(ref.dataset_id, ref.dataset_version)
                intent = await self.observed_node(trace, 'intent_parser', self.intent_parser, NodeInput(session_id=session_id,
                    payload=IntentInput(user_query=state.user_goal, profile=profile,
                                        clarification_answers=state.clarification_answers)), guard)
                if intent.next_action == "proceed" and (intent.llm is None or intent.parse_origin != "llm"):
                    raise AppError("REAL_INTENT_REQUIRED", "继续分析必须具备真实模型意图结果。", 409)
                def interpreted(current):
                    current.intent = intent
                    current.intent_history.append(intent)
                    current.analysis_mode = intent.analysis_mode
                    if intent.next_action == "clarify":
                        transition(current, S.WAITING_FOR_CLARIFICATION)
                        current.messages.append(Message(role="assistant", content="需要先补充以下信息：\n" +
                            "\n".join(intent.clarification_questions)))
                    else:
                        transition(current, S.PLANNING)
                        current.messages.append(Message(role="assistant", kind="status", content="需求已理解，正在生成受控分析计划。"))
                state = self.preparation_mutate(session_id, interpreted, guard)
            if state.status == S.WAITING_FOR_CLARIFICATION:
                return state
            if state.status == S.PLANNING:
                if self.real_planner is None:
                    raise AppError("PLANNER_NOT_AVAILABLE", "真实Planner尚未配置。", 503)
                ref = state.dataset_ref
                candidate = await self.observed_node(trace, 'analysis_planner', self.real_planner, NodeInput(session_id=session_id,
                    payload=PlannerV1Input(intent=state.intent, profile=self.datasets.profile(ref.dataset_id, ref.dataset_version))), guard)
                if candidate.llm is None or candidate.llm.is_mock:
                    raise AppError("REAL_PLANNER_REQUIRED", "真实流程必须使用真实模型计划。", 409)
                def planned(current):
                    current.planner_result = candidate
                    transition(current, S.VALIDATING)
                state = self.preparation_mutate(session_id, planned, guard)
            if state.status == S.VALIDATING:
                return self.save_generated_plan(session_id, guard)
            return state
        except NodeFailure as exc:
            return self.fail_real(session_id, exc.error, guard)
        except AppError as exc:
            if exc.error.code == 'STALE_SESSION':
                raise
            return self.fail_real(session_id, exc.error, guard)
        except Exception:
            return self.fail_real(session_id, WorkflowError(code="WORKFLOW_PREPARATION_FAILED",
                message="真实流程准备失败，已保存可用检查点，未使用示例结果替代。"), guard)

    def save_generated_plan(self, session_id, guard=None):
        # This adapter saves generated drafts; it does not change manual-import
        # goal matching, validation, approval or execution rules.
        with self.review.audit.transaction(session_id) as (conn, state):
            if guard is not None:
                self.review.revision_guard(state, guard['revision'])
            if state.workflow_kind != "real_v1" or state.status != S.VALIDATING or state.review_plan is not None:
                raise AppError("GENERATED_PLAN_STATE_INVALID", "当前状态不能保存生成计划。", 409)
            candidate = state.planner_result
            if candidate is None or candidate.llm is None or candidate.llm.is_mock:
                raise AppError("REAL_PLANNER_REQUIRED", "缺少真实模型计划检查点。", 409)
            checked = self.review.validate_v1(state, candidate.plan, candidate.intent_snapshot)
            record = PlanVersion(session_id=session_id, plan_id=checked.plan.plan_id, plan_version=1,
                dataset_id=checked.plan.dataset_id, dataset_version=checked.plan.dataset_version,
                validation_version=checked.validation_version, created_at=now(), change_type="created",
                change_summary="真实LLM生成计划；现有Validator重新校验，等待人工批准。", validated_plan=checked)
            self.review.audit.append_version(conn, record)
            state.review_plan = record
            state.current_plan_version = 1
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = "awaiting_review"
            transition(state, S.AWAITING_APPROVAL)
            state.messages.append(Message(role="assistant", kind="plan", plan_version=1,
                content=f"真实计划已保存，目标覆盖：{checked.coverage_status}。请审核任务、未满足需求和约束；批准前不会计算。"))
        if guard is not None:
            guard['revision'] = state.revision
        return state

    def begin_real_clarification(self, session_id, answer, expected_revision):
        def resume(state):
            if state.workflow_kind != "real_v1" or state.status != S.WAITING_FOR_CLARIFICATION:
                raise AppError("CLARIFICATION_NOT_ALLOWED", "当前真实会话不在等待澄清。", 409)
            state.clarification_answers.append(answer)
            state.planner_result = None
            state.error = None
            state.messages.append(Message(role="user", content=answer))
            transition(state, S.PARSING_INTENT)
        return self.repository.mutate(session_id, resume, expected_revision)

    def begin_real_retry(self, session_id, expected_revision):
        def resume(state):
            if (state.workflow_kind != "real_v1" or state.status != S.FAILED or not state.error
                    or not state.error.retryable or state.review_plan is not None or state.engine_execution_ids):
                raise AppError("PREPARATION_RETRY_NOT_ALLOWED", "只能显式重试尚未批准、未执行的准备阶段失败。", 409)
            if state.planner_result is not None:
                target = S.VALIDATING
            elif state.intent is not None and state.intent.next_action == "proceed" and state.intent.clarification_answers == state.clarification_answers:
                target = S.PLANNING
            else:
                target = S.PARSING_INTENT if state.dataset_ref else S.PROFILING
            transition(state, target)
            state.error = None
            state.messages.append(Message(role="assistant", kind="status", content="按已保存检查点重试准备；不会自动批准或执行。"))
        return self.repository.mutate(session_id, resume, expected_revision)
