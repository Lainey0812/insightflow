"""Failure attribution and node input summaries in the Admin workflow projection."""
import json
import time
from fastapi.testclient import TestClient
from test_trace_closure_c2 import application, AUTH
from test_report_workflow import run
from app.observability.failures import CATEGORIES, classify, first_failure


def test_classify_known_and_unknown_codes():
    assert classify('EMPTY_HEADER')['category'] == 'file_input'
    assert 'input_header_row' in classify('EMPTY_HEADER')['hint']
    assert classify('CSV_ROW_WIDTH_MISMATCH')['category'] == 'file_input'
    assert 'input_header_row' in classify('CSV_ROW_WIDTH_MISMATCH')['hint']
    assert classify('LLM_TIMEOUT')['category'] == 'model_service'
    assert classify('PLANNER_SCHEMA_INVALID')['category'] == 'model_output'
    assert classify('NO_EXECUTABLE_TASKS')['category'] == 'plan_blocked'
    assert classify('PROCESS_INTERRUPTED')['category'] == 'interrupted'
    assert classify('SOMETHING_NEW')['category'] == 'unclassified'
    assert classify(None)['category'] == 'unclassified'
    assert set(CATEGORIES) >= {classify(c)['category'] for c in ('EMPTY_HEADER', 'SCOPE_NO_MATCHES', 'REPORT_CAPACITY_EXCEEDED')}


def test_first_failure_prefers_earliest_node_then_business_then_report():
    nodes = [
        {'span_id': 's2', 'name': 'analysis_planner', 'status': 'failed', 'started_at': '2026-01-01T00:00:02', 'error_code': 'LLM_TIMEOUT', 'attributes': {}},
        {'span_id': 's1', 'name': 'data_profiler', 'status': 'complete', 'started_at': '2026-01-01T00:00:01', 'attributes': {}},
        {'span_id': 's3', 'name': 'intent_parser', 'status': 'failed', 'started_at': '2026-01-01T00:00:01.5', 'error_code': 'LLM_INVALID_JSON',
         'attributes': {'input_query_chars': 12, 'node_name': 'intent_parser'}},
    ]
    found = first_failure(nodes, 'PROCESS_INTERRUPTED', 'REPORT_LLM_CALL_FAILED')
    assert (found['span_id'], found['category'], found['source']) == ('s3', 'model_output', 'node')
    assert found['inputs'] == {'input_query_chars': 12}
    assert first_failure([], 'PROCESS_INTERRUPTED')['source'] == 'business'
    assert first_failure([], None, 'REPORT_LLM_CALL_FAILED')['source'] == 'report_generation'
    assert first_failure(nodes[1:2]) is None


def wait_terminal(client, session_id):
    for _ in range(100):
        state = client.get('/api/v1/sessions/' + session_id).json()
        if state['status'] in {'FAILED', 'AWAITING_APPROVAL', 'WAITING_FOR_CLARIFICATION'}:
            return state
        time.sleep(0.02)
    raise AssertionError(state['status'])


def test_profiler_parse_failure_is_attributed_with_input_parameters(tmp_path):
    app = application(tmp_path)
    with TestClient(app) as client:
        response = client.post('/api/v1/sessions', data={'goal': '保密的分析需求', 'real_workflow': 'true', 'header_row': '9'},
                               files={'file': ('客户名单.csv', b'a,b\n1,2\n')})
        assert response.status_code == 201, response.text
        client.headers['X-Session-Token'] = response.json()['review_access_token']
        state = wait_terminal(client, response.json()['id'])
        assert state['status'] == 'FAILED'
        detail = client.get('/admin/workflow-observability/' + state['workflow_id'], headers=AUTH).json()
        failure = detail['failure']
        assert failure['category'] == 'file_input' and failure['source'] == 'node'
        assert failure['node_name'] == 'data_profiler' and failure['code'] == state['error']['code']
        assert failure['inputs']['input_header_row'] == 9
        assert failure['inputs']['input_file_extension'] == '.csv' and failure['inputs']['input_file_size_bytes'] == 8
        dumped = json.dumps(detail, ensure_ascii=False)
        assert '客户名单' not in dumped and '保密的分析需求' not in dumped
        base = '/admin/workflow-observability?failure_category='
        assert client.get(base + 'file_input', headers=AUTH).json()['total'] == 1
        assert client.get(base + 'model_output', headers=AUTH).json()['total'] == 0
        assert client.get(base + 'imaginary', headers=AUTH).status_code == 422


def test_success_has_no_failure_and_records_inputs_without_user_text(tmp_path):
    app = application(tmp_path)
    with TestClient(app) as client:
        _, _, session = run(client)
        detail = client.get('/admin/workflow-observability/' + session['workflow_id'], headers=AUTH).json()
        assert detail['failure'] is None
        nodes = {n['name']: n['attributes'] for n in detail['trace']['nodes']}
        assert nodes['data_profiler']['input_header_row'] == 1
        assert nodes['intent_parser']['input_query_chars'] == len(session['user_goal'])
        assert nodes['analysis_planner']['input_field_count'] > 0
        assert session['user_goal'] not in json.dumps(detail, ensure_ascii=False)


def test_report_model_timeout_is_attributed_to_model_service(tmp_path):
    from test_report_workflow import Provider
    from app.domain.errors import AppError
    app = application(tmp_path, Provider(report_error=AppError('LLM_TIMEOUT', 'unit timeout', 504)))
    with TestClient(app) as client:
        _, _, session = run(client)
        failure = client.get('/admin/workflow-observability/' + session['workflow_id'], headers=AUTH).json()['failure']
        assert failure is not None and failure['category'] == 'model_service', failure
