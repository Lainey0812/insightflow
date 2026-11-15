"""Compare a fresh replay with the frozen Bad Case. Prose expectations stay for a person."""
from app.regression.scoring import LLM_UNAVAILABLE_PREFIXES

OUTCOMES = ('cleared', 'recurred', 'changed', 'unchanged', 'blocked', 'source_missing', 'not_run')
NOTICE = '自动结果只看保存时的错误代码或需关注项是否再次出现。期望结果是标注人写的文字，这里不判通过或未通过。'


def _attention(quality):
    return [s.get('key') for s in ((quality or {}).get('signals') or []) if s.get('level') == 'attention' and s.get('key')]


def frozen_view(case):
    evidence = case.get('evidence') or {}
    failure = evidence.get('failure') or {}
    return {'business_status': (evidence.get('business_lifecycle') or {}).get('status'),
            'failure_code': failure.get('code'), 'attention': _attention(evidence.get('quality'))}


def judge(frozen, observed):
    """Return (outcome, reason). observed carries source_error or a runner projection."""
    if observed.get('source_error'):
        return 'source_missing', observed['source_error']
    if observed.get('runner_error'):
        return 'blocked', '运行器错误：' + str(observed['runner_error'])
    error = observed.get('error_code') or ''
    if error.startswith(LLM_UNAVAILABLE_PREFIXES):
        return 'blocked', '模型不可用：' + error
    new_failure = observed.get('failure') or {}
    new_code = new_failure.get('code') or None
    old_code = frozen.get('failure_code')
    if old_code:
        if new_code == old_code:
            return 'recurred', f'原错误代码 {old_code} 仍在。'
        if new_code:
            return 'changed', f'错误代码从 {old_code} 变为 {new_code}。'
        return 'cleared', f'原错误代码 {old_code} 未再出现。'
    old = set(frozen.get('attention') or [])
    new = set(_attention(observed.get('quality')))
    if old:
        still = sorted(old & new)
        if still == sorted(old):
            return 'recurred', '原需关注项仍在：' + '、'.join(still)
        if still:
            return 'changed', '部分需关注项仍在：' + '、'.join(still)
        return 'cleared', '原需关注项未再出现。'
    old_status, new_status = frozen.get('business_status'), observed.get('business_status')
    if old_status and new_status and old_status != new_status:
        return 'changed', f'业务状态从 {old_status} 变为 {new_status}。'
    return 'unchanged', '保存时没有错误代码或需关注项，业务状态也未变。'
