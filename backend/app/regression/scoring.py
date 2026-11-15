"""Deterministic checks for the typical suite. Numbers come from the frozen cases.json, never from product code."""
import json
import math

AUTO_CASES = tuple(f'TC{i:02d}' for i in range(1, 13))
MANUAL_ONLY = {'TC13': '需要人工修改计划并在隔离环境验证旧审批失效。', 'TC14': '需要在隔离环境注入报告模型故障。',
               'TC15': '需要在隔离环境注入 Trace 写入故障。'}
# Cases whose correct behaviour is to stop before execution; the runner never approves them.
EXPECT_STOP = {'TC08', 'TC11'}
LLM_UNAVAILABLE_PREFIXES = ('LLM_', 'PLANNER_LLM_', 'PROMPT_', 'INTENT_LLM_')


def check(key, label, passed, expected=None, actual=None):
    return {'key': key, 'label': label, 'status': 'skip' if passed is None else ('pass' if passed else 'fail'),
            'expected': expected, 'actual': actual}


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _key(value):
    number = _number(value)
    if number is not None and number.is_integer():
        return str(int(number))
    return str(value).strip()


def find_mapping(tables, expected, exact=True):
    """True if some table has a label column and a numeric column matching expected {label: value}."""
    want = {_key(k): float(v) for k, v in expected.items()}
    best = None
    for rows in tables:
        if not rows:
            continue
        columns = list(rows[0])
        for label in columns:
            for value in columns:
                if label == value:
                    continue
                mapping = {}
                for row in rows:
                    number = _number(row.get(value))
                    if number is None:
                        break
                    mapping[_key(row.get(label))] = number
                else:
                    hits = sum(1 for k, v in want.items() if k in mapping and math.isclose(mapping[k], v, abs_tol=1e-6))
                    if hits == len(want) and (not exact or set(mapping) == set(want)):
                        return True, mapping
                    if best is None or hits > best[0]:
                        best = (hits, mapping)
    return False, best[1] if best else None


def expected_mappings(case):
    expected = case['expected']
    if case['case_id'] == 'TC12':
        rows = expected['result']
        return [('count', '各团队任务数量', {r['团队']: r['任务数量'] for r in rows}),
                ('sum', '各团队工时总和', {r['团队']: r['工时总和'] for r in rows})]
    if case['case_id'] == 'TC09':
        return [('after_reply', '澄清后各团队已完成任务数', expected['after_reply'])]
    if isinstance(expected.get('result'), list):
        return [('result', '结果表', {str(k): v for k, v in expected['result']})]
    return []


def fields_named(profile, fragment):
    return [f['field_id'] for f in profile.get('fields', []) if fragment in f.get('display_name', '')]


def score(case, observed):
    """observed: plain dict collected by the runner. Returns (status, checks)."""
    cid, checks = case['case_id'], []
    intent = observed.get('intent') or {}
    plan = observed.get('plan') or {}
    tables = observed.get('result_tables') or []
    want_intent = case['expected'].get('intent') or case['expected'].get('initial_intent')
    if want_intent:
        mode, _, action = (part.strip() for part in want_intent.partition('/'))
        actual = f"{intent.get('analysis_mode')} / {intent.get('next_action')}" if cid != 'TC09' else f"{observed.get('initial_analysis_mode')} / {observed.get('initial_next_action')}"
        got_mode, _, got_action = actual.partition(' / ')
        checks.append(check('intent', '意图识别', got_mode == mode and (not action or got_action == action), want_intent, actual))

    if cid == 'TC09':
        checks.append(check('clarified_first', '模糊请求先澄清、不先执行', observed.get('initial_status') == 'WAITING_FOR_CLARIFICATION',
                            'WAITING_FOR_CLARIFICATION', observed.get('initial_status')))
    if cid in EXPECT_STOP:
        stopped = observed.get('final_status') == 'WAITING_FOR_CLARIFICATION' or plan.get('coverage_status') in {'partial', 'blocked'}
        checks.append(check('stopped', '核心需求无法满足时阻断或澄清', stopped, 'coverage partial/blocked 或澄清',
                            f"{observed.get('final_status')} / coverage={plan.get('coverage_status')}"))
        checks.append(check('not_executed', '未执行计算', observed.get('execution_status') is None, None, observed.get('execution_status')))
        return verdict(observed, checks)

    if cid == 'TC06':
        salary = set(fields_named(observed.get('profile') or {}, '薪'))
        used = sorted(f for f in salary if f in json.dumps(plan.get('tasks') or [], ensure_ascii=False))
        checks.append(check('no_salary', '计划不含薪资分析', not used, [], used))
    if cid == 'TC07':
        checks.append(check('header_row', '按第 6 行表头解析出 8 行', (observed.get('profile') or {}).get('row_count') == case['expected']['uploaded_rows'],
                            case['expected']['uploaded_rows'], (observed.get('profile') or {}).get('row_count')))
    if cid == 'TC10':
        text = json.dumps(plan.get('tasks') or [], ensure_ascii=False).lower()
        checks.append(check('no_median', '未把中位数加为任务', 'median' not in text and '中位数' not in text, False, 'median' in text))

    if cid == 'TC05':
        checks.append(check('empty_not_error', '零记录不判为执行错误', observed.get('execution_status') not in {None, 'failed'},
                            'success / partial_success', observed.get('execution_status')))
        checks.append(check('no_fabricated_insight', '无数据时不调用模型生成洞察', observed.get('insight_calls') == 0 and not observed.get('insight_count'),
                            0, {'insight_calls': observed.get('insight_calls'), 'insight_count': observed.get('insight_count')}))
        return verdict(observed, checks)

    if cid not in {'TC06', 'TC07'} or observed.get('approved_by_runner'):
        checks.append(check('executed', '计算执行成功', observed.get('execution_status') == 'success', 'success', observed.get('execution_status')))
        checks.append(check('report', '报告已生成', observed.get('report_generation_status') == 'completed', 'completed', observed.get('report_generation_status')))
    for key, label, mapping in expected_mappings(case):
        found, actual = find_mapping(tables, mapping)
        checks.append(check('values_' + key, label, found, mapping, actual))
    return verdict(observed, checks)


def verdict(observed, checks):
    error = observed.get('error_code') or ''
    if observed.get('runner_error'):
        return 'blocked', checks
    if error.startswith(LLM_UNAVAILABLE_PREFIXES) and not any(c['status'] == 'pass' for c in checks if c['key'] != 'intent'):
        return 'blocked', checks
    if any(c['status'] == 'fail' for c in checks):
        return 'failed', checks
    return ('passed' if checks else 'needs_review'), checks
