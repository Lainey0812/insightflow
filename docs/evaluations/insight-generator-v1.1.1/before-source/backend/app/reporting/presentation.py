"""Business report presentation from saved, validated result tables. No LLM or analysis rerun."""
from decimal import Decimal, ROUND_HALF_UP
import re

from app.domain.analysis_report import Evidence
from app.domain.report_presentation import ReportPresentation, PresentationFinding, PresentationMetric
from app.review.presentation import PlanPresentationMapper


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = Decimal(str(value))
    return value if value.is_finite() else None


def display(value):
    """Decimal formatting avoids float rounding of large integer source values."""
    value = Decimal(str(value))
    # Preserve source precision; only derived percentages have an explicit rounding rule.
    text = format(value, ',f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def percentage(numerator, denominator):
    if denominator <= 0:
        return None
    value = numerator / denominator * 100
    return value.quantize(Decimal('.1'), rounding=ROUND_HALF_UP)


def _scope(task, profile):
    mapper = PlanPresentationMapper(profile)
    lines = [line.replace('拟用统计口径：', '统计口径：') for line in mapper.steps(task)]
    fields = {f.field_id: f.display_name for f in profile.fields}
    derived_years = {s.params.get('alias') for s in task.steps if s.operation == 'derive' and s.params.get('function') == 'extract_year'}
    conditions = [c for s in task.steps if s.operation == 'filter' for c in s.params.get('conditions', [])]
    filter_ids = {s.step_id for s in task.steps if s.operation == 'filter'}
    filter_lines = [line for sid, line in mapper.step_details(task) if sid in filter_ids]
    years, regions, status, other = [], [], [], []
    consumed = set()
    for pos, c in enumerate(conditions):
        field, op, value = c.get('field'), c.get('operator'), c.get('value')
        if field in derived_years and op == 'eq' and isinstance(value, int) and not isinstance(value, bool):
            years.append(f'{value} 年'); consumed.add(pos)
        if field in fields and op == 'gte' and isinstance(value, str) and re.fullmatch(r'\d{4}-01-01', value):
            year = int(value[:4])
            end = next((i for i, x in enumerate(conditions) if x.get('field') == field and x.get('operator') == 'lt' and x.get('value') == f'{year + 1}-01-01'), None)
            if end is not None:
                years.append(f'{year} 年'); consumed.update({pos, end})
    for pos, c in enumerate(conditions):
        if pos in consumed:
            continue
        name, op, value = fields.get(c.get('field')), c.get('operator'), c.get('value')
        if op == 'eq' and name in {'地区', '区域'} and isinstance(value, str):
            regions.append(value if value.endswith('地区') else value + '地区')
        elif op == 'eq' and name == '订单状态' and isinstance(value, str):
            status.append(value + '订单')
        else:
            # Preserve all other actual filter conditions rather than guessing a compact meaning.
            label = filter_lines[pos] if pos < len(filter_lines) else None
            if label:
                other.append(label)
    compact = list(dict.fromkeys(years + regions + status + other))
    return lines, ''.join(dict.fromkeys(years + regions)), status + other, compact


def _general(report):
    scope = [line.replace('拟用统计口径：', '统计口径：') for m in report.execution_metadata.values() for line in m.get('approved_scope', [])]
    return ReportPresentation(report_id=report.report_id, kind='general',
        title=report.analysis_goal, subtitle=' · '.join(dict.fromkeys(scope)),
        executive_summary=report.summary.overview,
        key_metrics=[PresentationMetric(label=m.label, display_value=display(m.value) if decimal(m.value) is not None else str(m.value),
            caption=m.unit or '', evidence_refs=[m.evidence_ref]) for m in report.key_metrics],
        findings=[PresentationFinding(title=i.finding, body=' '.join([i.fact, i.implication]), evidence_refs=i.evidence_refs) for i in report.insights],
        recommendations=[r.text for r in report.recommendations], data_notes=[f'上传数据共 {report.dataset_row_count:,} 条。', *report.limitations],
        scope=list(dict.fromkeys(scope)), evidence=[])


def _legacy_presentation(report, profile=None):
    fallback = _general(report)
    if profile is None or report.report_status == 'unavailable':
        return fallback
    # Only one unambiguous successful core ranking direction is summarized this way.
    # Other plans keep their actual per-task facts without inventing a sales-specific story.
    core = [t for t in report.task_metadata.values() if t.priority == 'P0']
    if len(core) != 1:
        return fallback
    task = core[0]
    meta = report.execution_metadata.get(task.task_id, {})
    groups = [s for s in task.steps if s.operation in {'aggregate', 'group_aggregate'}]
    if meta.get('status') != 'success' or len(groups) != 1 or groups[0].operation != 'group_aggregate':
        return fallback
    group = groups[0]
    metrics, dimensions = group.params.get('metrics', []), group.params.get('dimensions', [])
    if len(metrics) != 1 or len(dimensions) != 1 or metrics[0].get('function') not in {'sum', 'count'}:
        return fallback
    field, dimension = metrics[0].get('alias'), dimensions[0]
    after = task.steps[task.steps.index(group) + 1:]
    if not after or after[-1].operation != 'top_n' or any(s.operation not in {'sort', 'top_n'} for s in after):
        return fallback
    top = after[-1].params
    if top.get('field') != field or top.get('direction') != 'desc' or any(s.params.get('field') != field or s.params.get('direction') != 'desc' for s in after):
        return fallback
    if top.get('n', 0) > 10:
        return fallback
    table = next((r for r in report.result_data.values() if r.result_id == meta.get('result_id')), None)
    if table is None or table.truncated or table.row_offset != 0 or not table.rows or len(table.rows) > top['n']:
        return fallback
    if any(decimal(row.get(field)) is None or row.get(dimension) is None for row in table.rows):
        return fallback
    ranked = sorted(enumerate(table.rows), key=lambda pair: -decimal(pair[1][field]))
    # Top-N tie membership has no unique ordinal; fall back to ordinary evidence on ties.
    values = [decimal(row[field]) for _, row in ranked]
    if len(values) != len(set(values)):
        return fallback
    names = {f.field_id: f.display_name for f in profile.fields}
    if metrics[0].get('function') == 'count':
        measure = '记录数量' if metrics[0].get('field') is None else names.get(metrics[0].get('field'), '该字段') + '非空记录数'
    else:
        measure = names.get(metrics[0].get('field'))
    if not measure or dimension not in names:
        return fallback
    dimension_label = names[dimension]
    labels = [str(row[dimension]) for _, row in ranked]
    count, n = len(ranked), top['n']
    lines, prefix, conditions, compact = _scope(task, profile)
    title = f'{prefix}{dimension_label}{measure} Top {n} 分析'
    subtitle = ' · '.join([*conditions, f'按{dimension_label}汇总', f'{measure}降序排名'])
    range_text = ''.join(compact) if compact else '本任务批准的筛选范围'
    chinese = {1:'一',2:'二',3:'三',4:'四',5:'五',6:'六',7:'七',8:'八',9:'九',10:'十'}
    returned = f'前{chinese[n]}名' if count == n else f'本次返回的 {count} 个分组'
    evidence = []
    def add(kind, value, indices, statement, calculation, scope=None):
        e = Evidence(evidence_id=f'V{len(evidence) + 1:03d}', task_id=task.task_id, data_ref=table.result_id,
            result_field=field, evidence_type=kind, value=value,
            source_row_indices=indices, scope=scope or f'{range_text}；{returned}结果表', calculation=calculation, statement=statement)
        evidence.append(e)
        return e.evidence_id
    leader = add('ranking', {'category': labels[0], 'value': ranked[0][1][field], 'rank': 1}, [ranked[0][0]],
        f'{labels[0]}的{measure}为 {display(values[0])}，在当前返回结果中居首。', f'按真实结果字段 {field} 降序比较，读取首位；未推断未返回类别。')
    cards = [PresentationMetric(label=f'第一名{measure}', display_value=display(values[0]), caption=labels[0], evidence_refs=[leader])]
    findings, summary_parts = [], []
    if count == n:
        summary_parts.append(f'在本次筛选范围内，{ "、".join(labels)}位列{measure}{returned}。')
    else:
        summary_parts.append(f'本次 Top {n} 选择实际返回 {count} 个{dimension_label}：{"、".join(labels)}。')
    if count >= 2:
        gap = values[0] - values[1]
        rate = percentage(gap, values[1])
        comparison = add('difference', {'left':labels[0], 'right':labels[1], 'difference':str(gap), 'left_value':ranked[0][1][field], 'right_value':ranked[1][1][field]},
            [ranked[0][0], ranked[1][0]], f'{labels[0]}领先{labels[1]} {display(gap)}。', f'{field}[{ranked[0][0]}] - {field}[{ranked[1][0]}]；仅比较同一结果表中的同口径指标。')
        gap_refs = [comparison]
        if rate is not None:
            relative = add('comparison', {'value':str(rate), 'numerator':str(gap), 'denominator':str(values[1]), 'unit':'%'},
                [ranked[0][0],ranked[1][0]], f'领先幅度约为 {rate}%，以{labels[1]}为基准。', '(第一名 - 第二名) / 第二名 × 100；分母为正，四舍五入至一位小数。')
            cards.append(PresentationMetric(label='领先第二名', display_value=f'{rate}%', caption=f'{labels[0]} vs {labels[1]}', evidence_refs=[comparison,relative]))
            gap_refs.append(relative)
        else:
            cards.append(PresentationMetric(label='领先第二名',display_value=display(gap),caption='第二名数值不为正，不计算领先比例',evidence_refs=[comparison]))
        body = f'{labels[0]}领先{labels[1]} {display(gap)}' + (f'，约为{labels[1]}{measure}的 {rate}%。' if rate is not None else '；第二名数值不为正，不计算相对领先比例。')
        # Do not invent a statistical significance or a subjective closeness threshold.
        findings.append(PresentationFinding(title=f'{labels[0]}与{labels[1]}的{measure}比较', body=body, evidence_refs=gap_refs))
        summary_parts.append(body)
    if count >= 3 and values[0] > 0 and values[-1] >= 0:
        ratio = percentage(values[-1], values[0])
        ref = add('comparison', {'value':str(ratio), 'numerator':str(values[-1]), 'denominator':str(values[0]), 'unit':'%'},
            [ranked[-1][0],ranked[0][0]], f'{labels[-1]}的{measure}约为{labels[0]}的 {ratio}%。', '末名已返回值 / 首名已返回值 × 100；分母为正，四舍五入至一位小数。')
        findings.append(PresentationFinding(title=f'{returned}{dimension_label}之间的{measure}差异',
            body=f'{labels[-1]}{measure}为 {display(values[-1])}，约为{labels[0]}的 {ratio}%。这一数值差异值得进一步调查，当前结果不能确定差异原因。',evidence_refs=[ref]))
    total = sum(values)
    if count >= 3 and total > 0 and all(v >= 0 for v in values):
        subtotal = values[0] + values[1]
        share = percentage(subtotal, total)
        label = f'占{returned}合计' if count == n else f'占本次返回 {count} 个分组合计'
        ref = add('proportion', {'value':str(share),'numerator':str(subtotal),'denominator':str(total),'unit':'%'},
            [index for index,_ in ranked], f'{labels[0]}和{labels[1]}合计占{returned}{measure}的 {share}%。',
            '(当前返回第一名 + 第二名) / 当前完整返回表全部分组之和 × 100；不是筛选范围总体占比；四舍五入至一位小数。',scope=f'{range_text}；分母仅为{returned}合计')
        cards.append(PresentationMetric(label='前两名合计占比',display_value=f'{share}%',caption=label,evidence_refs=[ref]))
        findings.append(PresentationFinding(title=f'前两名在{returned}中的合计占比',
            body=f'{labels[0]}和{labels[1]}合计占{returned}{measure}的 {share}%。注意，这并不是它们在整个地区或全部筛选结果中的{measure}占比。', evidence_refs=[ref]))
    recommendations = []
    if measure == '销售额':
        available = set(names.values())
        angles = []
        if available & {'订单编号', '订单号'}:
            angles.append('订单数量')
            angles.append('平均订单金额')
        if '产品类别' in available:
            angles.append('产品类别结构')
        if angles:
            recommendations = [f'比较{"、".join(labels)}的{"、".join(angles)}，寻找{measure}差异的可观察关联因素。这些补充分析尚未执行；当前数据结果不足以确定差异原因。']
            summary_parts.append(f'建议进一步从{"、".join(angles)}等角度调查{dimension_label}间差异。')
    if not recommendations:
        recommendations = ['结合当前分组的记录明细与采集口径继续核查差异；当前结果不足以确定差异原因。']
    sample = meta.get('valid_sample_count')
    notes = [f'上传数据共 {report.dataset_row_count:,} 条' + (f'，本任务报告有效样本量为 {sample:,} 条。' if isinstance(sample,int) else '；本任务未提供可合并的统一有效样本量。'),
        f'统计范围仅限{range_text}；结果仅返回{measure}{returned}。', '百分比按明确分母计算并四舍五入至一位小数；不能据此推断整个地区的市场占比或因果关系。']
    if report.goal_coverage != 'complete' or report.report_status != 'complete':
        summary_parts.insert(0,'本报告只展示已有结果，仍有未完成或未覆盖的问题。')
        notes.extend(report.limitations)
    else:
        defaults = {'结论仅适用于上传样本与本次分析范围，不能直接代表整体市场或总体人群。',
            '业务解释和行动建议采用谨慎表述，未经过严格事实验证，也不构成因果结论。'}
        notes.extend(s for s in report.limitations if s not in defaults and not s.endswith('：任务含 Top N 选择，不能仅凭返回表格确认所有分组均已覆盖。'))
    return ReportPresentation(report_id=report.report_id,kind='ranking',title=title,subtitle=subtitle,
        executive_summary=' '.join(summary_parts),key_metrics=cards,findings=findings,
        recommendations=recommendations,data_notes=list(dict.fromkeys(notes)),scope=lines,evidence=evidence)


def build_presentation(report, profile=None):
    """New reports display saved insights only. Old reports keep their explicit v1 view."""
    from .prompt import GENERATION_VERSION
    versions = {meta.get('insight_generation_version') for meta in report.execution_metadata.values()}
    if versions != {GENERATION_VERSION}:
        return _legacy_presentation(report, profile)
    view = _general(report)
    view.presentation_version = 'business-report-v1.1'
    view.title = report.summary.headline
    if len(report.key_metrics) >= 3 and report.key_metrics[0].label.startswith('第一名') and all(m.unit == '%' for m in report.key_metrics[1:3]):
        view.key_metrics = view.key_metrics[:3]
    view.findings = [PresentationFinding(title=i.finding, body=i.implication,
        evidence_refs=i.evidence_refs) for i in report.insights]
    # KPI formatting is presentation only; calculations and references are already saved.
    for metric, saved in zip(view.key_metrics, report.key_metrics):
        atom = next((e for e in report.evidence if e.evidence_id == saved.evidence_ref), None)
        if atom and atom.evidence_type == 'ranking':
            metric.caption = str(atom.value['category'])
        if saved.unit == '%':
            metric.display_value += '%'
            metric.caption = '仅适用于证据中明确的分母范围'
    samples = [(tid, m.get('valid_sample_count')) for tid, m in report.execution_metadata.items()
               if m.get('valid_sample_count') is not None]
    view.data_notes.extend(f'{report.task_metadata[tid].title}：执行记录的有效样本量为 {count} 条；各指标非空记录以原始计算口径为准。'
                           for tid, count in samples)
    return view
