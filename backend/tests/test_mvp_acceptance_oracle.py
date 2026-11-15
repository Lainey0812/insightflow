"""Product acceptance oracle safety. No models, production data or operation handlers."""
import importlib.util
import json
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_mvp_acceptance.py'
SPEC = importlib.util.spec_from_file_location('mvp_acceptance_oracle', SCRIPT)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def fixture():
    case = json.loads((oracle.FROZEN / 'cases.json').read_text())[0]
    source = pd.read_csv(oracle.FROZEN / 'sales.csv')
    names = {name: name for name in source.columns}
    return case, source, names


def plan():
    return {'tasks': [{'task_id': 'test', 'steps': [
        {'operation': 'filter', 'params': {'conditions': [
            {'field': '地区', 'operator': 'eq', 'value': '华东'},
            {'field': '订单状态', 'operator': 'eq', 'value': '已完成'}]}},
        {'operation': 'derive', 'params': {'function': 'extract_year', 'field': '订单日期', 'alias': 'year'}},
        {'operation': 'filter', 'params': {'conditions': [{'field': 'year', 'operator': 'eq', 'value': 2026}]}},
        {'operation': 'group_aggregate', 'params': {'dimensions': ['城市'], 'metrics': [{'function': 'sum', 'field': '销售额', 'alias': 'sales'}]}},
        {'operation': 'top_n', 'params': {'field': 'sales', 'direction': 'desc', 'n': 3}},
    ]}]}


def test_freeze_integrity_and_sales_business_answer():
    oracle.verify_freeze()
    case, source, names = fixture()
    rows, members = oracle.business_oracle(source, case, names)
    assert rows == [{'category': '济南', 'value': 21250}, {'category': '南京', 'value': 20250}, {'category': '上海', 'value': 5760}]
    assert len(members) == 6


def test_correct_goal_chain_passes_without_using_engine():
    case, source, names = fixture()
    checked = oracle.check_plan(case, plan(), {'coverage_status': 'complete'}, source, names)
    assert checked['errors'] == []


def test_equal_result_cannot_hide_extra_filtered_record():
    case, source, names = fixture()
    # Zero-valued cancelled row leaves the sums unchanged but violates the scope.
    source.loc[8, '销售额'] = 0
    source.loc[9, '销售额'] = 0
    candidate = plan()
    candidate['tasks'][0]['steps'][0]['params']['conditions'].pop()
    checked = oracle.check_plan(case, candidate, {'coverage_status': 'complete'}, source, names)
    assert 'FILTER_SCOPE_MISMATCH' in checked['errors']


def test_wrong_statistic_is_not_accepted_by_alias_or_title():
    case, source, names = fixture()
    candidate = plan()
    candidate['tasks'][0]['steps'][3]['params']['metrics'][0]['function'] = 'avg'
    checked = oracle.check_plan(case, candidate, {'coverage_status': 'complete'}, source, names)
    assert 'REQUIRED_METRIC_OR_DIMENSION_NOT_PLANNED' in checked['errors']


def test_missing_ranking_limit_is_not_inferred_from_few_rows():
    case, source, names = fixture()
    candidate = plan()
    candidate['tasks'][0]['steps'][-1] = {'operation': 'sort', 'params': {'field': 'sales', 'direction': 'desc'}}
    checked = oracle.check_plan(case, candidate, {'coverage_status': 'complete'}, source, names)
    assert 'TOP_N_NOT_PRESERVED' in checked['errors']
