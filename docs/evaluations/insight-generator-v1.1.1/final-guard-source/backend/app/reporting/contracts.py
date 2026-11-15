import json
from dataclasses import dataclass

from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.execution import ExecutionResultV1
from app.domain.intent import IntentArtifact, ParsedIntent
from app.planning.capabilities import CapabilityRegistry, FieldState
from app.planning.params import AggregateParams, DeriveParams, GroupParams
from app.planning.validator import PlanValidator
from app.planning.operations import temporal


@dataclass
class ResultDescription:
    metrics: dict
    dimensions: list[str]
    temporal_dimensions: set[str]
    scope_key: str
    complete_partition: bool


def prepare(intent: ParsedIntent, validated: ValidatedAnalysisPlan, execution: ExecutionResultV1,
            profile: DatasetProfile, registry: CapabilityRegistry):
    def reject(message):
        raise AppError("REPORT_INPUT_MISMATCH", message, 422)
    if execution.source == "mock":
        raise AppError("MOCK_EXECUTION_NOT_REPORTABLE", "旧 Mock 结果不能作为 V1 真实报告的输入。", 422)
    plan = validated.plan
    ref = (profile.dataset_id, profile.dataset_version)
    if (execution.dataset_id, execution.dataset_version) != ref or (plan.dataset_id, plan.dataset_version) != ref:
        reject("计划、执行结果与画像必须关联同一数据集版本。")
    if isinstance(intent, IntentArtifact) and (intent.dataset_ref.dataset_id, intent.dataset_ref.dataset_version) != ref:
        reject("意图与数据集版本不一致。")
    if intent.next_action != "proceed":
        reject("分析需求仍待澄清，不能生成报告。")
    if execution.plan_id != plan.plan_id or execution.plan_version != plan.plan_version or execution.approved_plan_version != plan.plan_version:
        reject("执行结果必须来自同一已批准计划版本。")
    checked = PlanValidator(registry).validate(plan, profile)
    if checked.validation_results != validated.validation_results or checked.executable_task_ids != validated.executable_task_ids:
        reject("计划的执行资格与确定性重验结果不一致。")
    if validated.intent_snapshot is not None and validated.intent_snapshot != ParsedIntent.model_validate(
            {name: getattr(intent, name) for name in ParsedIntent.model_fields}):
        reject("报告意图与规划时的意图快照不一致。")
    tasks = {task.task_id: task for task in plan.tasks}
    if set(tasks) != {task.task_id for task in execution.tasks}:
        reject("每个计划任务都需明确的成功、失败或跳过状态。")
    descriptions = {}
    for executed in execution.tasks:
        if executed.effective_row_count > profile.row_count:
            reject("任务有效行数超过数据集行数。")
        if executed.status != "success":
            continue
        if executed.task_id not in checked.executable_task_ids:
            reject("不可执行任务不能提交成功结果。")
        task = tasks[executed.task_id]
        fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in profile.fields}
        reserved, metrics, dimensions, temporal_dims = set(fields), {}, [], set()
        prefix, scope_key, complete_partition = [], "", False
        for step in task.steps:
            spec = registry.operations[step.operation]
            params = spec.params_model.model_validate(step.params)
            if isinstance(params, DeriveParams):
                temporal_dims.add(params.alias)
            if isinstance(params, AggregateParams):
                metrics = {m.alias: m for m in params.metrics}
                dimensions = params.dimensions if isinstance(params, GroupParams) else []
                scope_key = json.dumps(prefix, sort_keys=True, ensure_ascii=False)
                complete_partition = isinstance(params, GroupParams)
            elif step.operation in {"filter", "top_n"} and metrics:
                complete_partition = False
            fields = registry.propagate(step.operation, params, fields, reserved)
            reserved.update(fields)
            prefix.append({"operation": step.operation, "params": params.model_dump()})
        table = executed.result
        if {c.field for c in table.columns} != set(fields):
            reject("结果字段必须与操作链的最终输出完全一致。")
        if any(c.logical_type != fields[c.field].kind or (c.role == "metric") != (c.field in metrics) for c in table.columns):
            reject("结果字段类型或维度/指标角色与计划不一致。")
        if any(ref.metric_field not in metrics for ref in table.total_refs):
            reject("总体分母引用必须绑定实际指标字段。")
        for column in table.columns:
            if column.logical_type in {"date", "datetime"}:
                temporal_dims.add(column.field)
                timezone_modes = set()
                try:
                    for row in table.rows:
                        if row[column.field] is not None:
                            parsed = temporal(row[column.field])
                            if hasattr(parsed, "hour"):
                                timezone_modes.add(parsed.tzinfo is not None)
                            if (column.logical_type == "date") == hasattr(parsed, "hour"):
                                reject("日期字段包含日期时间值。")
                except (ValueError, TypeError):
                    reject("结果时间字段包含非法时间值。")
                if len(timezone_modes) > 1:
                    reject("同一时间字段混合有时区和无时区值，不能可靠比较时间顺序。")
            if column.field in metrics and metrics[column.field].function in {"count", "distinct_count"}:
                if column.unit not in {None, "条", "个", "记录", "次"}:
                    reject("计数指标的单位不能标记为金额或其他数值单位。")
                if any(row[column.field] is not None and (row[column.field] < 0 or row[column.field] > executed.effective_row_count) for row in table.rows):
                    reject("计数结果超出任务有效样本范围。")
        if dimensions:
            keys = [tuple(row[d] for d in dimensions) for row in table.rows]
            if len(keys) != len(set(keys)):
                reject("分组结果维度组合不能重复。")
        if sum(s.operation in {"aggregate", "group_aggregate"} for s in task.steps) == 1 and not table.truncated and not any(s.operation in {"filter", "top_n"} for s in task.steps[next((i + 1 for i,s in enumerate(task.steps) if s.operation in {"aggregate", "group_aggregate"}), len(task.steps)):]):
            for name, metric in metrics.items():
                if metric.function == "count" and metric.field is None:
                    values = [row[name] for row in table.rows]
                    if any(value is None for value in values) or sum(values) != executed.effective_row_count:
                        reject("完整行计数结果必须与任务有效行数一致。")
        descriptions[executed.task_id] = ResultDescription(metrics, dimensions, temporal_dims, scope_key,
                                                         complete_partition and not table.truncated)
    return checked, descriptions
