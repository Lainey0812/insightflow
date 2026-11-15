"""Golden-set scoring uses the frozen oracles. It does not call a model."""
import hashlib
from pathlib import Path
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden, salary_executed, score_case

GOLD = {case['case_id']: case for case in load_golden()['cases']}


def test_set_stays_at_five_cases_and_nine_rows():
    document = load_golden()
    assert [case['case_id'] for case in document['cases']] == ['RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05']
    assert len(document['rows']) == 9
    assert document['cases'][4]['oracle'] == {'深圳': 3, '北京': 1, '杭州': 1}
    admin = Path(__file__).resolve().parents[2] / 'admin/src/features/evaluations/golden-set.json'
    assert hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest() == hashlib.sha256(admin.read_bytes()).hexdigest()


def test_exact_city_counts_pass_and_known_wrong_counts_keep_their_class():
    passed = score_case(GOLD['RF-01'], {'execution_status': 'success', 'result_tables': [[{'城市': '上海', '岗位数量': 3}, {'城市': '深圳', '岗位数量': 1}]]})
    assert passed['status'] == 'passed' and passed['failure'] is None
    dropped = score_case(GOLD['RF-01'], {'execution_status': 'success', 'result_tables': [[{'城市': '上海', '岗位数量': 4}, {'城市': '深圳', '岗位数量': 3}]]})
    assert dropped['failure'] == 'F-EXCLUDE-DROPPED'
    partial = score_case(GOLD['RF-05'], {'execution_status': 'success', 'result_tables': [[{'城市': '深圳', 'n': 3}, {'城市': '北京', 'n': 1}]]})
    assert partial['failure'] == 'F-ORACLE-MISS'
    complete = score_case(GOLD['RF-05'], {'execution_status': 'success', 'result_tables': [[{'城市': '杭州', 'n': 1}, {'城市': '北京', 'n': 1}, {'城市': '深圳', 'n': 3}]]})
    assert complete['status'] == 'passed'


def test_salary_execution_fails_rf04_even_when_the_count_is_right():
    tables = [[{'城市': '上海', '岗位数量': 3}, {'城市': '深圳', '岗位数量': 1}]]
    tasks = [{'steps': [{'operation': 'aggregate', 'params': {'metrics': [{'function': 'avg', 'field': 'field_pay'}]}}]}]
    fields = [{'field_id': 'field_pay', 'display_name': '薪资区间'}]
    assert salary_executed([{'business_question': '不要分析薪资', 'steps': []}], fields, tables) is False
    failed = score_case(GOLD['RF-04'], {'execution_status': 'success', 'result_tables': tables, 'plan': {'tasks': tasks}, 'profile': {'fields': fields}})
    assert failed['failure'] == 'F-METRIC-SUBSTITUTED'
    kept = score_case(GOLD['RF-04'], {'execution_status': 'success', 'result_tables': tables, 'plan': {'tasks': [{'business_question': '不要分析薪资', 'steps': []}]}, 'profile': {'fields': fields}})
    assert kept['status'] == 'passed'
