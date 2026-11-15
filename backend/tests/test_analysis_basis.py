"""Business declarations never override actual functions, approval or plan fencing."""
import json
import sqlite3
from contextlib import closing
import pytest
from app.review.analysis_basis import load
from hitl_fixtures import create, save, approval, execution, revision


def body(state, grain='record', entity=None):
    record = state['review_plan']
    return {'expected_revision':state['revision'],'plan_id':record['plan_id'],'plan_version':record['plan_version'],
            'row_grain':grain,'entity_field_id':entity}


def change(client,state,grain='record',entity=None):
    return client.post(f'/api/v1/sessions/{state["id"]}/analysis-basis',json=body(state,grain,entity))


def test_definitions_are_real_plan_operations_and_unknown_grain_stays_unknown(client,app):
    state=save(client,create(client))
    basis=client.get(f'/api/v1/sessions/{state["id"]}/review').json()['analysis_basis']
    assert basis['row_grain']=='unknown' and basis['declaration_source']=='unconfirmed'
    actual={(t['task_id'],s['step_id'],m['alias'],m['function'],m.get('field'))
        for t in state['review_plan']['validated_plan']['plan']['tasks'] for s in t['steps']
        for m in s['params'].get('metrics',[])}
    assert {(m['task_id'],m['step_id'],m['alias'],m['function'],m['field_id']) for m in basis['metrics']}==actual
    assert any('逐行计数' in m['basis'] for m in basis['metrics'])


def test_change_creates_version_clears_approval_and_execution_carries_exact_basis(client,app):
    state=save(client,create(client)); sid=state['id']
    old=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    response=change(client,old,'detail'); assert response.status_code==200,response.text
    current=response.json(); assert current['current_plan_version']==2
    assert current['engine_approval'] is None and current['approved_plan_version'] is None
    assert client.get(f'/api/v1/sessions/{sid}/plans/1').json()==state['review_plan']
    assert client.post('/api/v1/executions',json=execution(old)).status_code==409
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(current,request_id='basis-v2')).json()
    output=client.post('/api/v1/executions',json=execution(approved)).json()
    assert output['execution_status']=='success',output
    with closing(app.state.repository.database.connect()) as conn:
        expected=load(conn,sid,2)
        stored=json.loads(conn.execute('SELECT record FROM approval_analysis_bases WHERE approval_id=?',(approved['engine_approval']['approval_id'],)).fetchone()[0])
    assert stored==expected
    for task in output['tasks']:
        if task.get('execution_metadata'):
            basis=task['execution_metadata']['analysis_basis']
            assert basis['row_grain']=='detail' and basis['digest']==expected['digest'] and basis['plan_version']==2
            assert all(m['task_id']==task['task_id'] for m in basis['metrics'])
    assert change(client,approved).status_code==409


def test_duplicate_entity_identifier_is_rejected_atomically(client,app):
    state=save(client,create(client)); sid=state['id']
    option=next(field for field in state['profile']['fields'] if field['unique_count']<state['profile']['row_count'])
    response=change(client,state,'entity',option['field_id'])
    assert response.status_code==422 and response.json()['error']['code']=='ENTITY_GRAIN_NOT_VERIFIED'
    assert client.get(f'/api/v1/sessions/{sid}').json()==state
    assert len(client.get(f'/api/v1/sessions/{sid}/plans').json())==1


def test_unique_entity_identifier_and_task_deletion_preserve_declaration(client,app):
    from hitl_fixtures import ROOT, GOAL
    lines=(ROOT/'examples/sales.csv').read_text().strip().splitlines()
    source='\n'.join([lines[0]+',entity_key', *[line+','+str(i) for i,line in enumerate(lines[1:],1)]])+'\n'
    response=client.post('/api/v1/sessions',data={'goal':GOAL,'manual_review':'true'},files={'file':('records.csv',source.encode(),'text/csv')})
    initial=response.json(); client.headers['X-Session-Token']=initial.pop('review_access_token')
    state=save(client,initial); sid=state['id']
    field=next(f for f in state['profile']['fields'] if f['unique_count']==state['profile']['row_count'] and not f['missing_count'])
    response=change(client,state,'entity',field['field_id']); assert response.status_code==200,response.text
    current=response.json()
    current=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(current,['A03'])).json()
    view=client.get(f'/api/v1/sessions/{sid}/review').json()
    assert view['analysis_basis']['row_grain']=='entity'
    assert view['analysis_basis']['entity_field_id']==field['field_id']
    assert all(m['task_id']!='A03' for m in view['analysis_basis']['metrics'])


def test_invalid_grain_entity_pair_and_stale_revision_cannot_change_plan(client):
    state=save(client,create(client))
    assert change(client,state,'record','field_0001').status_code==422
    first=change(client,state).json()
    stale=change(client,state)
    assert stale.status_code==409 and stale.json()['error']['code']=='STALE_SESSION'
    assert client.get(f'/api/v1/sessions/{state["id"]}').json()==first


def test_basis_tables_are_immutable_and_approval_link_is_required(client,app):
    state=save(client,create(client)); sid=state['id']
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    with closing(app.state.repository.database.connect()) as conn:
        for table in ('plan_analysis_bases','approval_analysis_bases'):
            for statement in (f'DELETE FROM {table}',f'UPDATE {table} SET record=record'):
                with pytest.raises(sqlite3.IntegrityError): conn.execute(statement)
        # Fault injection: do not weaken the production immutable trigger.
        conn.execute('DROP TRIGGER approval_analysis_bases_no_delete')
        conn.execute('DELETE FROM approval_analysis_bases'); conn.commit()
    response=client.post('/api/v1/executions',json=execution(approved))
    assert response.status_code==409 and response.json()['error']['code']=='ANALYSIS_BASIS_MISMATCH'


def test_existing_uncertainty_is_not_resolved_by_grain_declaration(client):
    from hitl_fixtures import candidate
    state=create(client); data=candidate(state)
    data['intent']['uncertainties']=[{'id':'U1','description':'需确认均值或中位数','impact':'影响比较','action':'defer','resolve_at':'plan_approval'}]
    state=save(client,state,data); state=change(client,state).json()
    response=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state))
    assert response.status_code==409 and response.json()['error']['code']=='BLOCKING_UNCERTAINTY'


@pytest.mark.parametrize('headers',[
    ('记录编号','区域','交易金额'),('岗位编号','城市','薪资'),
    ('工单编号','类别','处理分钟'),('任务编号','项目','工时')])
def test_four_domains_use_actual_fields_and_same_generic_contract(client,headers):
    from planning_fixtures import plan,task,step
    from intent_fixtures import intent_payload
    from app.domain.dataset_profile import DatasetProfile
    goal=f'按{headers[1]}统计{headers[2]}合计'
    source=(','.join(headers)+'\n1,A,10\n2,A,20\n3,B,30\n').encode()
    response=client.post('/api/v1/sessions',data={'goal':goal,'manual_review':'true'},files={'file':('business.csv',source,'text/csv')})
    state=response.json();client.headers['X-Session-Token']=state.pop('review_access_token')
    candidate=plan([task([step('group_aggregate',{'dimensions':['field_0002'],'metrics':[{'function':'sum','field':'field_0003','alias':'total'}]})])],DatasetProfile.model_validate(state['profile']))
    data={'plan':candidate,'intent':intent_payload(business_goal=goal)}
    state=save(client,state,data)
    changed=change(client,state,'entity','field_0001');assert changed.status_code==200,changed.text
    state=changed.json()
    basis=client.get(f'/api/v1/sessions/{state["id"]}/review').json()['analysis_basis']
    assert basis['metrics'][0]['label']==headers[2]
    assert basis['metrics'][0]['function']=='sum'
    assert basis['entity_field_id']=='field_0001'
