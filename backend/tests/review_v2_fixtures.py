"""Four domains using real profiler/validator/HITL/Engine, no model calls."""
from hitl_fixtures import save

CASES = {
    'sales': ('订单日期,地区,城市,订单状态,销售额\n2026-01-02,华东,上海,已完成,100\n2026-02-01,华东,南京,已完成,300\n2026-03-01,华东,济南,已完成,200\n2025-02-01,华东,上海,已完成,900\n2026-04-01,华南,广州,已完成,800\n2026-02-05,华东,上海,退款,700\n', '订单日期', '销售额', 'sum', ['华东地区', '已完成订单'], '销售额总和', '降序排名'),
    'jobs': ('发布日期,城市,岗位状态,招聘人数\n2026-01-02,上海,在招,3\n2026-02-01,北京,在招,5\n2026-03-01,杭州,在招,2\n2025-02-01,上海,在招,9\n2026-04-01,广州,已关闭,8\n', '发布日期', '招聘人数', 'sum', ['岗位状态为在招'], '招聘人数总和', '降序排名'),
    'tickets': ('创建日期,城市,工单状态,响应分钟\n2026-01-02,上海,已解决,10\n2026-02-01,北京,已解决,30\n2026-03-01,杭州,已解决,20\n2025-02-01,上海,已解决,90\n2026-04-01,广州,未解决,80\n', '创建日期', '响应分钟', 'avg', ['工单状态为已解决'], '平均响应分钟', '升序排名'),
    'projects': ('开始日期,城市,任务状态,工时\n2026-01-02,上海,已完成,10\n2026-02-01,北京,已完成,30\n2026-03-01,杭州,已完成,20\n2025-02-01,上海,已完成,90\n2026-04-01,广州,未完成,80\n', '开始日期', '工时', 'sum', ['任务状态为已完成'], '工时总和', '降序排名'),
}


def prepare(client, topic='sales'):
    csv, date, metric, fn, filters, raw_metric, ordering = CASES[topic]
    goal = f'分析2026年{raw_metric}，按城市汇总，{ordering}，取前三名'
    r = client.post('/api/v1/sessions', data={'goal': goal, 'manual_review': 'true'}, files={'file': (topic+'.csv', csv.encode())})
    assert r.status_code == 201, r.text
    state = r.json(); client.headers['X-Session-Token'] = state.pop('review_access_token')
    fields = {f['display_name']: f['field_id'] for f in state['profile']['fields']}
    conditions = [{'field': fields[date], 'operator': 'gte', 'value': '2026-01-01'}, {'field': fields[date], 'operator': 'lt', 'value': '2027-01-01'}]
    if topic == 'sales':
        conditions += [{'field': fields['地区'], 'operator': 'eq', 'value': '华东'}, {'field': fields['订单状态'], 'operator': 'eq', 'value': '已完成'}]
    else:
        condition_field = {'jobs': '岗位状态', 'tickets': '工单状态', 'projects': '任务状态'}[topic]
        condition_value = {'jobs': '在招', 'tickets': '已解决', 'projects': '已完成'}[topic]
        conditions.append({'field': fields[condition_field], 'operator': 'eq', 'value': condition_value})
    wrap = lambda value: {'raw_text': value, 'validation_status': 'unverified'}
    intent = {'analysis_mode': 'goal_driven', 'next_action': 'proceed', 'analysis_goal': {'analysis_object': topic, 'business_goal': goal, 'decision_goal': None},
              'constraints': {'time_range': wrap('2026年'), 'filters': list(map(wrap, filters)), 'metric_requirements': [wrap(raw_metric)],
                              'analysis_limits': list(map(wrap, ['按城市汇总', ordering, '取前三名']))}, 'uncertainties': [], 'clarification_questions': []}
    task = {'task_id': 'A01', 'title': '各城市'+raw_metric, 'business_question': '在指定范围内，各城市的'+raw_metric+'如何排名？',
            'priority': 'P0', 'priority_reason': '删除后无法回答核心城市比较问题', 'requirement_ids': ['C01'], 'depends_on': [], 'missing_inputs': [],
            'steps': [{'step_id': 'F', 'operation': 'filter', 'params': {'conditions': conditions}},
                      {'step_id': 'G', 'operation': 'group_aggregate', 'params': {'dimensions': [fields['城市']], 'metrics': [{'field': fields[metric], 'function': fn, 'alias': 'value'}]}},
                      {'step_id': 'O', 'operation': 'sort', 'params': {'field': 'value', 'direction': 'asc' if topic == 'tickets' else 'desc'}},
                      {'step_id': 'T', 'operation': 'top_n', 'params': {'field': 'value', 'direction': 'asc' if topic == 'tickets' else 'desc', 'n': 3}}]}
    plan = {**state['dataset_ref'], 'plan_id': 'review_'+state['id'], 'plan_version': 1, 'tasks': [task], 'core_requirements': [{'requirement_id': 'C01', 'description': goal}]}
    return state, {'plan': plan, 'intent': intent}, fields


def ready(client, topic='sales'):
    state, data, fields = prepare(client, topic)
    return save(client, state, data), fields
