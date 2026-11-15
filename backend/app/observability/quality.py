"""Quality signals derived from collected spans, calls and business facts only. Missing data stays unavailable."""

STAGES = {'understanding': '需求理解', 'planning': '分析规划', 'review': '人工审核', 'execution': '计算执行',
          'report': '报告生成', 'model': '模型调用'}


def _signal(key, stage, label, value, attention=None, note=''):
    level = 'unavailable' if value is None else ('attention' if attention else 'normal')
    return {'key': key, 'stage': stage, 'label': label, 'value': value, 'level': level, 'note': note}


def _latest(nodes, name, attribute=None):
    matches = [n for n in nodes if n.get('name') == name and (attribute is None or attribute in (n.get('attributes') or {}))]
    return (matches[-1].get('attributes') or {}) if matches else None


def quality_signals(nodes, llm_calls, business, reports=()):
    """nodes must be sorted by start time. Only actually collected values are reported."""
    nodes = list(nodes)
    signals = []

    intents = [n for n in nodes if n.get('name') == 'intent_parser' and 'next_action' in (n.get('attributes') or {})]
    clarify = sum(1 for n in intents if n['attributes']['next_action'] == 'clarify') if intents else None
    signals.append(_signal('clarification_rounds', 'understanding', '需求澄清轮数', clarify, clarify,
                           '需求不明确时模型要求用户补充；多轮澄清说明需求表达或意图识别存在困难。'))

    planner = _latest(nodes, 'analysis_planner', 'coverage_status')
    coverage = planner.get('coverage_status') if planner else None
    signals.append(_signal('planner_coverage', 'planning', '规划覆盖度', coverage, coverage not in (None, 'complete'),
                           'complete 表示核心需求都有对应任务；partial/blocked 表示部分需求无法规划。'))
    blocked = planner.get('blocked_count') if planner else None
    signals.append(_signal('planner_blocked_tasks', 'planning', '规划中被阻断的任务数', blocked, blocked,
                           '校验判定无法执行的任务数量。'))

    validator = _latest(nodes, 'plan_validator', 'f0_count')
    for key, label, note in (('f0_count', 'F0 不可执行任务数', '字段或能力不满足，任务不能执行。'),
                             ('f1_count', 'F1 需数据转换任务数', '需要日期派生等转换后才能执行，属于正常但值得核对。'),
                             ('unmet_core_count', '未覆盖的核心需求数', '用户核心诉求没有可执行任务承接。')):
        value = validator.get(key) if validator else None
        signals.append(_signal(key, 'planning', label, value, key != 'f1_count' and value,
                               note + ('' if validator else ' 早于本功能的记录未采集。')))

    reviews = [n for n in nodes if n.get('name') == 'hitl' and 'command' in (n.get('attributes') or {})]
    revisions = sum(1 for n in reviews if n['attributes']['command'] == 'revise') if reviews else None
    signals.append(_signal('hitl_revisions', 'review', '用户修改计划次数', revisions, revisions,
                           '用户在审批前修改或删除任务，通常说明规划未完全符合预期。'))

    engine = _latest(nodes, 'analysis_engine', 'execution_status')
    status = business.get('execution_status') or (engine or {}).get('execution_status')
    signals.append(_signal('execution_status', 'execution', '执行结果', status, status not in (None, 'success'),
                           'partial_success/failed 表示有任务计算失败。'))

    accepted_attempt = next((r.get('accepted_report_attempt') for r in reports if r.get('accepted_report_attempt')), None)
    validators = [n.get('attributes') or {} for n in nodes if n.get('name') == 'fact_validator' and 'candidate_count' in (n.get('attributes') or {})]
    if validators:
        attempt = accepted_attempt or max((v.get('report_attempt') or 0) for v in validators)
        scoped = [v for v in validators if (v.get('report_attempt') or 0) == attempt] or validators
        candidates = sum(v.get('candidate_count') or 0 for v in scoped)
        rejected = sum(v.get('rejected_count') or 0 for v in scoped)
    else:
        candidates = rejected = None
    signals.append(_signal('insight_candidates', 'report', '洞察候选数', candidates, candidates == 0,
                           '模型提出的候选结论数量（采用的报告尝试）。'))
    signals.append(_signal('insight_rejected', 'report', '事实校验拒绝数', rejected, rejected,
                           '被拒绝的候选与证据不符；可在模型调用详情查看原始返回。'))
    attempts = [v.get('report_attempt') for v in (n.get('attributes') or {} for n in nodes if n.get('name') == 'report_persistence') if v.get('report_attempt')]
    report_attempts = max(attempts) if attempts else None
    signals.append(_signal('report_attempts', 'report', '报告生成尝试次数', report_attempts, (report_attempts or 0) > 1,
                           '大于 1 表示报告至少失败重试过一次。'))
    report_status = business.get('report_status')
    signals.append(_signal('report_status', 'report', '报告完整度', report_status, report_status not in (None, 'complete'),
                           'partial 表示部分方向没有可交付结论。'))
    goal = business.get('goal_coverage')
    signals.append(_signal('goal_coverage', 'report', '目标覆盖', goal, goal not in (None, 'complete'),
                           '报告对用户分析目标的覆盖程度。'))

    calls = list(llm_calls)
    retries = sum(1 for c in calls if (c.get('retry_index') or 0) > 0) if calls else None
    failed = sum(1 for c in calls if c.get('status') in {'failed', 'cancelled', 'interrupted'}) if calls else None
    signals.append(_signal('llm_retries', 'model', '模型请求重试次数', retries, retries,
                           '输出不合规或调用失败后的自动重试。'))
    signals.append(_signal('llm_failed_calls', 'model', '模型调用失败数', failed, failed,
                           '超时、服务错误或响应不完整。'))

    return {'signals': signals, 'attention_count': sum(1 for s in signals if s['level'] == 'attention'),
            'unavailable_count': sum(1 for s in signals if s['level'] == 'unavailable'),
            'notice': '信号由已采集的节点与调用推导，仅提示需要关注的位置，不代表结论正确与否；未采集项不按 0 处理。'}
