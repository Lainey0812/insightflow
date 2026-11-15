"""Finite, enforced report boundaries; never general semantic interpretation.

A report-only restriction is not a missing dataset filter. Proof is conditional
on the controlled V2 renderer, and the renderer checks the same contract again.
Unknown expressions remain unverified. No positive inference is authorized.
"""
import re
from app.domain.errors import AppError

POLICY_VERSION = 'controlled-report-boundaries-v1'
CONTROLLED_GENERATIONS = {'evidence-selection-v2.0', 'evidence-selection-v2.1', 'evidence-selection-v2.1.1'}
CAUSE_PHRASES = {
    '不要推断团队差异的原因', '不要推断差异原因', '不要推断差异的原因',
    '不要推断原因', '不要解释差异原因', '不要解释差异的原因',
}
PERFORMANCE_PHRASES = {'不要推断人员绩效', '不要推断团队绩效', '不要评价人员绩效', '不要评价团队绩效'}
PROFIT_PHRASES = {'不要分析利润', '不要计算利润', '不分析利润', '不计算利润'}


def boundary(text):
    value = re.sub(r'\s+', '', text).strip('。；;，,')
    if value.startswith('也'):
        value = value[1:]
    if value in CAUSE_PHRASES:
        return 'no_causal_inference'
    if value in PERFORMANCE_PHRASES:
        return 'no_performance_inference'
    if value in PROFIT_PHRASES:
        return 'no_profit_analysis'
    return None


def required(intent):
    return sorted({kind for c in intent.constraints.analysis_limits
                   for part in re.split(r'[，,；;]|并且|并|且', c.raw_text)
                   if (kind := boundary(part)) is not None})


def available():
    from app.reporting.prompt import GENERATION_VERSION
    return GENERATION_VERSION in CONTROLLED_GENERATIONS


def enforce(intent, generation_version, tasks=None, profile=None):
    policies = required(intent)
    if policies and generation_version not in CONTROLLED_GENERATIONS:
        raise AppError('REPORT_BOUNDARY_UNSUPPORTED', '当前报告生成版本不能保证已批准的表达边界，未生成报告。', 409)
    if 'no_profit_analysis' in policies and tasks is not None:
        if profile is None or any(not profit_references_absent(task, profile) for task in tasks):
            raise AppError('REPORT_BOUNDARY_VIOLATION', '执行来源包含被明确禁止的利润字段、别名或未支持计算，未生成报告。', 409)
    return policies


def profit_references_absent(task, profile):
    # Only structural identifiers/field labels are examined, not inferred NLU.
    prohibited = lambda text: bool(re.search(r'利润|盈利|毛利|净利|profit|margin', str(text), re.I))
    ids = {f.field_id for f in profile.fields if prohibited(f.original_name) or prohibited(f.display_name)}
    for step in task.steps:
        p = step.params
        refs = [p.get('field'), *p.get('dimensions', [])]
        refs += [c.get('field') for c in p.get('conditions', [])]
        refs += [m.get('field') for m in p.get('metrics', [])]
        aliases = [p.get('alias'), *[m.get('alias') for m in p.get('metrics', [])]]
        if any(ref in ids for ref in refs if ref) or any(prohibited(alias) for alias in aliases if alias):
            return False
        if step.operation not in {'filter','group_aggregate','aggregate','sort','top_n','derive'}:
            return False
        if step.operation == 'derive' and p.get('function') not in {'extract_year','extract_month'}:
            return False
    return True
