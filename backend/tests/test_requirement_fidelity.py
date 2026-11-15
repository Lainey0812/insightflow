"""Requirement fidelity: a dropped exclusion is attributed to the stage that lost it."""
from app.evaluation.requirement_fidelity import assess, score_snapshot

FIELDS = [{'field_id': 'field_role', 'display_name': '岗位'}, {'field_id': 'field_city', 'display_name': '城市'}]
EXCLUDE = {'id': 'exclude_intern', 'kind': 'filter', 'polarity': 'exclude', 'field_name': '岗位', 'operator': 'ne',
           'value': '实习', 'forbidden_labels': ['实习'], 'required_labels': ['产品'], 'scope': 'every_executed'}
FILTER = {'step_id': 'S1', 'operation': 'filter', 'params': {'conditions': [{'field': 'field_role', 'operator': 'ne', 'value': '实习'}]}}
GROUP = {'step_id': 'S2', 'operation': 'group_aggregate', 'params': {'dimensions': ['field_city'], 'metrics': [{'function': 'count', 'field': None, 'alias': 'n'}]}}
KEPT = {'task_id': 'T1', 'priority': 'P0', 'steps': [FILTER, GROUP]}
DROPPED = {'task_id': 'T1', 'priority': 'P0', 'steps': [GROUP]}


def snapshot(intent_text, tasks, validated=None, steps=None, rows=None, execution='success'):
    if validated is None:
        validated = [KEPT]
    elif isinstance(validated, dict):
        validated = [validated]
    return {'fields': FIELDS,
            'intent': {'analysis_goal': {'business_goal': '统计岗位数量'},
                       'constraints': {'time_range': None, 'filters': [{'raw_text': intent_text}] if intent_text else [],
                                       'metric_requirements': [], 'analysis_limits': []}},
            'planner_tasks': tasks, 'planner_executable_task_ids': ['T1'],
            'validated_tasks': validated, 'executable_task_ids': ['T1'],
            'execution_status': execution, 'execution_steps': steps,
            'result_tables': [rows or [{'岗位': '产品', 'n': 3}]]}


def lost(text, tasks, **kwargs):
    report = score_snapshot([EXCLUDE], snapshot(text, tasks, **kwargs))
    row = report['obligations'][0]
    return row['lost_at'], row


def test_exclusion_kept_only_in_goal_fails_at_intent():
    steps = [{'task_id': 'T1', 'step_id': 'S1', 'operation': 'filter', 'status': 'success'},
             {'task_id': 'T1', 'step_id': 'S2', 'operation': 'group_aggregate', 'status': 'success'}]
    observed = snapshot('', [KEPT], steps=steps)
    observed['intent']['analysis_goal']['business_goal'] = '统计岗位数量，排除实习'
    observed['intent']['constraints']['filters'] = []
    row = score_snapshot([EXCLUDE], observed)['obligations'][0]
    assert row['lost_at'] == 'intent' and row['intent']['detail'] == 'prose_only'
    assert row['planner']['status'] == 'pass' and row['engine']['status'] == 'pass'


def test_planner_omission_is_not_blamed_on_the_engine():
    lost_at, row = lost('排除实习岗位', [DROPPED], validated=DROPPED, steps=[])
    assert lost_at == 'planner' and row['planner']['detail'] == 'condition_missing'
    assert row['engine']['detail'] == 'condition_missing_from_executed_plan'


def test_validator_drop_is_separate_from_the_planner_result():
    lost_at, row = lost('排除实习岗位', [KEPT], validated=DROPPED, steps=[])
    assert lost_at == 'validator' and row['validator']['detail'] == 'dropped_after_planning'
    assert row['planner']['status'] == 'pass'


def test_engine_result_containing_the_excluded_value_fails_even_when_versions_match():
    steps = [{'task_id': 'T1', 'step_id': 'S1', 'operation': 'filter', 'status': 'success', 'input_row_count': 4, 'output_row_count': 4}]
    lost_at, row = lost('排除实习岗位', [KEPT], steps=steps, rows=[{'岗位': '实习', 'n': 2}, {'岗位': '产品', 'n': 3}])
    assert lost_at == 'engine' and row['engine']['detail'] == 'excluded_value_in_result'
    assert row['validator']['status'] == 'pass'


def test_correct_result_without_the_filter_step_still_fails_the_engine():
    lost_at, row = lost('排除实习岗位', [KEPT], steps=[{'task_id': 'T1', 'step_id': 'S2', 'operation': 'group_aggregate', 'status': 'success'}])
    assert lost_at == 'engine' and row['engine']['detail'] == 'step_not_run'


def test_carried_exclusion_clears_all_four_stages():
    steps = [{'task_id': 'T1', 'step_id': 'S1', 'operation': 'filter', 'status': 'success'},
             {'task_id': 'T1', 'step_id': 'S2', 'operation': 'group_aggregate', 'status': 'success'}]
    report = score_snapshot([EXCLUDE], snapshot('排除实习岗位', [KEPT], steps=steps))
    assert report['carried_count'] == 1 and report['lost'] == []


def test_non_exclusion_and_reversal_do_not_count_as_capturing_the_constraint():
    assert lost('不排除实习岗位', [KEPT], steps=[])[0] == 'intent'
    assert lost('只看实习岗位', [KEPT], steps=[])[0] == 'intent'


def test_gold_file_refuses_a_different_query_and_unknown_cases():
    assert assess('TC02', {'intent': {}}, '另一句需求')['status'] == 'query_mismatch'
    assert assess('TC15', {'intent': {}}, '按团队统计已完成任务数量。')['status'] == 'not_in_gold'
    bound = assess('TC02', None, '只分析2026年华东地区已完成订单，排除上海，按城市汇总销售额并降序排名。')
    assert bound['status'] == 'not_observed'
