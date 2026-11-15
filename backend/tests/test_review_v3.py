"""Review changes preserve original constraints and require a new server approval."""
import copy
import pytest
from hitl_fixtures import create, save, approval, execution, revision


def edit(state, task_id, params):
    return {**revision(state, []), 'task_edits':[{'task_id':task_id,'step_params':params}]}


def test_actual_overview_uses_profile_units_without_claiming_cleaning(client):
    state=save(client,create(client))
    view=client.get(f'/api/v1/sessions/{state["id"]}/review').json()
    overview=view['data_overview']; p=state['profile']
    for field in ['row_count','column_count','missing_cell_count','duplicate_row_count','dataset_id','dataset_version']:
        assert overview[field]==p[field]
    assert overview['cleaning_status']=='not_performed'
    assert 'invalid_row_count' not in overview and 'valid_row_count' not in overview
    assert '未自动' in overview['cleaning_notice']


def test_edit_creates_new_version_revalidates_clears_approval_and_preserves_intent(client):
    state=save(client,create(client));sid=state['id']
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    task=next(t for t in state['review_plan']['validated_plan']['plan']['tasks'] if t['task_id']=='A03')
    step=task['steps'][0];params=copy.deepcopy(step['params']);params['metrics'][0]['function']='avg'
    r=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=edit(approved,'A03',{step['step_id']:params}))
    assert r.status_code==200,r.text
    current=r.json(); assert current['current_plan_version']==2 and current['engine_approval'] is None
    assert current['review_plan']['change_type']=='tasks_edited'
    assert current['review_plan']['validated_plan']['intent_snapshot']==state['review_plan']['validated_plan']['intent_snapshot']
    assert client.get(f'/api/v1/sessions/{sid}/plans/1').json()==state['review_plan']
    assert client.post('/api/v1/executions',json=execution(approved)).status_code==409
    response=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(current,request_id='new-version'))
    assert response.status_code==200,response.text


def test_invalid_type_edit_keeps_task_f0_and_cannot_silently_execute(client):
    state=save(client,create(client));sid=state['id']
    task=next(t for t in state['review_plan']['validated_plan']['plan']['tasks'] if t['task_id']=='A02')
    step=task['steps'][0];p=copy.deepcopy(step['params']);p['metrics'][0]['field']='field_0002'
    # Select a real text field rather than guessing a field's type by its position.
    p['metrics'][0]['field']=next(f['field_id'] for f in state['profile']['fields'] if f['logical_type']=='text')
    r=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=edit(state,'A02',{step['step_id']:p}))
    assert r.status_code==200,r.text
    current=r.json();checked=current['review_plan']['validated_plan']
    result=next(v for v in checked['validation_results'] if v['task_id']=='A02')
    assert not result['executable'] and result['reason_code']=='TYPE_MISMATCH'
    assert any(t['task_id']=='A02' for t in checked['plan']['tasks'])
    assert checked['unmet_core_requirements']


def test_stale_edit_and_running_edit_rejected_without_new_versions(client):
    state=save(client,create(client));sid=state['id']
    task=state['review_plan']['validated_plan']['plan']['tasks'][0]
    step=task['steps'][0];p=copy.deepcopy(step['params'])
    # A nonexistent step is rejected before any plan write.
    request=edit(state,task['task_id'],{'unknown':p})
    assert client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=request).status_code==422
    current=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,['A03'])).json()
    assert client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,['A01'])).status_code==409
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(current)).json()
    output=client.post('/api/v1/executions',json=execution(approved));assert output.status_code==200,output.text
    completed=client.get(f'/api/v1/sessions/{sid}').json()
    assert client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=edit(completed,task['task_id'],{step['step_id']:p})).status_code==409
    assert len(client.get(f'/api/v1/sessions/{sid}/plans').json())==2


def test_schema_error_is_atomic_and_cross_task_conflicts_rejected(client):
    state=save(client,create(client));sid=state['id']
    task=state['review_plan']['validated_plan']['plan']['tasks'][0]; step=task['steps'][0]
    bad=edit(state,task['task_id'],{step['step_id']:{'python':'print(1)'}})
    assert client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=bad).status_code==422
    bad=edit(state,task['task_id'],{step['step_id']:step['params']});bad['remove_task_ids']=[task['task_id']]
    assert client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=bad).status_code==422
    assert client.get(f'/api/v1/sessions/{sid}').json()==state


def test_edit_cannot_erase_or_acknowledge_away_original_constraints(client):
    from hitl_fixtures import candidate
    state=create(client);data=candidate(state)
    data['intent']['constraints']['metric_requirements']=[{'raw_text':'总销售额','validation_status':'unverified'}]
    state=save(client,state,data);sid=state['id']
    edits=[]
    for t in state['review_plan']['validated_plan']['plan']['tasks']:
        params={}
        for step in t['steps']:
            if step['operation'] in {'aggregate','group_aggregate'}:
                p=copy.deepcopy(step['params'])
                for m in p['metrics']:
                    m['function']='avg'
                    m['field']=next(f['field_id'] for f in state['profile']['fields'] if f['logical_type'] in {'integer','number'})
                params[step['step_id']]=p
        if params:edits.append({'task_id':t['task_id'],'step_params':params})
    r=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json={**revision(state,[]),'task_edits':edits})
    assert r.status_code==200,r.text
    current=r.json()
    assert current['review_plan']['validated_plan']['intent_snapshot']['constraints']==data['intent']['constraints']
    response=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(current))
    assert response.status_code==409 and response.json()['error']['code']=='UNVERIFIED_CONSTRAINTS'

@pytest.mark.parametrize('headers',[
    ('订单编号','地区','销售额'),('岗位编号','城市','薪资'),('工单编号','类别','处理分钟'),('任务编号','项目','工时')])
def test_four_domain_overviews_and_edits_use_real_uploaded_data(client,headers):
    from planning_fixtures import plan,task,step
    from intent_fixtures import intent_payload
    from app.domain.dataset_profile import DatasetProfile
    goal=f'按{headers[1]}比较{headers[2]}'
    source=(','.join(headers)+'\n1,A,10\n2,A,\n3,B,30\n3,B,30\n').encode()
    r=client.post('/api/v1/sessions',data={'goal':goal,'manual_review':'true'},files={'file':('data.csv',source,'text/csv')})
    state=r.json();client.headers['X-Session-Token']=state.pop('review_access_token')
    candidate=plan([task([step('group_aggregate',{'dimensions':['field_0002'],'metrics':[{'function':'sum','field':'field_0003','alias':'total'}]})])],DatasetProfile.model_validate(state['profile']))
    state=save(client,state,{'plan':candidate,'intent':intent_payload(business_goal=goal)})
    sid=state['id'];view=client.get(f'/api/v1/sessions/{sid}/review').json()
    assert view['data_overview']['row_count']==4 and view['data_overview']['missing_cell_count']==1
    assert view['data_overview']['duplicate_row_count']==1
    t=state['review_plan']['validated_plan']['plan']['tasks'][0];s=t['steps'][0];p=copy.deepcopy(s['params']);p['metrics'][0]['function']='median'
    r=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=edit(state,t['task_id'],{s['step_id']:p}))
    assert r.status_code==200,r.text
    view=client.get(f'/api/v1/sessions/{sid}/review').json()
    assert view['plan_version']==2 and '中位数' in str(view['directions'])
    assert view['data_overview']['row_count']==4
