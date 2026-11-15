"""Typed, server-owned follow-up catalogue; never an executable analysis plan."""
from app.domain.errors import AppError

NUMERIC = {'integer', 'number'}
CATEGORICAL = {'text', 'boolean'}
TEMPORAL = {'date', 'datetime'}
NO_RECOMMENDATION = '现有证据仅支持上述统计结论，暂无额外建议。'


def group_key(evidence):
    return evidence.task_id, evidence.data_ref, evidence.result_field


def source_fields(task):
    refs = []
    for step in task.steps:
        p = step.params
        refs += [p.get('field'), *p.get('dimensions', [])]
        refs += [c.get('field') for c in p.get('conditions', [])]
        refs += [m.get('field') for m in p.get('metrics', [])]
    return {r for r in refs if r}


def label(profile, field_id):
    field = next(f for f in profile.fields if f.field_id == field_id)
    # Delimit labels as data; no field content is treated as an instruction.
    return '「' + field.display_name[:100] + '」'


def validate_option(option, primary, tasks, profile):
    if (option['task_id'], option['data_ref'], option['result_field']) != group_key(primary):
        raise AppError('REPORT_INVALID_RECOMMENDATION', '建议与当前发现的任务、结果或指标不一致。', 502,
                       details={'rule': 'RECOMMENDATION_BINDING'})
    fields = {f.field_id: f for f in profile.fields}
    ids = option['field_ids']
    if len(ids) != len(set(ids)) or not set(ids) <= fields.keys():
        raise AppError('REPORT_INVALID_RECOMMENDATION', '建议引用的字段无效。', 502,
                       details={'rule': 'RECOMMENDATION_FIELDS'})
    kind = option['kind']
    if kind == 'review_source_rows':
        valid = 1 <= len(ids) <= 2 and set(ids) <= source_fields(tasks[primary.task_id])
    elif kind == 'compare_distribution':
        valid = len(ids) == 1 and fields[ids[0]].logical_type in NUMERIC | CATEGORICAL | TEMPORAL
    elif kind == 'check_missingness':
        valid = len(ids) == 1 and fields[ids[0]].missing_count > 0 and ids[0] in source_fields(tasks[primary.task_id])
    else:
        valid = False
    if not valid:
        raise AppError('REPORT_INVALID_RECOMMENDATION', '建议类型、字段类型或数据依据不兼容。', 502,
                       details={'rule': 'RECOMMENDATION_CAPABILITY'})


def render_option(option, primary, tasks, profile):
    validate_option(option, primary, tasks, profile)
    names = '、'.join(label(profile, fid) for fid in option['field_ids'])
    kind = option['kind']
    if kind == 'check_missingness':
        text = f'核查上传数据中{names}的缺失记录与来源；上传缺失情况不等于本次筛选样本的缺失情况。'
    elif kind == 'review_source_rows':
        text = f'查看参与本次统计的来源记录，重点核对{names}及筛选口径。'
    else:
        field = next(f for f in profile.fields if f.field_id == option['field_ids'][0])
        if field.logical_type in NUMERIC:
            text = f'进一步查看{names}的数值分布与非空记录情况，评估当前统计值的代表性。'
        elif field.logical_type in TEMPORAL:
            text = f'进一步查看{names}的时间分布，核查记录覆盖的时间范围。'
        else:
            text = f'进一步比较{names}的类别分布，核查当前记录的构成。'
    return text + '该后续核查尚未执行，需另行提出需求、规划并确认。'


def build_catalog(evidence, tasks, profile, intent=None):
    """Offer at most four grounded choices per actual metric group.

    The model selects a useful choice. This list is not a fallback insight and
    does not claim that every type-compatible follow-up has business value.
    """
    fields = {f.field_id: f for f in profile.fields}
    forbidden, allow_additional = set(), True
    if intent is not None:
        # Reuse the existing bounded constraint grammar. Unknown boundaries do
        # not authorize extra directions; the approved source review remains.
        from app.review.constraint_audit import ConstraintAuditor
        auditor = ConstraintAuditor(profile)
        for limit in intent.constraints.analysis_limits:
            clauses = auditor.parse(limit.raw_text, 'analysis_limits')
            if clauses is None:
                allow_additional = False
            else:
                forbidden.update(c.field for c in clauses if c.kind == 'prohibited' and c.field)
    groups = {}
    for item in evidence:
        groups.setdefault(group_key(item), item)
    result = {}
    for (task_id, ref, metric), primary in groups.items():
        referenced = source_fields(tasks[task_id]) - forbidden
        metric_fields = [m.get('field') for s in tasks[task_id].steps for m in s.params.get('metrics', [])
                         if m.get('alias') == metric and m.get('field') in fields]
        dimensions = [d for s in tasks[task_id].steps for d in s.params.get('dimensions', []) if d in fields]
        relevant = list(dict.fromkeys([*metric_fields, *dimensions,
            *(f.field_id for f in profile.fields if f.field_id in referenced)]))
        relevant = [fid for fid in relevant if fid not in forbidden]
        choices = []
        if relevant:
            choices.append(('review_source_rows', relevant[:2]))
        missing = next((fid for fid in relevant if fields[fid].missing_count), None)
        if missing:
            choices.append(('check_missingness', [missing]))
        # Additional structure should use existing fields, not invented sales,
        # customer or efficiency metrics. Keep the prompt catalogue bounded.
        extras = [f.field_id for f in profile.fields if f.field_id not in relevant and f.field_id not in forbidden and
                  f.logical_type in NUMERIC | CATEGORICAL | TEMPORAL]
        if not allow_additional:
            extras = []
        distribution = extras[:2] or relevant[:1]
        choices += [('compare_distribution', [fid]) for fid in distribution]
        for kind, ids in choices[:4]:
            option = {'option_id': f'N{len(result)+1:04d}', 'task_id': task_id,
                      'data_ref': ref, 'result_field': metric, 'kind': kind, 'field_ids': ids}
            option['description'] = render_option(option, primary, tasks, profile)
            result[option['option_id']] = option
    return result
