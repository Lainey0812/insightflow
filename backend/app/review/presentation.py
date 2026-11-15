"""Business-only defaults, deterministic from the saved plan and proof results."""
import re
from app.domain.review_presentation import ReviewCondition, ReviewDirection, ReviewPresentation
from .constraint_audit import FUNCTIONS
from .confirmed_scope import decode, summary

IMPORTANCE = {'P0': '核心分析', 'P1': '辅助分析', 'P2': '补充分析'}
COVERAGE = {'complete': '已安排核心问题的分析', 'partial': '只能回答部分核心问题', 'blocked': '核心问题目前无法分析'}
REASONS = {
    'MISSING_FIELD': '缺少完成此分析所需的数据。', 'INVALID_DATA': '所需字段没有可用数据。',
    'UNSUPPORTED_OPERATION': '当前还不支持此分析方法。', 'TYPE_MISMATCH': '字段格式不适合这项计算，需要先补充可计算的数据。',
    'INVALID_FIELD_REFERENCE': '分析步骤引用的数据已不可用，需要重新生成方案。',
    'INVALID_OPERATION_ORDER': '分析步骤顺序不正确，需要重新生成方案。',
    'UNSUPPORTED_DEPENDENCY': '当前还不支持分析方向之间的结果联动。',
    'INVALID_SCHEMA': '分析步骤的设置不完整，需要重新生成方案。',
    'DATASET_VERSION_MISMATCH': '方案与当前文件版本不一致，请重新提出需求。',
    'UNKNOWN_REQUIREMENT': '此方向没有正确关联核心问题，需要重新生成方案。',
}
CATEGORIES = {'time_range': '时间范围', 'filters': '筛选范围', 'metric_requirements': '统计指标',
              'analysis_limits': '分析要求', 'scope': '范围一致性', 'context': '分析需求'}
OPERATORS = {'eq': '为', 'ne': '排除', 'gt': '大于', 'gte': '不小于', 'lt': '小于', 'lte': '不大于',
             'in': '属于', 'not_in': '不属于', 'is_null': '为空', 'not_null': '不为空'}


class PlanPresentationMapper:
    def __init__(self, profile):
        self.profile = profile
        self.names = {f.field_id: f.display_name for f in profile.fields}

    def text(self, value):
        confirmed = decode(str(value or ''), self.profile)
        if confirmed:
            return summary(confirmed, self.profile)
        s = str(value or '')
        s = re.sub(r'field_\d{4}', lambda m: self.names.get(m[0], '未识别字段'), s)
        for raw, label in {**IMPORTANCE, **REASONS, 'F0': '暂时无法分析', 'F1': '转换后可分析', 'F2': '可以分析', 'Schema': '结构'}.items():
            s = re.sub(r'(?<![A-Za-z0-9_])' + raw + r'(?![A-Za-z0-9_])', label, s)
        for raw, label in CATEGORIES.items():
            s = s.replace(raw + '：', label + '：').replace(raw + ':', label + '：')
        return s

    def step_details(self, task):
        names = dict(self.names)
        descriptions, by_step = [], []
        for step in task.steps:
            start = len(descriptions)
            p = step.params
            name = lambda field: names.get(field, '未识别字段')
            if step.operation == 'filter':
                for condition in p.get('conditions', []):
                    value = condition.get('value')
                    if isinstance(value, list):
                        value = '、'.join(map(str, value))
                    descriptions.append(f"{name(condition.get('field'))} {OPERATORS.get(condition.get('operator'), '待核对')} {value if value is not None else ''}".strip())
            elif step.operation in {'aggregate', 'group_aggregate'}:
                dimensions = p.get('dimensions', [])
                if dimensions:
                    descriptions.append('按' + '、'.join(name(d) for d in dimensions) + '分组')
                for metric in p.get('metrics', []):
                    label = ('记录数' if metric.get('field') is None and metric.get('function') == 'count'
                             else f"{name(metric.get('field'))} · {FUNCTIONS.get(metric.get('function'), '未支持口径')}")
                    names[metric.get('alias')] = label
                    descriptions.append('拟用统计口径：' + label)
                    if metric.get('field') is None and metric.get('function') == 'count':
                        descriptions.append('按上传记录逐行计数，不代表去重后的业务实体数量。')
            elif step.operation in {'sort', 'top_n'}:
                order = '从高到低' if p.get('direction') == 'desc' else '从低到高'
                descriptions.append(f"按{name(p.get('field'))}{order}排列" + (f"，取前 {p.get('n')} 名" if step.operation == 'top_n' else ''))
            elif step.operation == 'derive' and p.get('function') in {'extract_year', 'extract_month'}:
                label = '年份' if p['function'] == 'extract_year' else '月份'
                names[p.get('alias')] = name(p.get('field')) + '的' + label
                descriptions.append('从' + name(p.get('field')) + '提取' + label + '，再分析')
            else:
                descriptions.append('存在当前未支持的分析步骤')
            by_step += [(step.step_id, line) for line in descriptions[start:]]
        return by_step

    def steps(self, task):
        return [line for _, line in self.step_details(task)]

    def build(self, state, audit, issues, warnings):
        record = state.review_plan
        checked = record.validated_plan
        intent = checked.intent_snapshot
        conditions = [ReviewCondition(label=CATEGORIES.get(item.category, '分析条件'), text=self.text(item.raw_text),
                      verification=('已核对报告表达边界' if any(m.get('check') == 'enforced_report_boundary' for m in item.matches) else '已核对分析步骤') if item.status == 'verified' else '需要解决后才能开始', source=item.source)
                      for item in audit.items if item.category not in {'scope', 'context'}]
        if not conditions:
            conditions = [ReviewCondition(label='用户指定条件', text='没有单独指定时间、筛选或统计限制；请查看各方向拟用口径。',
                          verification='以当前方案为准', source='intent.constraints')]
        results = {v.task_id: v for v in checked.validation_results}
        editable = state.status in {'AWAITING_APPROVAL', 'APPROVED'}
        directions = []
        for task in sorted(checked.plan.tasks, key=lambda t: {'P0': 0, 'P1': 1, 'P2': 2}[t.priority]):
            result = results[task.task_id]
            for step_id, line in self.step_details(task):
                label = ('拟用统计口径' if line.startswith('拟用统计口径：') else
                         '拟用分组维度' if line.startswith('按') and line.endswith('分组') else
                         '拟用排序与展示' if line.startswith('按') and '排列' in line else None)
                if label and not any(c.label == label and c.text == line for c in conditions):
                    conditions.append(ReviewCondition(label=label, text=line, verification='来自当前方案，请结合待确认事项核对',
                        source=f'plan.tasks.{task.task_id}.steps.{step_id}'))
            gaps = []
            if not result.executable:
                gaps = [self.text(x) for x in task.missing_inputs] or [REASONS.get(result.reason_code, '此分析的设置需要核对。')]
            directions.append(ReviewDirection(task_id=task.task_id, title=self.text(task.title), question=self.text(task.business_question),
                importance=IMPORTANCE[task.priority], reason=self.text(task.priority_reason),
                readiness='暂时无法分析' if not result.executable else ('完成已支持的数据转换后可分析' if result.feasibility == 'F1' else '可以分析'),
                executable=result.executable, details=self.steps(task), gaps=gaps, can_remove=editable))
        return ReviewPresentation(session_id=state.id, revision=state.revision, plan_id=record.plan_id, plan_version=record.plan_version,
            goal=self.text(intent.analysis_goal.business_goal if intent else state.user_goal), coverage=COVERAGE[checked.coverage_status],
            conditions=conditions, directions=directions, issues=issues, warnings=warnings, audit=audit,
            data_overview=self.data_overview(),
            can_approve=not issues and state.status == 'AWAITING_APPROVAL',
            can_execute=not issues and state.status == 'APPROVED' and state.approved_plan_version == record.plan_version,
            technical_details={'record': record.model_dump(mode='json'), 'constraint_audit': audit.model_dump(mode='json'),
                               'session_status': state.status.value, 'revision': state.revision})

    def data_overview(self):
        """Profile facts only. A missing cell is not an invalid row or a cleaning receipt."""
        p = self.profile
        return {'dataset_id': p.dataset_id, 'dataset_version': p.dataset_version,
            'file_name': p.file_name, 'sheet_name': p.sheet_name,
            'row_count': p.row_count, 'column_count': p.column_count,
            'missing_cell_count': p.missing_cell_count, 'duplicate_row_count': p.duplicate_row_count,
            'fields_with_missing': [{'name': f.display_name, 'missing_count': f.missing_count} for f in p.fields if f.missing_count],
            'quality_notes': [self.text(issue.message) for issue in p.quality_issues],
            'cleaning_status': 'not_performed',
            'cleaning_notice': '已检查上传数据；尚未自动删除、填补或去重。疑似重复不等于错误记录。',
            'sample_notice': '筛选后及指标有效样本量需执行后按分析方向统计，当前不将缺失单元格换算为无效行。'}
