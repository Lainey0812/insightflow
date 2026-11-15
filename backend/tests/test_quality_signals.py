"""Quality signals on the Admin workflow detail: derived only from collected evidence."""
from fastapi.testclient import TestClient
from test_trace_closure_c2 import application, AUTH
from test_report_workflow import run
from app.observability.quality import STAGES, quality_signals


def node(name, **attributes):
    return {'name': name, 'attributes': attributes}


def by_key(result):
    return {s['key']: s for s in result['signals']}


def test_missing_evidence_is_unavailable_not_zero():
    result = quality_signals([], [], {})
    assert all(s['level'] == 'unavailable' and s['value'] is None for s in result['signals'])
    assert result['attention_count'] == 0 and result['unavailable_count'] == len(result['signals'])
    assert {s['stage'] for s in result['signals']} <= set(STAGES)


def test_attention_levels_follow_collected_values():
    nodes = [
        node('intent_parser', next_action='clarify'), node('intent_parser', next_action='proceed'),
        node('analysis_planner', coverage_status='partial', blocked_count=1, executable_count=2),
        node('plan_validator', f0_count=1, f1_count=2, f2_count=0, unmet_core_count=0),
        node('hitl', command='revise'), node('hitl', command='approve'),
        node('analysis_engine', execution_status='success'),
        node('fact_validator', report_attempt=1, candidate_count=4, rejected_count=3),
        node('fact_validator', report_attempt=2, candidate_count=3, rejected_count=1),
        node('report_persistence', report_attempt=2),
    ]
    calls = [{'retry_index': 0, 'status': 'succeeded'}, {'retry_index': 1, 'status': 'failed'}]
    business = {'execution_status': 'success', 'report_status': 'partial', 'goal_coverage': 'complete'}
    signals = by_key(quality_signals(nodes, calls, business, [{'accepted_report_attempt': 2}]))
    assert signals['clarification_rounds'] == {**signals['clarification_rounds'], 'value': 1, 'level': 'attention'}
    assert signals['planner_coverage']['level'] == 'attention' and signals['planner_blocked_tasks']['value'] == 1
    assert signals['f0_count']['level'] == 'attention'
    assert signals['f1_count']['value'] == 2 and signals['f1_count']['level'] == 'normal'
    assert signals['unmet_core_count']['level'] == 'normal'
    assert signals['hitl_revisions']['value'] == 1
    assert signals['execution_status']['level'] == 'normal'
    assert (signals['insight_candidates']['value'], signals['insight_rejected']['value']) == (3, 1)
    assert signals['report_attempts']['value'] == 2 and signals['report_attempts']['level'] == 'attention'
    assert signals['report_status']['level'] == 'attention' and signals['goal_coverage']['level'] == 'normal'
    assert (signals['llm_retries']['value'], signals['llm_failed_calls']['value']) == (1, 1)


def test_old_validator_spans_without_counts_stay_unavailable():
    signals = by_key(quality_signals([node('plan_validator', coverage_status='complete', executable_count=3)], [], {}))
    assert signals['f0_count']['level'] == 'unavailable' and '未采集' in signals['f0_count']['note']


def test_workflow_detail_exposes_quality_signals(tmp_path):
    app = application(tmp_path)
    with TestClient(app) as client:
        _, _, session = run(client)
        detail = client.get('/admin/workflow-observability/' + session['workflow_id'], headers=AUTH).json()
        signals = by_key(detail['quality'])
        validator = [n['attributes'] for n in detail['trace']['nodes'] if n['name'] == 'plan_validator']
        assert validator and all({'f0_count', 'f1_count', 'f2_count', 'unmet_core_count'} <= set(v) for v in validator)
        assert signals['f0_count']['level'] != 'unavailable'
        assert signals['execution_status']['value'] == detail['business_lifecycle']['execution_status']
        assert signals['report_status']['value'] == detail['business_lifecycle']['report_status']
        assert signals['llm_failed_calls']['value'] == 0
        listed = client.get('/admin/workflow-observability', headers=AUTH).json()['items'][0]
        assert listed['quality']['attention_count'] == detail['quality']['attention_count']
