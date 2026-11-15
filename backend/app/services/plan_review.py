import json
from typing import Any
from app.observability.hitl import observe_hitl, mark_approval_replay, hitl_validation_role
from pydantic import BaseModel, Field, model_validator

from app.domain.errors import AppError
from app.domain.enums import Operation, SessionStatus as S
from app.domain.models import Message, Plan, SessionState, now, uid
from app.nodes.analysis_planner import make_task
from app.storage.session_repository import SessionRepository
from app.workflow.transitions import transition


class TaskEdit(BaseModel):
    model_config = {"extra": "forbid"}
    task_id: str = Field(min_length=1, max_length=120)
    # Public task identity, priority and core requirement bindings are not editable here.
    step_params: dict[str, dict[str, Any]] = Field(min_length=1, max_length=20)


class RevisionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    expected_revision: int = Field(ge=0)
    plan_version: int = Field(ge=1)
    remove_task_ids: list[str] = Field(default_factory=list)
    instruction: str = Field(default="", max_length=2000)
    plan_id: str | None = None
    task_edits: list[TaskEdit] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_change(self) -> "RevisionRequest":
        if not self.remove_task_ids and not self.instruction.strip() and not self.task_edits:
            raise ValueError("A revision needs a deletion or instruction")
        return self


class ApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}
    expected_revision: int = Field(ge=0)
    plan_version: int = Field(ge=1)
    plan_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    validation_version: str | None = None
    approval_request_id: str | None = Field(default=None, min_length=1, max_length=120)
    acknowledged_warnings: list[str] = Field(default_factory=list, max_length=30)


class PlanReviewService:
    def __init__(self, repository: SessionRepository, datasets=None, registry=None, files=None):
        self.repository = repository
        self.datasets, self.registry, self.files = datasets, registry, files
        from app.storage.plan_review_repository import PlanReviewRepository
        self.audit = PlanReviewRepository(repository.database)

    @staticmethod
    def check_version(state: SessionState, version: int) -> None:
        if state.engine_approval is not None or state.review_plan is not None or state.review_status is not None:
            raise AppError("V1_REVIEW_REQUIRED", "旧 Mock 审核入口不能修改或批准 V1 执行快照。", 409)
        if state.status not in {S.AWAITING_APPROVAL, S.APPROVED}:
            raise AppError("PLAN_NOT_EDITABLE", "当前状态无法审核或修改计划。")
        if state.current_plan_version != version:
            raise AppError("STALE_PLAN", "只能操作当前计划版本。")

    def revise(self, session_id: str, request: RevisionRequest) -> SessionState:
        if self.repository.get(session_id).review_plan is not None:
            return self.revise_v1(session_id, request)
        if request.task_edits:
            raise AppError('REAL_PLAN_NOT_AVAILABLE', '此修改入口仅支持真实分析计划。', 409)
        def change(state: SessionState):
            self.check_version(state, request.plan_version)
            old = state.current_plan
            ids = {task.id for task in old.tasks}
            if not set(request.remove_task_ids) <= ids:
                raise AppError("TASK_NOT_FOUND", "待删除任务不存在。", 422)
            tasks = [task.model_copy(deep=True) for task in old.tasks if task.id not in request.remove_task_ids]
            instruction = request.instruction.strip()
            if instruction:
                supported = [("地区", Operation.REGION), ("趋势", Operation.TREND),
                             ("产品", Operation.CATEGORY), ("概况", Operation.SUMMARY)]
                operations = [op for word, op in supported if word in instruction]
                if not operations or not any(word in instruction for word in ("增加", "添加", "加入", "补充")):
                    raise AppError("MOCK_INSTRUCTION_UNSUPPORTED",
                                   "Mock 修订仅支持「增加地区对比 / 趋势 / 产品贡献 / 销售概况」；删除请使用任务按钮。", 422)
                for operation in operations:
                    if operation not in {task.operation for task in tasks}:
                        tasks.append(make_task(operation))
            if not tasks:
                raise AppError("EMPTY_PLAN", "计划至少需要保留一个任务。", 422)
            if [t.model_dump() for t in tasks] == [t.model_dump() for t in old.tasks]:
                raise AppError("NO_PLAN_CHANGE", "计划已包含这些任务，无需创建新版本。", 422)
            version = old.version + 1
            reason = instruction or f"删除 {len(request.remove_task_ids)} 个任务"
            state.plans.append(Plan(version=version, tasks=tasks, reason=reason))
            state.current_plan_version = version
            state.approved_plan_version = None
            transition(state, S.AWAITING_APPROVAL)
            state.messages.extend([
                Message(role="user", content=reason),
                Message(role="assistant", kind="plan", plan_version=version,
                        content=f"已生成计划 v{version}。请确认后再执行。"),
            ])
        return self.repository.mutate(session_id, change, request.expected_revision)

    def approve(self, session_id: str, request: ApprovalRequest) -> SessionState:
        if self.repository.get(session_id).review_plan is not None:
            return self.approve_v1(session_id, request)
        def change(state: SessionState):
            self.check_version(state, request.plan_version)
            if state.status != S.AWAITING_APPROVAL:
                raise AppError("ALREADY_APPROVED", "该计划已批准，请继续执行。")
            if not state.current_plan.tasks:
                raise AppError("EMPTY_PLAN", "无法批准空计划。", 422)
            state.approved_plan_version = request.plan_version
            transition(state, S.APPROVED)
            state.messages.append(Message(role="user", content=f"确认计划 v{request.plan_version} 并执行分析。"))
        return self.repository.mutate(session_id, change, request.expected_revision)

    @staticmethod
    def revision_guard(state, expected):
        if state.revision != expected:
            raise AppError("STALE_SESSION", "会话已更新，请刷新后重试。", 409)
        if state.status in {S.RUNNING, S.PREPARING}:
            raise AppError("PLAN_NOT_EDITABLE", "执行或准备期间不能修改计划。", 409)

    def validate_v1(self, state, plan, intent):
        from contextlib import nullcontext
        from app.observability.context import current_trace
        from app.planning.validator import PlanValidator
        ref = state.dataset_ref
        if ref is None or state.file.id != plan.dataset_id or (ref.dataset_id, ref.dataset_version) != (plan.dataset_id, plan.dataset_version):
            raise AppError("DATASET_VERSION_MISMATCH", "计划必须使用当前会话上传的数据集及准确版本。", 409)
        trace = current_trace()
        with trace.span('plan_validator', {'validation_role':hitl_validation_role()}) if trace else nullcontext() as validation_span:
            checked = PlanValidator(self.registry).validate(plan, self.datasets.profile(plan.dataset_id, plan.dataset_version))
            if trace:
                from app.observability.recorder import feasibility_counts
                validation_span.attributes(coverage_status=checked.coverage_status, validation_version=checked.validation_version,
                    executable_count=len(checked.executable_task_ids), blocked_count=len(checked.blocked_task_ids),
                    plan_id=checked.plan.plan_id, plan_version=checked.plan.plan_version,
                    **feasibility_counts(checked))
        checked.intent_snapshot = intent
        return checked

    def save_v1(self, session_id, request):
        from app.domain.plan_review import PlanVersion
        with self.audit.transaction(session_id) as (conn, state):
            self.revision_guard(state, request.expected_revision)
            if state.review_status is None:
                raise AppError("REAL_REVIEW_SESSION_REQUIRED", "请使用 manual_review=true 创建真实审核会话；旧 Mock 会话不能升级为真实审批。", 409)
            if state.review_plan is not None or state.engine_approval is not None:
                raise AppError("PLAN_ALREADY_EXISTS", "已有 V1 计划，请在最新版本上修改。", 409)
            if request.plan.plan_version != 1:
                raise AppError("PLAN_VERSION_MISMATCH", "初始 V1 计划版本必须为 1。", 409)
            if request.intent.analysis_goal.business_goal != state.user_goal:
                raise AppError("ANALYSIS_GOAL_MISMATCH", "计划意图必须保留会话的原始业务目标。", 422)
            checked = self.validate_v1(state, request.plan, request.intent)
            record = PlanVersion(session_id=session_id, plan_id=request.plan.plan_id, plan_version=1,
                dataset_id=request.plan.dataset_id, dataset_version=request.plan.dataset_version,
                validation_version=checked.validation_version, created_at=now(), change_type="created",
                change_summary="人工提交结构化计划；经真实 Validator 校验，尚未批准。", validated_plan=checked)
            self.audit.append_version(conn, record)
            state.review_plan = record
            state.current_plan_version = 1
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = "awaiting_review"
            state.status = S.AWAITING_APPROVAL
            state.data_source = "uploaded"
            state.analysis_mode = request.intent.analysis_mode
            state.messages.append(Message(role="assistant", kind="status", content="真实计划 v1 已保存，请审核任务、覆盖情况与限制后确认。"))
        return state

    def current_guard(self, state, request):
        record = state.review_plan
        if record is None:
            raise AppError("REAL_PLAN_NOT_AVAILABLE", "尚未保存真实 V1 计划。", 409)
        history = self.audit.versions(state.id)
        if not history or history[-1] != record:
            raise AppError("PLAN_VERSION_MISMATCH", "只能操作服务端保存的最新版本。", 409)
        if request.plan_id != record.plan_id or request.plan_version != record.plan_version:
            raise AppError("PLAN_VERSION_MISMATCH", "只能操作本会话最新计划 ID 和版本。", 409)
        return record

    @observe_hitl('revise')
    def revise_v1(self, session_id, request):
        from app.domain.plan_review import PlanVersion
        with self.audit.transaction(session_id) as (conn, state):
            self.revision_guard(state, request.expected_revision)
            old = self.current_guard(state, request)
            # Preserve the pre-existing completed-plan deletion API for legacy clients.
            # The new edit form does not reopen executed/completed plans.
            if request.task_edits and state.status not in {S.AWAITING_APPROVAL, S.APPROVED}:
                raise AppError('PLAN_NOT_EDITABLE', '运行中或执行后不能修改方案，请开始新分析。', 409)
            if request.instruction.strip():
                raise AppError("AI_REVISION_NOT_AVAILABLE", "自然语言修订尚未接入 LLM；当前仅支持删除任务并确定性重新校验。", 501)
            plan = old.validated_plan.plan.model_copy(deep=True)
            ids = set(request.remove_task_ids)
            tasks = {t.task_id: t for t in plan.tasks}
            edit_ids = [edit.task_id for edit in request.task_edits]
            if not ids <= tasks.keys() or len(edit_ids) != len(set(edit_ids)) or not set(edit_ids) <= tasks.keys() or ids.intersection(edit_ids):
                raise AppError("TASK_NOT_FOUND", "待删除任务不存在。", 422)
            for edit in request.task_edits:
                steps = {s.step_id: s for s in tasks[edit.task_id].steps}
                if not edit.step_params.keys() <= steps.keys():
                    raise AppError('STEP_NOT_FOUND', '只能修改当前方向已有的步骤。', 422)
                for step_id, params in edit.step_params.items():
                    step = steps[step_id]
                    spec = self.registry.operations.get(step.operation)
                    if spec is None:
                        raise AppError('UNSUPPORTED_OPERATION', '当前不支持修改此分析方法，请重新提出需求。', 422)
                    try:
                        step.params = spec.params_model.model_validate(params).model_dump()
                    except ValueError:
                        raise AppError('INVALID_STEP_PARAMS', '修改内容不符合当前计算规则，请检查字段、数值和统计方式。', 422)
            plan.tasks = [t for t in plan.tasks if t.task_id not in ids]
            if plan == old.validated_plan.plan:
                raise AppError('NO_PLAN_CHANGE', '方案没有变化，无需创建新版本。', 422)
            plan.plan_version += 1
            state.review_status = "validating"
            checked = self.validate_v1(state, plan, old.validated_plan.intent_snapshot)
            record = PlanVersion(session_id=session_id, plan_id=plan.plan_id, plan_version=plan.plan_version,
                dataset_id=plan.dataset_id, dataset_version=plan.dataset_version, validation_version=checked.validation_version,
                created_at=now(), change_type="tasks_edited" if edit_ids else "tasks_deleted",
                change_summary='；'.join(filter(None, ['移除方向：' + '、'.join(tasks[x].title[:80] for x in sorted(ids)) if ids else '',
                    '调整方向：' + '、'.join(tasks[x].title[:80] for x in edit_ids) if edit_ids else ''])) + '；已重新校验，需重新确认。', validated_plan=checked)
            self.audit.append_version(conn, record)
            state.review_plan = record
            state.current_plan_version = plan.plan_version
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = "awaiting_approval"
            state.status = S.AWAITING_APPROVAL
            state.messages.append(Message(role="user", content=record.change_summary))
            state.messages.append(Message(role="assistant", kind="status", content=f"计划 v{plan.plan_version} 已重新校验，目标覆盖：{checked.coverage_status}。"))
        return state

    @staticmethod
    def confirmation_prompts(audit, scope_questions, intent):
        """Questions the user can answer in the dialogue without uploading again."""
        prompts, seen = [], set()

        def add(text):
            text = ' '.join(text.split())
            if text and text not in seen and len(prompts) < 6:
                seen.add(text)
                prompts.append(text[:300])

        for question in scope_questions:
            add(f'「{question["keyword"]}」要包含{question["field_name"]}里的哪些完整名称？直接回复范围，例如只要完全等于这个名称，或写出要保留的名称。')
        asked = {f'intent.constraints.filters[{question["filter_index"]}]' for question in scope_questions}
        for item in audit.items:
            if item.source in asked or item.source.startswith('plan.tasks.') or item.status == 'verified' or not item.raw_text.strip():
                continue
            if item.status in {'unmapped', 'mismatch', 'ambiguous'}:
                add(f'请确认「{item.raw_text.strip()}」。{item.message}')
        if intent:
            for uncertainty in intent.uncertainties:
                if uncertainty.action in {'clarify', 'defer'}:
                    add(f'请确认：{uncertainty.issue}')
        return prompts

    @staticmethod
    def warning_ids(checked):
        warnings = []
        if checked.coverage_status == "partial":
            warnings.append("partial_coverage")
        if checked.blocked_task_ids:
            warnings.append("blocked_tasks")
        if checked.intent_snapshot:
            warnings.extend("uncertainty_" + u.id for u in checked.intent_snapshot.uncertainties if u.action == "annotate")
        return warnings

    def constraint_audit(self, checked):
        from app.review.constraint_audit import ConstraintAuditor
        return ConstraintAuditor(self.datasets.profile(checked.plan.dataset_id, checked.plan.dataset_version)).audit(checked)

    def review_presentation(self, session_id):
        """Read-only, server-authoritative eligibility; approval always rechecks."""
        from types import SimpleNamespace
        from app.domain.review_presentation import ReviewIssue, ScopeQuestion
        from app.review.confirmed_scope import scope_questions as collect_scope_questions
        from app.review.presentation import PlanPresentationMapper
        state = self.repository.get(session_id)
        if state.review_plan is None:
            raise AppError('REAL_PLAN_NOT_AVAILABLE', '分析方案尚未准备完成。', 409)
        record = self.current_guard(state, SimpleNamespace(plan_id=state.review_plan.plan_id, plan_version=state.review_plan.plan_version))
        checked = self.validate_v1(state, record.validated_plan.plan, record.validated_plan.intent_snapshot)
        profile = self.datasets.profile(record.dataset_id, record.dataset_version)
        mapper = PlanPresentationMapper(profile)
        audit = self.constraint_audit(checked)
        issues = []
        from app.reporting.capacity import preflight
        report_capacity = preflight(checked, profile)
        if not report_capacity.supported:
            issues.append(ReviewIssue(code='REPORT_CAPACITY_EXCEEDED', message=report_capacity.message,
                next_step='请重新提出更明确的分析范围；当前计划及核心指标将保留。'))
        if checked != record.validated_plan:
            issues.append(ReviewIssue(code='PLAN_VALIDATION_STALE', message='方案的校验依据发生变化。', next_step='请重新提出需求并生成新方案。'))
        intent = checked.intent_snapshot
        if intent is None or intent.next_action != 'proceed':
            issues.append(ReviewIssue(code='BLOCKING_UNCERTAINTY', message='分析目标仍需要澄清。', next_step='请补充需求后重新生成方案。'))
        if intent:
            for u in intent.uncertainties:
                if u.action in {'clarify', 'defer'}:
                    issues.append(ReviewIssue(code='BLOCKING_UNCERTAINTY', message=mapper.text(u.issue + '；' + u.reason),
                        next_step='请在新需求中明确这一口径；当前不支持在此直接修改或解除。'))
        questions = collect_scope_questions(record, profile, audit.items)
        prompts = self.confirmation_prompts(audit, questions, intent)
        for item in audit.items:
            if item.status != 'verified':
                answered = any(item.source == f'intent.constraints.filters[{q["filter_index"]}]' for q in questions)
                issues.append(ReviewIssue(code='UNVERIFIED_CONSTRAINTS', message=mapper.text(item.raw_text + '：' + item.message),
                    next_step='请在本页预览并确认这个名称对应哪些完整取值。保存后会重新审核，不必回到一开始重写需求。勾选不能跳过确认。'
                    if answered else '请明确字段、范围或口径后重新提出需求；勾选不能解除此问题。'))
        if checked.coverage_status == 'blocked':
            issues.append(ReviewIssue(code='COVERAGE_BLOCKED', message='核心问题目前无法得到回答。', next_step='请补充缺少的数据，或重新提出当前可分析的问题。'))
        for unmet in checked.unmet_core_requirements:
            issues.append(ReviewIssue(code='CORE_NOT_COVERED', message='尚未覆盖：' + mapper.text(unmet.description),
                next_step='请补充数据或重新提出需求。' if checked.coverage_status == 'blocked' else '可在确认下方部分覆盖限制后，仅执行可用方向。'))
        if not checked.executable_task_ids:
            issues.append(ReviewIssue(code='NO_EXECUTABLE_TASKS', message='没有可以开始的分析方向。', next_step='请重新提出需求或上传包含所需字段的数据。'))
        if prompts:
            dialog = '可在下方对话框直接回复。会沿用已上传的文件和原来的目标，生成新的待确认方案，不必重新上传。勾选不能代替回复。'
            issues = [issue.model_copy(update={'next_step': dialog}) if issue.code in {'UNVERIFIED_CONSTRAINTS', 'BLOCKING_UNCERTAINTY'} else issue for issue in issues]
        if not checked.plan.tasks:
            # All constraint failures share this cause. Keep each condition and
            # full audit visible, but do not repeat the same problem a dozen times.
            issues = [ReviewIssue(code='NO_EXECUTABLE_TASKS', message='分析方向已全部移除，当前方案不能开始。',
                next_step='请重新提出需求；历史方案、审批与已有计算结果仍会保留。')]
        # Partial coverage is an existing acknowledged-warning path, not a blocker.
        blocking = [i for i in issues if not (i.code == 'CORE_NOT_COVERED' and checked.coverage_status == 'partial')]
        warnings = []
        for wid in self.warning_ids(checked):
            if wid == 'partial_coverage':
                label = '我了解本方案只能回答部分核心问题。'
            elif wid == 'blocked_tasks':
                label = '我了解暂时无法分析的方向将保留，但不会参与计算。'
            else:
                u = next(u for u in intent.uncertainties if 'uncertainty_' + u.id == wid)
                label = mapper.text(u.issue + '；影响：' + u.reason)
            warnings.append({'id': wid, 'label': label})
        view = mapper.build(state, audit, issues, warnings)
        from contextlib import closing
        from app.review.analysis_basis import load
        with closing(self.repository.database.connect()) as conn:
            view.analysis_basis = load(conn,session_id,record.plan_version)
        view.report_capacity = report_capacity
        view.scope_questions = [ScopeQuestion(**item) for item in questions]
        view.confirmation_questions = prompts
        view.can_approve = not blocking and state.status == S.AWAITING_APPROVAL
        active = state.engine_approval
        recorded = next((a for a in self.audit.approvals(state.id) if active and a.approval_id == active.approval_id), None)
        view.can_execute = bool(not blocking and state.status == S.APPROVED and state.approved_plan_version == record.plan_version
            and active and recorded and recorded.snapshot == active and active.validated_plan == record.validated_plan)
        return view

    @observe_hitl('approve')
    def approve_v1(self, session_id, request):
        from app.domain.execution import ApprovedExecutionSnapshot
        from app.domain.plan_review import ReviewApproval
        with self.audit.transaction(session_id) as (conn, state):
            record = self.current_guard(state, request)
            if not request.approval_request_id:
                raise AppError("APPROVAL_REQUEST_ID_REQUIRED", "确认操作需要唯一请求 ID；重试必须复用此 ID。", 422)
            previous = conn.execute("SELECT request, record FROM plan_approvals WHERE session_id=? AND request_id=?",
                                    (session_id, request.approval_request_id)).fetchone()
            if previous:
                if previous["request"] != request.model_dump_json():
                    raise AppError("APPROVAL_REQUEST_CONFLICT", "审批请求 ID 已用于不同参数。", 409)
                if state.engine_approval is None or state.engine_approval.approval_id != json.loads(previous["record"])["approval_id"]:
                    raise AppError("APPROVAL_SUPERSEDED", "原审批已不再是当前有效审批。", 409)
                mark_approval_replay()
                return state
            self.revision_guard(state, request.expected_revision)
            if state.approved_plan_version == record.plan_version:
                raise AppError("ALREADY_APPROVED", "当前版本已批准；请继续执行。", 409)
            if (request.dataset_id, request.dataset_version) != (record.dataset_id, record.dataset_version):
                raise AppError("DATASET_VERSION_MISMATCH", "确认的数据集版本与当前计划不一致。", 409)
            checked = self.validate_v1(state, record.validated_plan.plan, record.validated_plan.intent_snapshot)
            saved = record.validated_plan
            if request.validation_version != saved.validation_version or checked.model_dump() != saved.model_dump():
                raise AppError("PLAN_VALIDATION_STALE", "计划校验已失效，需要重新校验和审核。", 409)
            intent = checked.intent_snapshot
            if intent.next_action != "proceed" or any(u.action in {"clarify", "defer"} for u in intent.uncertainties):
                raise AppError("BLOCKING_UNCERTAINTY", "仍有待澄清或待解决的不确定性，不能以确认替代解决。", 409)
            from app.reporting.capacity import preflight
            capacity = preflight(checked, self.datasets.profile(record.dataset_id, record.dataset_version))
            if not capacity.supported:
                raise AppError('REPORT_CAPACITY_EXCEEDED', capacity.message, 422,
                               details={'report_capacity': capacity.model_dump()})
            constraints = intent.constraints
            constraint_audit = self.constraint_audit(checked)
            if not constraint_audit.all_verified:
                raise AppError("UNVERIFIED_CONSTRAINTS", "分析条件未能与当前步骤完整对应，请明确范围或口径后重新提出需求。", 409,
                    details={'unverified': [item.model_dump(mode='json') for item in constraint_audit.items if item.status != 'verified']})
            if checked.coverage_status == "blocked":
                raise AppError("COVERAGE_BLOCKED", "核心业务目标覆盖不足，不能批准。", 422)
            if not checked.executable_task_ids:
                raise AppError("NO_EXECUTABLE_TASKS", "至少需要一个可执行任务。", 422)
            required = self.warning_ids(checked)
            if set(request.acknowledged_warnings) != set(required):
                raise AppError("WARNINGS_NOT_ACKNOWLEDGED", "请明确确认当前计划全部重要限制。", 422, details={"required_warnings": required})
            snapshot = ApprovedExecutionSnapshot(approval_id="approval_" + uid(), approved_at=now(),
                session_id=session_id, validated_plan=checked, intent=intent, acknowledged_warnings=required,
                constraints_confirmed=bool(constraints.time_range or constraints.filters or constraints.metric_requirements or constraints.analysis_limits) and constraint_audit.all_verified)
            approval = ReviewApproval(approval_id=snapshot.approval_id, approval_request_id=request.approval_request_id,
                session_id=session_id, plan_id=record.plan_id, plan_version=record.plan_version,
                validation_version=record.validation_version, dataset_id=record.dataset_id, dataset_version=record.dataset_version,
                approved_at=snapshot.approved_at, acknowledged_warnings=required, snapshot=snapshot)
            conn.execute("INSERT INTO plan_approvals VALUES (?, ?, ?, ?, ?)",
                (approval.approval_id, session_id, request.approval_request_id, request.model_dump_json(), approval.model_dump_json()))
            conn.execute('INSERT INTO plan_constraint_audits VALUES (?, ?, ?)',
                (approval.approval_id, session_id, json.dumps({'approval_id': approval.approval_id, 'session_id': session_id,
                    'approved_at': snapshot.approved_at, 'audit': constraint_audit.model_dump(mode='json')}, ensure_ascii=False)))
            from app.review.analysis_basis import bind_approval as bind_basis
            bind_basis(conn, approval)
            from app.storage.workflow_bindings import bind_approval
            bind_approval(conn, state, approval, request)
            state.engine_approval = snapshot
            state.approved_plan_version = record.plan_version
            state.status = S.APPROVED
            state.review_status = "approved"
            state.messages.append(Message(role="user", content=f"确认真实计划 v{record.plan_version} 并执行；已确认限制：{', '.join(required) or '无'}。"))
        return state

    @observe_hitl('revise')
    def update_analysis_basis(self, session_id, request):
        from app.domain.plan_review import PlanVersion
        from app.review.analysis_basis import register
        with self.audit.transaction(session_id) as (conn,state):
            self.revision_guard(state, request.expected_revision)
            old = self.current_guard(state,request)
            if state.status not in {S.AWAITING_APPROVAL,S.APPROVED}:
                raise AppError('PLAN_NOT_EDITABLE','执行后不能修改当前计划口径，请开始新分析。',409)
            plan = old.validated_plan.plan.model_copy(deep=True)
            plan.plan_version += 1
            checked = self.validate_v1(state,plan,old.validated_plan.intent_snapshot)
            record = PlanVersion(session_id=session_id,plan_id=plan.plan_id,plan_version=plan.plan_version,
                dataset_id=plan.dataset_id,dataset_version=plan.dataset_version,validation_version=checked.validation_version,
                created_at=now(),change_type='basis_updated',change_summary='更新记录粒度声明；计算字段和函数保持不变，需重新审批。',validated_plan=checked)
            # The plan and declared basis commit in the same existing transaction.
            conn.execute('INSERT INTO plan_versions VALUES (?,?,?,?)',(session_id,plan.plan_id,plan.plan_version,record.model_dump_json()))
            register(conn,record,request.model_dump(include={'row_grain','entity_field_id'}))
            state.review_plan = record
            state.current_plan_version = plan.plan_version
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = 'awaiting_approval'
            state.status = S.AWAITING_APPROVAL
            state.messages.append(Message(role='user',content=record.change_summary))
        return state


    def scope_preview(self, session_id, request):
        from app.review.confirmed_scope import preview
        state = self.repository.get(session_id)
        self.revision_guard(state, request.expected_revision)
        record = self.current_guard(state, request)
        if state.status not in {S.AWAITING_APPROVAL, S.APPROVED}:
            raise AppError('PLAN_NOT_EDITABLE', '当前状态不能修改分析范围。', 409)
        return preview(record, request, self.datasets, self.files)

    @observe_hitl('revise')
    def confirm_scope(self, session_id, request):
        from app.review.confirmed_scope import preview, check_target, encode, ConfirmedScope
        from app.domain.plan_review import PlanVersion
        from app.domain.intent import UnverifiedConstraint
        with self.audit.transaction(session_id) as (conn, state):
            self.revision_guard(state, request.expected_revision)
            old = self.current_guard(state, request)
            if state.status not in {S.AWAITING_APPROVAL, S.APPROVED}:
                raise AppError('PLAN_NOT_EDITABLE', '执行期间或执行后不能改变分析范围。', 409)
            proof = preview(old, request, self.datasets, self.files)
            if proof['preview_digest'] != request.preview_digest:
                raise AppError('SCOPE_PREVIEW_STALE', '范围预览已失效，请重新核对当前版本。', 409)
            scope = ConfirmedScope.model_validate(proof['scope'])
            targets = check_target(old, request)
            plan = old.validated_plan.plan.model_copy(deep=True)
            for tid, sid, index in targets:
                task = next(t for t in plan.tasks if t.task_id == tid)
                step = next(s for s in task.steps if s.step_id == sid)
                step.params['conditions'][index] = {'field':scope.field_id,'operator':'in','value':scope.values}
            intent = old.validated_plan.intent_snapshot.model_copy(deep=True)
            intent.constraints.filters[request.filter_index] = UnverifiedConstraint(raw_text=encode(scope), validation_status='unverified')
            plan.plan_version += 1
            checked = self.validate_v1(state, plan, intent)
            summary = proof['summary'] + f"；匹配 {proof['matched_row_count']} / {proof['dataset_row_count']} 条上传记录；需重新审核。"
            record = PlanVersion(session_id=session_id,plan_id=plan.plan_id,plan_version=plan.plan_version,
                dataset_id=plan.dataset_id,dataset_version=plan.dataset_version,validation_version=checked.validation_version,
                created_at=now(),change_type='scope_confirmed',change_summary=summary,validated_plan=checked)
            self.audit.append_version(conn,record)
            state.review_plan = record
            state.current_plan_version = plan.plan_version
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = 'awaiting_approval'
            state.status = S.AWAITING_APPROVAL
            state.messages.append(Message(role='user', content='确认筛选范围：' + summary))
            state.messages.append(Message(role='assistant',kind='status',content=f'已生成范围确认后的方案 v{plan.plan_version}，请重新核对分析方向；尚未执行。'))
        return state
