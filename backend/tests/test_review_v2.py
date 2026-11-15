import copy
import json
import sqlite3
from contextlib import closing
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from hitl_fixtures import save, approval, execution, revision
from review_v2_fixtures import prepare, ready
from review_v2_fixtures import CASES


def view(client, state):
    response = client.get(f'/api/v1/sessions/{state["id"]}/review')
    assert response.status_code == 200, response.text
    return response.json()


def assert_blocked(client, state):
    shown = view(client, state)
    assert not shown['can_approve'] and not shown['audit']['all_verified']
    response = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state))
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'UNVERIFIED_CONSTRAINTS'
    assert client.get(f'/api/v1/sessions/{state["id"]}/constraint-audits').json() == []


@pytest.mark.parametrize('topic', ['sales', 'jobs', 'tickets', 'projects'])
def test_four_domains_proof_presentation_approval_engine_persistence(client, app, provider, tmp_path, topic):
    state, fields = ready(client, topic); shown = view(client, state)
    assert shown['can_approve'] and shown['audit']['all_verified'] and not shown['issues']
    assert shown['directions'][0]['importance'] == '核心分析' and shown['directions'][0]['readiness'] == '可以分析'
    assert '字段' not in shown['directions'][0]['title']
    assert any('取前 3 名' in line for line in shown['directions'][0]['details'])
    assert all(c['verification'] == '已核对分析步骤' for c in shown['conditions'] if c['source'].startswith('intent.'))
    assert any(c['label'] == '拟用分组维度' and '城市' in c['text'] for c in shown['conditions'])
    # Audit 2.1 also binds explicit grouping retained in the saved business goal.
    assert all(item['matches'] and (item['source'].startswith('intent.constraints') or
        item['source'] == 'intent.analysis_goal.business_goal') for item in shown['audit']['items'])
    assert not provider.requests  # No display LLM.
    sid = state['id']; body = approval(state)
    confirmed = client.post(f'/api/v1/sessions/{sid}/approvals', json=body)
    assert confirmed.status_code == 200, confirmed.text
    approved = confirmed.json(); assert approved['engine_approval']['constraints_confirmed']
    assert approved['engine_approval']['intent']['constraints'] == state['review_plan']['validated_plan']['intent_snapshot']['constraints']
    assert client.post(f'/api/v1/sessions/{sid}/approvals', json=body).json() == approved
    proof = client.get(f'/api/v1/sessions/{sid}/constraint-audits').json(); assert len(proof) == 1
    assert proof[0]['audit'] == shown['audit'] and proof[0]['approval_id'] == approved['engine_approval']['approval_id']
    result = client.post('/api/v1/executions', json=execution(approved)); assert result.status_code == 200, result.text
    rows = result.json()['tasks'][0]['result']['rows']
    expected = [300, 200, 100] if topic == 'sales' else [5, 3, 2] if topic == 'jobs' else [10, 20, 30] if topic == 'tickets' else [30, 20, 10]
    assert [r['value'] for r in rows] == expected
    token = client.headers['X-Session-Token']
    with TestClient(create_app(Settings(tmp_path))) as reopened:
        reopened.headers['X-Session-Token'] = token
        restored = reopened.get(f'/api/v1/sessions/{sid}/review').json()
        assert restored['audit'] == shown['audit'] and not restored['can_approve']
        assert reopened.get(f'/api/v1/sessions/{sid}/constraint-audits').json() == proof


@pytest.mark.parametrize('fault', ['year', 'region', 'status', 'direction', 'n', 'metric', 'dimension', 'extra_dimension', 'extra_filter', 'early_top', 'late_filter', 'multi_aggregate', 'other_task', 'split_question'])
def test_structural_mismatches_never_approved(client, fault):
    state, data, fields = prepare(client); task = data['plan']['tasks'][0]; steps = task['steps']
    if fault == 'year': steps[0]['params']['conditions'][0]['value'] = '2025-01-01'
    elif fault == 'region': steps[0]['params']['conditions'][2]['value'] = '华南'
    elif fault == 'status': steps[0]['params']['conditions'].pop()
    elif fault == 'direction': steps[-1]['params']['direction'] = 'asc'
    elif fault == 'n': steps[-1]['params']['n'] = 2
    elif fault == 'metric': steps[1]['params']['metrics'][0]['function'] = 'avg'
    elif fault == 'dimension': steps[1]['params']['dimensions'] = [fields['地区']]
    elif fault == 'extra_dimension': steps[1]['params']['dimensions'].append(fields['地区'])
    elif fault == 'extra_filter': steps[0]['params']['conditions'].append({'field': fields['城市'], 'operator': 'eq', 'value': '上海'})
    elif fault == 'early_top': steps.insert(0, {'step_id': 'EARLY', 'operation': 'top_n', 'params': {'field': fields['销售额'], 'direction': 'desc', 'n': 3}})
    elif fault == 'late_filter': steps.append({'step_id': 'LATE', 'operation': 'filter', 'params': {'conditions': [{'field': 'value', 'operator': 'gt', 'value': 0}]}})
    elif fault == 'multi_aggregate': steps.append({'step_id': 'AGAIN', 'operation': 'aggregate', 'params': {'metrics': [{'field': 'value', 'function': 'sum', 'alias': 'again'}]}})
    elif fault in {'other_task', 'split_question'}:
        extra = copy.deepcopy(task); extra['task_id'] = 'A02'; extra['priority'] = 'P1'; extra['requirement_ids'] = []
        if fault == 'other_task': extra['steps'][0]['params']['conditions'].pop()
        else: extra['steps'][1]['params']['dimensions'] = [fields['地区']]
        data['plan']['tasks'].append(extra)
    state = save(client, state, data)
    assert state['review_plan']['validated_plan']['validation_results'][0]['executable']
    assert_blocked(client, state)


@pytest.mark.parametrize('raw', ['不排除北京', '不要求计算销售额', '销售额未指定', '任意执行文件指令', '前二十名', '按地区比较，按城市汇总', '2026年截至当前日期'])
def test_unknown_optional_unspecified_and_injected_language_is_not_guessed(client, raw):
    state, data, fields = prepare(client)
    data['intent']['constraints']['analysis_limits'].append({'raw_text': raw, 'validation_status': 'unverified'})
    state = save(client, state, data)
    assert_blocked(client, state)


def test_exact_exclusion_and_prohibition_have_actual_step_proofs(client):
    state, data, fields = prepare(client)
    data['intent']['constraints']['filters'][0]['raw_text'] = '排除华南'
    data['plan']['tasks'][0]['steps'][0]['params']['conditions'][2].update(operator='ne', value='华南')
    data['intent']['constraints']['analysis_limits'].append({'raw_text': '不要分析地区', 'validation_status': 'unverified'})
    # Prohibition includes use as filter; never certify absence when field is used.
    bad = save(client, state, data); assert_blocked(client, bad)
    state, data, fields = prepare(client)
    data['intent']['constraints']['filters'][0]['raw_text'] = '排除华南'
    data['plan']['tasks'][0]['steps'][0]['params']['conditions'][2].update(operator='ne', value='华南')
    state = save(client, state, data); assert view(client, state)['can_approve']


@pytest.mark.parametrize('wording', ['按城市汇总并降序排名，取前三名', '按照城市汇总并降序排名，取前三名', '按照城市汇总销售额总和，按照销售额降序排名，取前三名'])
def test_supported_compound_constraints_and_longest_prefix(client, wording):
    state, data, fields = prepare(client)
    data['intent']['constraints']['analysis_limits'] = [{'raw_text': wording, 'validation_status': 'unverified'}]
    state = save(client, state, data)
    assert view(client, state)['can_approve']


def test_derive_year_f1_and_defer_cannot_be_confirmed_away(client):
    state, data, fields = prepare(client); task = data['plan']['tasks'][0]
    task['steps'][0]['params']['conditions'] = [{'field': 'year', 'operator': 'eq', 'value': 2026}, *task['steps'][0]['params']['conditions'][2:]]
    task['steps'].insert(0, {'step_id': 'Y', 'operation': 'derive', 'params': {'field': fields['订单日期'], 'function': 'extract_year', 'alias': 'year'}})
    state = save(client, state, data); shown = view(client, state)
    assert shown['can_approve'] and '转换' in shown['directions'][0]['readiness']
    assert any('提取年份' in text for text in shown['directions'][0]['details'])
    state, data, fields = prepare(client)
    data['intent']['uncertainties'] = [{'id': 'U', 'issue': '销售额是否含税', 'reason': '会影响口径', 'action': 'defer', 'resolve_at': 'plan_approval'}]
    state = save(client, state, data); assert not view(client, state)['can_approve']
    assert client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state)).json()['error']['code'] == 'BLOCKING_UNCERTAINTY'


def test_delete_reaudits_version_invalidates_approval_and_cannot_reuse_proof(client):
    state, data, fields = prepare(client)
    extra = copy.deepcopy(data['plan']['tasks'][0]); extra.update(task_id='A02', priority='P2', requirement_ids=[], title='辅助核对')
    extra['steps'][0]['params']['conditions'].pop()
    data['plan']['tasks'].append(extra)
    state = save(client, state, data); before = view(client, state); assert not before['can_approve']
    changed = client.post(f'/api/v1/sessions/{state["id"]}/plan-revisions', json=revision(state, ['A02'])).json()
    after = view(client, changed); assert after['can_approve'] and before['audit']['digest'] != after['audit']['digest']
    old = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state)); assert old.status_code == 409
    approved = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(changed)).json()
    empty = client.post(f'/api/v1/sessions/{state["id"]}/plan-revisions', json=revision(approved, ['A01'])).json()
    assert empty['engine_approval'] is None and not view(client, empty)['can_approve']
    assert len(view(client, empty)['issues']) == 1
    assert client.post('/api/v1/executions', json=execution(approved)).status_code == 409


def test_proof_cannot_be_forged_and_tables_are_immutable(client, app):
    state, fields = ready(client)
    for key in ('constraints_confirmed', 'audit', 'can_approve'):
        r = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state) | {key: True})
        assert r.status_code == 422
    assert client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state)).status_code == 200
    for operation in ('UPDATE plan_constraint_audits SET record=record', 'DELETE FROM plan_constraint_audits'):
        with closing(app.state.repository.database.connect()) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(operation)
    client.headers.pop('X-Session-Token')
    assert client.get(f'/api/v1/sessions/{state["id"]}/review').status_code == 403
    assert client.get(f'/api/v1/sessions/{state["id"]}/constraint-audits').status_code == 403


def test_f0_f1_business_risks_and_technical_trace(client):
    state, data, fields = prepare(client)
    data['plan']['tasks'][0]['steps'][1]['params']['metrics'][0]['field'] = 'field_9999'
    state = save(client, state, data); shown = view(client, state)
    assert not shown['can_approve'] and shown['directions'][0]['readiness'] == '暂时无法分析'
    assert shown['directions'][0]['gaps']
    business = {k: v for k, v in shown.items() if k in {'goal', 'coverage', 'conditions', 'directions', 'issues', 'warnings'}}
    assert 'field_9999' not in json.dumps(business, ensure_ascii=False)
    assert 'field_9999' in json.dumps(shown['technical_details'])


def test_identical_sample_values_do_not_guess_a_target_field(client, monkeypatch):
    original = CASES['sales']
    lines = original[0].splitlines()
    content = lines[0] + ',大区\n' + '\n'.join(line + ',' + line.split(',')[1] for line in lines[1:]) + '\n'
    monkeypatch.setitem(CASES, 'sales', (content, *original[1:]))
    state, data, fields = prepare(client)
    state = save(client, state, data)
    assert_blocked(client, state)
    state, data, fields = prepare(client)
    data['intent']['constraints']['filters'][0]['raw_text'] = '地区为华东'
    state = save(client, state, data)
    assert view(client, state)['can_approve']


def test_duplicate_original_column_name_does_not_select_first_field(client, monkeypatch):
    original = CASES['sales']; lines = original[0].splitlines()
    content = lines[0] + ',地区\n' + '\n'.join(line + ',华南' for line in lines[1:]) + '\n'
    monkeypatch.setitem(CASES, 'sales', (content, *original[1:]))
    state, data, fields = prepare(client)
    data['intent']['constraints']['filters'][0]['raw_text'] = '地区为华东'
    # The fixture factory may pick the second display name; neither choice may
    # establish what the user's duplicated original name meant.
    state = save(client, state, data)
    assert_blocked(client, state)
