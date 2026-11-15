"""Manual Bad Case annotation: separate write token, frozen evidence, append-only status history."""
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from test_report_workflow import Provider, run
from test_trace_closure_c2 import AUTH, http_provider

WRITE = {**AUTH, 'X-Admin-Annotation-Token': 'note'}


def application(path, annotation_token='note'):
    provider, _ = http_provider(Provider())
    return create_app(Settings(path, admin_read_token='read', admin_annotation_token=annotation_token), provider)


def body(workflow_id, **extra):
    return {'workflow_id': workflow_id, 'category': 'insight', 'severity': 'high', 'title': '结论与数据不符',
            'observed': '报告称华东增长最快，但数据显示华南更高。', 'expected': '应指出华南增长最快。', 'annotator': 'lainey', **extra}


def test_create_freezes_evidence_and_lists_by_workflow(tmp_path):
    with TestClient(application(tmp_path)) as client:
        _, _, session = run(client)
        workflow = client.get('/admin/workflow-observability/' + session['workflow_id'], headers=AUTH).json()
        node = next(n for n in workflow['trace']['nodes'] if n['name'] == 'insight_generator')
        response = client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'], span_id=node['span_id']))
        assert response.status_code == 201, response.text
        case = response.json()
        assert case['status'] == 'open' and case['sequence'] == 1 and case['evidence_intact'] is True
        assert case['node_name'] == 'insight_generator' and case['created_by'] == 'lainey'
        evidence = case['evidence']
        assert evidence['business_lifecycle'] == workflow['business_lifecycle']
        assert evidence['quality'] == workflow['quality']
        assert {n['span_id'] for n in evidence['nodes']} == {n['span_id'] for n in workflow['trace']['nodes']}
        refs = evidence['replay_refs']
        assert refs['session_id'] == session['id'] and refs['execution_id'] and refs['dataset_version']
        assert refs['llm_call_ids'] and all(c['call_id'] in refs['llm_call_ids'] for c in evidence['llm_calls'])
        dumped = json.dumps(evidence, ensure_ascii=False)
        assert session['user_goal'] not in dumped and 'error_message' not in dumped
        page = client.get('/admin/bad-cases?workflow_id=' + session['workflow_id'], headers=AUTH).json()
        assert page['total'] == 1 and page['items'][0]['case_id'] == case['case_id']
        assert page['items'][0]['business_status'] == workflow['business_lifecycle']['status']
        assert client.get('/admin/bad-cases?workflow_id=wf_other', headers=AUTH).json()['total'] == 0


def test_write_requires_annotation_token_and_valid_references(tmp_path):
    with TestClient(application(tmp_path)) as client:
        _, _, session = run(client)
        assert client.post('/admin/bad-cases', headers=AUTH, json=body(session['workflow_id'])).status_code == 403
        assert client.post('/admin/bad-cases', json=body(session['workflow_id']), headers={'X-Admin-Annotation-Token': 'note'}).status_code == 403
        assert client.post('/admin/bad-cases', headers=WRITE, json=body('wf_missing')).status_code == 404
        assert client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'], span_id='span_other')).status_code == 422
        assert client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'], category='guess')).status_code == 422
        assert client.post('/admin/bad-cases', headers=WRITE, json={**body(session['workflow_id']), 'status': 'fixed'}).status_code == 422
        assert client.get('/admin/bad-cases', headers=AUTH).json()['total'] == 0


def test_unconfigured_annotation_token_keeps_admin_read_only(tmp_path):
    with TestClient(application(tmp_path, annotation_token='')) as client:
        _, _, session = run(client)
        response = client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id']))
        assert response.status_code == 503 and response.json()['error']['code'] == 'ANNOTATION_NOT_CONFIGURED'


def test_status_history_is_append_only_with_optimistic_concurrency(tmp_path):
    app = application(tmp_path)
    with TestClient(app) as client:
        _, _, session = run(client)
        case = client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'])).json()
        url = '/admin/bad-cases/' + case['case_id'] + '/events'
        confirmed = client.post(url, headers=WRITE, json={'status': 'confirmed', 'note': '复核属实', 'annotator': 'reviewer', 'expected_sequence': 1})
        assert confirmed.status_code == 201 and confirmed.json()['status'] == 'confirmed'
        stale = client.post(url, headers=WRITE, json={'status': 'fixed', 'annotator': 'reviewer', 'expected_sequence': 1})
        assert stale.status_code == 409 and stale.json()['error']['code'] == 'BAD_CASE_STALE'
        same = client.post(url, headers=WRITE, json={'status': 'confirmed', 'annotator': 'reviewer', 'expected_sequence': 2})
        assert same.status_code == 422
        noted = client.post(url, headers=WRITE, json={'status': 'confirmed', 'note': '补充：仅在季度视图出现', 'annotator': 'reviewer', 'expected_sequence': 2}).json()
        assert [e['kind'] for e in noted['events']] == ['created', 'status_changed', 'note']
        assert [e['status'] for e in noted['events']] == ['open', 'confirmed', 'confirmed']
        assert client.get('/admin/bad-cases?status=confirmed', headers=AUTH).json()['total'] == 1
        assert client.get('/admin/bad-cases?status=open', headers=AUTH).json()['total'] == 0
        assert client.post('/admin/bad-cases/bc_missing/events', headers=WRITE,
                           json={'status': 'fixed', 'annotator': 'x', 'expected_sequence': 1}).status_code == 404
        path = app.state.bad_cases.repository.path
        conn = sqlite3.connect(path)
        for sql in ('UPDATE bad_cases SET record=1', 'DELETE FROM bad_cases', 'UPDATE bad_case_events SET record=1', 'DELETE FROM bad_case_events'):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)
        conn.close()


def test_tampered_evidence_is_reported(tmp_path):
    app = application(tmp_path)
    with TestClient(app) as client:
        _, _, session = run(client)
        case = client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'])).json()
        conn = sqlite3.connect(app.state.bad_cases.repository.path)
        conn.execute('DROP TRIGGER bad_cases_no_update')
        record = json.loads(conn.execute('SELECT record FROM bad_cases').fetchone()[0])
        record['evidence']['business_lifecycle']['status'] = 'succeeded_forged'
        conn.execute('UPDATE bad_cases SET record=?', (json.dumps(record),))
        conn.commit(); conn.close()
        assert client.get('/admin/bad-cases/' + case['case_id'], headers=AUTH).json()['evidence_intact'] is False
