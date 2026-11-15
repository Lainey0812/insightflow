"""Batch regression: deterministic scoring, isolated end-to-end run with a controlled provider, read-only Admin view."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.regression.runner import evaluate, summarize, write_new
from app.regression.scoring import find_mapping, score
from test_report_workflow import Provider, SALES, QUERY
from test_trace_closure_c2 import AUTH, http_provider

SUITE = json.loads((Path(__file__).resolve().parents[2] / 'docs/testing/typical-suite-v1-2026-11-09/cases.json').read_text())
CASES = {c['case_id']: c for c in SUITE['cases']}


def test_find_mapping_matches_label_and_value_columns_regardless_of_order():
    rows = [{'field_0003': '南京', 'sales_total': 20250.0}, {'field_0003': '济南', 'sales_total': 21250}, {'field_0003': '上海', 'sales_total': 5760}]
    assert find_mapping([rows], {'济南': 21250, '南京': 20250, '上海': 5760})[0]
    assert not find_mapping([rows], {'济南': 21250, '南京': 20250})[0]
    assert find_mapping([rows], {'济南': 21250, '南京': 20250}, exact=False)[0]
    found, closest = find_mapping([rows], {'济南': 1, '南京': 20250, '上海': 5760})
    assert not found and closest['南京'] == 20250
    assert find_mapping([[{'month': 1.0, 'v': 27760}, {'month': 2, 'v': 22240}]], {'1': 27760, '2': 22240})[0]


def test_stop_cases_pass_only_when_blocked_and_not_executed():
    case = CASES['TC11']
    status, checks = score(case, {'final_status': 'AWAITING_APPROVAL', 'plan': {'coverage_status': 'blocked'}})
    assert status == 'passed', checks
    status, _ = score(case, {'final_status': 'AWAITING_APPROVAL', 'plan': {'coverage_status': 'complete'}})
    assert status == 'failed'
    status, _ = score(case, {'final_status': 'COMPLETED', 'plan': {'coverage_status': 'partial'}, 'execution_status': 'success'})
    assert status == 'failed'


def test_empty_result_and_llm_outage_and_runner_errors_are_classified():
    status, checks = score(CASES['TC05'], {'execution_status': 'success', 'insight_calls': 1, 'insight_count': 2})
    assert status == 'failed' and {c['key']: c['status'] for c in checks}['no_fabricated_insight'] == 'fail'
    assert score(CASES['TC05'], {'execution_status': 'success', 'insight_calls': 0, 'insight_count': 0})[0] == 'passed'
    assert score(CASES['TC01'], {'final_status': 'FAILED', 'error_code': 'LLM_TIMEOUT'})[0] == 'blocked'
    assert score(CASES['TC01'], {'runner_error': 'KeyError'})[0] == 'blocked'
    tc12 = score(CASES['TC12'], {'execution_status': 'success', 'report_generation_status': 'completed', 'intent': {},
        'result_tables': [[{'团队': '运营', 'n': 2, 'h': 10}, {'团队': '研发', 'n': 2, 'h': 20}]]})
    assert tc12[0] == 'passed', tc12[1]


def isolated_suite(tmp_path):
    suite = tmp_path / 'suite'
    (suite / 'data').mkdir(parents=True)
    (suite / 'data/sales.csv').write_bytes(SALES)
    case = {**CASES['TC01'], 'user_query': QUERY}
    return suite, [case, CASES['TC14']]


def test_end_to_end_run_approves_executes_scores_and_records_versions(tmp_path):
    suite, cases = isolated_suite(tmp_path)
    provider, _ = http_provider(Provider())
    app = create_app(Settings(tmp_path / 'data'), provider)
    with TestClient(app) as client:
        results = evaluate(client, app, cases, suite, 'rg_test')
    tc01, tc14 = results
    assert tc01['status'] == 'passed', tc01['checks']
    assert tc01['approved_by_runner'] and '代为批准' in tc01['approval_note']
    assert tc01['execution_status'] == 'success' and tc01['report_generation_status'] == 'completed'
    assert tc01['workflow_id'] and tc01['quality']['signals'] and tc01['llm']['calls'] >= 3
    assert set(tc01['prompt_templates']) >= {'intent_parser', 'analysis_planner', 'insight_generator'}
    assert tc14['status'] == 'not_run' and '故障' in tc14['reason']
    summary = summarize(results)
    assert summary['passed'] == 1 and summary['auto_total'] == 1 and summary['counts']['not_run'] == 1
    assert QUERY not in json.dumps(summary, ensure_ascii=False)


def test_admin_lists_finished_and_incomplete_runs_read_only(tmp_path):
    runs = tmp_path / 'regression/runs'
    finished, partial = runs / 'rg_20261110-010000_aaaaaa', runs / 'rg_20261110-020000_bbbbbb'
    for run_dir in (finished, partial):
        (run_dir / 'cases').mkdir(parents=True)
    start = {'schema_version': 'regression-run-v1', 'label': 'baseline', 'started_at': 't', 'suite': {}, 'environment': {'model': 'm'}, 'source_fingerprint': 'f', 'selected_cases': ['TC01']}
    case = {'case_id': 'TC01', 'title': 't', 'status': 'passed', 'checks': [], 'llm': {'calls': 3}, 'duration_ms': 10, 'prompt_templates': {'intent_parser': ['pt_1']}}
    write_new(finished / 'run.json', {**start, 'run_id': finished.name, 'finished_at': 'u', 'summary': summarize([case]), 'cases': [case]})
    write_new(partial / 'run-start.json', {**start, 'run_id': partial.name})
    write_new(partial / 'cases/TC01.json', {**case, 'status': 'failed'})
    (runs / '..evil').mkdir()
    app = create_app(Settings(tmp_path, admin_read_token='read'))
    with TestClient(app) as client:
        page = client.get('/admin/regression-runs', headers=AUTH).json()
        assert [i['run_id'] for i in page['items']] == [partial.name, finished.name]
        assert [i['state'] for i in page['items']] == ['incomplete', 'finished']
        assert page['items'][0]['summary']['counts'] == {'failed': 1}
        detail = client.get('/admin/regression-runs/' + finished.name, headers=AUTH).json()
        assert detail['cases'][0]['status'] == 'passed' and detail['summary']['prompt_templates'] == {'intent_parser': ['pt_1']}
        assert client.get('/admin/regression-runs/..evil', headers=AUTH).status_code == 404
        assert client.get('/admin/regression-runs/rg_20261110-030000_cccccc', headers=AUTH).status_code == 404
        assert client.get('/admin/regression-runs').status_code == 403
        assert client.post('/admin/regression-runs', headers=AUTH).status_code == 405
