"""Bounded comparisons of verified result cells, never of LLM-provided numbers."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import math
from app.domain.analysis_report import Evidence
from .evidence import number, fmt


def comparison_evidence(execution, descriptions, start):
    result = []
    for task in execution.tasks:
        if task.status != 'success':
            continue
        table, desc = task.result, descriptions[task.task_id]
        if table.truncated or table.row_offset or len(desc.dimensions) != 1 or len(table.rows) < 2:
            continue
        dimension = desc.dimensions[0]
        if dimension in desc.temporal_dimensions or any(row[dimension] is None for row in table.rows):
            continue
        for field, metric in desc.metrics.items():
            if not all(number(row[field]) for row in table.rows):
                continue
            ranked = sorted(enumerate(table.rows), key=lambda pair: -Decimal(str(pair[1][field])))
            values = [Decimal(str(row[field])) for _, row in ranked]
            if len(set(values)) != len(values):
                continue
            first, second = ranked[0], ranked[1]
            left, right = first[1][dimension], second[1][dimension]
            column = next(c for c in table.columns if c.field == field)
            label = column.label.replace(' · ', '')[:100]
            common = {'metric_field': field, 'dimension_field': dimension,
                      'source_scope': task.scope, 'unit': '%', 'rounding': 'half_up_1_decimal'}

            def add(kind, numerator, denominator, rows, source, statement):
                if denominator <= 0:
                    return
                raw = numerator / denominator * 100
                if not math.isfinite(float(raw)):
                    return
                with localcontext() as ctx:
                    ctx.prec = max(28, raw.adjusted() + 10)
                    percent = raw.quantize(Decimal('.1'), rounding=ROUND_HALF_UP)
                value = {**common, **source, 'comparison_kind': kind,
                         'numerator': str(numerator), 'denominator': str(denominator), 'percent': str(percent)}
                scope = task.scope[:1700] + ('；分母仅为本次完整返回的分组合计，不是全部筛选范围或整体市场。'
                                      if kind == 'returned_concentration' else '；仅比较当前返回的同口径分组。')
                result.append(Evidence(evidence_id=f'E{start + len(result) + 1:04d}', task_id=task.task_id,
                    data_ref=table.result_id, result_field=field, evidence_type='comparison', value=value,
                    scope=scope, source_row_indices=rows,
                    calculation=f'{task.calculation[:500]}；{kind}：{source["formula"]}；字段 {field}，分子 {numerator}，分母 {denominator}；分母必须为正，百分比四舍五入一位小数。',
                    statement=statement(str(percent))))

            gap = values[0] - values[1]
            add('relative_lead', gap, values[1], [first[0], second[0]],
                {'left': left, 'right': right, 'left_value': str(values[0]), 'right_value': str(values[1]),
                 'difference': str(gap), 'formula': '(left_value - right_value) / right_value * 100'},
                lambda pct: f'在当前返回结果中，{fmt(left)}的{label}比{fmt(right)}高 {fmt(gap)}，相对{fmt(right)}领先约 {pct}%。')
            if len(ranked) >= 3 and values[-1] >= 0:
                last = ranked[-1]
                add('relative_ratio', values[-1], values[0], [last[0], first[0]],
                    {'left': last[1][dimension], 'right': left, 'left_value': str(values[-1]), 'right_value': str(values[0]),
                     'formula': 'left_value / right_value * 100'},
                    lambda pct: f'在当前返回结果中，{fmt(last[1][dimension])}的{label}为 {fmt(values[-1])}，约为{fmt(left)}的 {pct}%。')
                if metric.function in {'sum', 'count'} and all(v >= 0 for v in values):
                    add('returned_concentration', values[0] + values[1], sum(values), [index for index, _ in ranked],
                        {'left': left, 'right': right, 'left_value': str(values[0]), 'right_value': str(values[1]),
                         'returned_group_count': len(ranked), 'denominator_scope': 'returned_groups_only',
                         'formula': '(left_value + right_value) / returned_group_sum * 100'},
                        lambda pct: f'{fmt(left)}和{fmt(right)}合计占本次返回 {len(ranked)} 个分组{label}合计的约 {pct}%；分母仅为返回分组合计，不代表全部筛选范围或整体市场占比。')
    return result
