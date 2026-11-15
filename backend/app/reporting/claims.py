"""Structured result/operand bindings. No natural-language inference or model calls.

Same-metric composition is supported by the current Draft contract. Cross-metric
facts may coexist as separate Insights; new cross-metric arithmetic needs an
explicit verified Evidence type, not a permanent ban on business comparisons.
"""
from dataclasses import dataclass
from decimal import Decimal
import math

from app.domain.errors import AppError
from .evidence import fmt


@dataclass(frozen=True)
class Binding:
    task_id: str
    result_id: str
    metric: str
    source_scope: str

    @classmethod
    def of(cls, evidence):
        return cls(evidence.task_id, evidence.data_ref, evidence.result_field,
                   evidence.value.get('source_scope', evidence.scope))


def compatible(primary, selected):
    if any(Binding.of(e) != Binding.of(primary) for e in selected):
        raise AppError('REPORT_INVALID_EVIDENCE_REFERENCE',
            '当前单条洞察只支持同指标同范围组合；跨指标事实请分别展示，派生计算需独立验证证据。', 502,
            details={'rule': 'SAME_METRIC_COMPOSITION',
                     'bindings': [Binding.of(e).__dict__ for e in selected]})


def decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Not numeric')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Nonfinite')
    return result


def same(actual, expected, *, derived=False):
    a, b = decimal(actual), decimal(expected)
    if a == a.to_integral_value() and b == b.to_integral_value():
        return a == b
    # Raw cells/ranks are exact. Only legacy float-derived arithmetic has a
    # relative tolerance, with no absolute floor that could erase tiny results.
    return a == b or (derived and math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=0))


def dimension(table):
    dims = [c.field for c in table.columns if c.role == 'dimension']
    return dims[0] if len(dims) == 1 else None


def validate_source(e, tables, tasks):
    """Recheck all base evidence against result cells, not only new ratios.

Execution sample counts are validated by report contracts and created from the
ExecutionResult, never supplied by the LLM. They have no result-table cell.
"""
    if tables is None:
        return
    try:
        table = tables[e.data_ref]
        if e.evidence_type == 'coverage':
            if e.result_field != '$execution.valid_sample_count' or e.source_row_indices:
                raise ValueError()
            return
        field, value = e.result_field, e.value
        col = next(c for c in table.columns if c.field == field and c.role == 'metric')
        indices = e.source_row_indices
        if not indices or len(indices) != len(set(indices)) or any(i < 0 or i >= len(table.rows) for i in indices):
            raise ValueError()
        rows = [table.rows[i] for i in indices]
        dim = dimension(table)
        pairs = [(i, decimal(r[field])) for i, r in enumerate(table.rows) if r[field] is not None]
        kind = e.evidence_type
        if kind in {'ranking', 'maximum', 'minimum'}:
            target = decimal(value['value'])
            if not dim or any(r[dim] != value['category'] for r in rows[:1]) or any(decimal(r[field]) != target for r in rows):
                raise ValueError()
            if kind == 'ranking' and (len(rows) != 1 or value['rank'] != 1 + sum(v > target for _, v in pairs)):
                raise ValueError()
            if kind != 'ranking':
                expected = (max if kind == 'maximum' else min)(v for _, v in pairs)
                if target != expected or set(indices) != {i for i, v in pairs if v == target} or value['tie_count'] != len(indices):
                    raise ValueError()
        elif kind == 'metric':
            expected = sum(decimal(r[field]) for r in rows)
            if len(rows) > 1:
                aggregates = [s for s in tasks[e.task_id].steps if s.operation in {'aggregate', 'group_aggregate'}]
                metric = next(m for m in aggregates[-1].params['metrics'] if m['alias'] == field)
                if metric['function'] not in {'sum', 'count'} or table.truncated or table.row_offset or set(indices) != set(range(len(table.rows))):
                    raise ValueError()
            if not same(value['value'], expected, derived=len(rows)>1) or value.get('unit') != col.unit:
                raise ValueError()
        elif kind in {'difference', 'comparison'} and not value.get('comparison_kind'):
            if 'left_field' in value:  # Existing explicit scalar comparison evidence.
                a, b = rows[0][value['left_field']], rows[0][value['right_field']]
            else:
                if not dim or len(rows) != 2 or rows[0][dim] != value['left'] or rows[1][dim] != value['right']:
                    raise ValueError()
                a, b = rows[0][field], rows[1][field]
            if not same(value['left_value'], a) or not same(value['right_value'], b) or not same(value['difference'], decimal(a)-decimal(b), derived=True):
                raise ValueError()
        elif kind == 'change_rate':
            if not dim or len(rows) != 2 or rows[0][dim] != value['from'] or rows[1][dim] != value['to']:
                raise ValueError()
            a, b = decimal(rows[0][field]), decimal(rows[1][field])
            if a <= 0 or not same(value['baseline'], a) or not same(value['current'], b) or not same(value['change_percent'], (b-a)/a*100, derived=True):
                raise ValueError()
        elif kind == 'proportion':
            if not dim or len(rows) != 1 or rows[0][dim] != value['category'] or not same(value['numerator'], rows[0][field]):
                raise ValueError()
            refs = [r for r in table.total_refs if r.metric_field == field]
            if refs:
                ref = refs[0]
                denominator = tables[ref.result_id].rows[0][ref.result_field]
                if ref.result_id not in e.related_result_refs:
                    raise ValueError()
            else:
                task = tasks[e.task_id]
                last_group = max(i for i, s in enumerate(task.steps) if s.operation == 'group_aggregate')
                if table.truncated or table.row_offset or any(s.operation in {'filter', 'top_n'} for s in task.steps[last_group+1:]):
                    raise ValueError()
                metric = next(m for m in task.steps[last_group].params['metrics'] if m['alias'] == field)
                if metric['function'] not in {'sum', 'count'} or len(pairs) != len(table.rows):
                    raise ValueError()
                denominator = sum(v for _, v in pairs)
            if decimal(denominator) <= 0 or not same(value['denominator'], denominator, derived=True) or not same(value['percent'], decimal(value['numerator'])/decimal(denominator)*100, derived=True):
                raise ValueError()
    except (ValueError, KeyError, IndexError, TypeError, StopIteration, ArithmeticError):
        raise AppError('REPORT_INVALID_FACT_BINDING', '证据的对象、指标、数值、排名或分母与计算结果不一致。', 502,
                       details={'rule': 'RESULT_CELL_BINDING', 'evidence_id': e.evidence_id}) from None


def all_returned_equal(selected, tables):
    if not selected or not tables:
        return False
    e = selected[0]
    table = tables[e.data_ref]
    values = [r.get(e.result_field) for r in table.rows]
    return (not table.truncated and not table.row_offset and bool(values) and
            all(v is not None for v in values) and len({decimal(v) for v in values}) == 1 and
            set(range(len(values))) <= {i for x in selected for i in x.source_row_indices})


def pair_terms(selected, tables):
    """Finite grammatical aliases backed by the actual dimension, not guessed topics."""
    if not tables or not selected or not any(('left' in e.value and 'right' in e.value) or e.evidence_type == 'change_rate' for e in selected):
        return []
    table = tables[selected[0].data_ref]
    dims = [c for c in table.columns if c.role == 'dimension']
    if len(dims) != 1:
        return []
    label = dims[0].label
    nouns = {label}
    if dims[0].logical_type in {'date', 'datetime'}:
        nouns.update({'时间点', '日期'})
    aliases = {'岗位类型': {'类岗位'}, '工单类型': {'类工单'}, '类别': {'类别', '类记录'}, '城市': {'城市'}}
    nouns.update(aliases.get(label, set()))
    return ['两者', '两个分组', *('两'+n if n.startswith('类') else '两个'+n for n in nouns)]


def render(e, table):
    """Canonical facts use structured operands, never model-provided numeric prose."""
    v = e.value
    column = next((c for c in table.columns if c.field == e.result_field), None)
    label = column.label.replace(' · ', '') if column else '记录'
    unit = column.unit or '' if column else ''
    kind = e.evidence_type
    if kind == 'coverage':
        return f"有效样本量 {fmt(v['valid_samples'])} 条，上传数据 {fmt(v['dataset_rows'])} 条。"
    if kind == 'metric':
        return f"{v.get('label', label)}为 {fmt(v['value'])}{unit}。"
    if kind in {'ranking', 'maximum', 'minimum'}:
        suffix = f"，返回结果内排名 {v['rank']}（并列同名次）" if kind == 'ranking' else f"，为返回结果{'最大' if kind == 'maximum' else '最小'}值"
        return f"{fmt(v['category'])}的{label}为 {fmt(v['value'])}{unit}{suffix}。"
    if kind == 'proportion':
        return f"{fmt(v['category'])}的{label}占已验证同口径总体的 {fmt(v['percent'])}%（分母 {fmt(v['denominator'])}{unit}）。"
    if kind == 'change_rate':
        return f"{fmt(v['from'])}至{fmt(v['to'])}，{label}从 {fmt(v['baseline'])} 变为 {fmt(v['current'])}，首末变化 {fmt(v['change_percent'])}%；不代表期间连续趋势。"
    ck = v.get('comparison_kind')
    if ck == 'relative_lead':
        return f"{fmt(v['left'])}的{label}比{fmt(v['right'])}高 {fmt(decimal(v['difference']))}{unit}，相对{fmt(v['right'])}高 {v['percent']}%。"
    if ck == 'relative_ratio':
        return f"{fmt(v['left'])}的{label}为 {fmt(decimal(v['left_value']))}{unit}，是{fmt(v['right'])}的 {v['percent']}%。"
    if ck == 'returned_concentration':
        return f"{fmt(v['left'])}和{fmt(v['right'])}合计占本次返回 {v['returned_group_count']} 个分组{label}的 {v['percent']}%；分母 {fmt(decimal(v['denominator']))}{unit}仅为返回分组合计，不是筛选范围总体。"
    left = v.get('left', v.get('left_field'))
    right = v.get('right', v.get('right_field'))
    return f"{fmt(left)}与{fmt(right)}的{label}差值为 {fmt(v['difference'])}{unit}。"


def compose(selected, tables):
    kept, seen = [], set()
    # A relative lead already carries the same absolute difference. Keep citations
    # but do not repeat the atom. Avoid dropping facts merely because numbers match.
    for e in selected:
        key = (e.result_field, str(e.value.get('category')), str(e.value.get('value')))
        if e.evidence_type in {'ranking', 'maximum', 'minimum'}:
            if key in seen:
                continue
            seen.add(key)
        redundant = e.evidence_type == 'difference' and any(
            x.value.get('comparison_kind') == 'relative_lead' and
            all(str(e.value.get(k)) == str(x.value.get(k)) for k in ['left', 'right', 'difference']) for x in selected)
        if not redundant:
            kept.append(render(e, tables[e.data_ref]) if tables else e.statement.replace(' · ', ''))
    return ' '.join(dict.fromkeys(kept))


def fact_details(selected):
    """Compact operand record for the expandable fact field, not another finding."""
    labels = {'category':'对象', 'value':'指标值', 'rank':'返回排名', 'left':'比较对象', 'right':'基准对象',
        'left_value':'对象值', 'right_value':'基准值', 'difference':'差值', 'numerator':'分子',
        'denominator':'分母', 'percent':'比例(%)', 'from':'首期', 'to':'末期',
        'baseline':'首期值', 'current':'末期值', 'change_percent':'首末变化(%)',
        'valid_samples':'有效样本量', 'dataset_rows':'上传行数'}
    parts = []
    for e in selected:
        fields = '，'.join(f'{label}={fmt(e.value[key])}' for key,label in labels.items() if key in e.value)
        parts.append(f'{e.evidence_id}（{e.result_field}）：{fields}')
    return '；'.join(parts)


def missing_metrics(evidence, tasks, insights):
    by_id = {e.evidence_id: e for e in evidence}
    required = {(e.task_id, e.result_field) for e in evidence
                if tasks[e.task_id].priority == 'P0' and not e.result_field.startswith('$')}
    covered = {(by_id[r].task_id, by_id[r].result_field) for i in insights for r in i.evidence_refs
               if r in by_id and not by_id[r].result_field.startswith('$')}
    return sorted(required-covered)
