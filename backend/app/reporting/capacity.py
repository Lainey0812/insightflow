"""Shared, bounded report budgets. Preflight is an estimate, never a result claim."""
import json
import math
from app.domain.review_presentation import ReportCapacity

VERSION = 'report-capacity-v1'
GROUPS_PER_CALL = 8
MAX_GROUPS = 64
MAX_BATCHES = 8
MAX_EVIDENCE = 80
MAX_CONTEXT_BYTES = 160 * 1024


def encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def preflight(checked, profile):
    tasks = [t for t in checked.plan.tasks if t.task_id in checked.executable_task_ids]
    groups = []
    for task in tasks:
        aggregates = [s for s in task.steps if s.operation in {'aggregate', 'group_aggregate'}]
        if aggregates:
            groups += [(task, m) for m in aggregates[-1].params.get('metrics', [])]
    # Metadata is known; real result labels, quality context and evidence are
    # only available after execution and will be checked before any model call.
    intent = checked.intent_snapshot
    context = {'analysis_goal': intent.analysis_goal.model_dump() if intent else None,
               'constraints': intent.constraints.model_dump() if intent else {},
               'fields': [{'field_id': f.field_id, 'name': f.display_name,
                           'logical_type': f.logical_type} for f in profile.fields]}
    largest = max([encoded_bytes({**context, 'task': t.model_dump()}) for t in tasks] or [encoded_bytes(context)])
    supported = len(groups) <= MAX_GROUPS and largest < MAX_CONTEXT_BYTES
    count = math.ceil(len(groups) / GROUPS_PER_CALL) if groups else 0
    message = (f'本方案包含 {sum(t.priority == "P0" for t, _ in groups)} 个核心指标、共 {len(groups)} 个指标，'
               + (f'预计分 {count} 批生成并汇总为一份报告。' if count > 1 else '预计一次生成报告。'))
    if not supported:
        message = '方案超出报告总容量或已知元数据预算，请明确缩小分析范围后重新生成方案；系统不会自动删除核心指标。'
    return ReportCapacity(policy_version=VERSION, supported=supported, metric_count=len(groups),
        core_metric_count=sum(t.priority == 'P0' for t, _ in groups), estimated_batches=count,
        max_groups_per_call=GROUPS_PER_CALL, max_groups=MAX_GROUPS, max_batches=MAX_BATCHES,
        estimated_metadata_bytes=largest, context_estimate_only=True,
        message=message + ' 实际证据大小和模型生成结果将在执行后核验。')
