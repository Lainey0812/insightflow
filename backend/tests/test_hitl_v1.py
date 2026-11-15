import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.domain.errors import AppError
from hitl_fixtures import create,candidate,save,revision,approval,execution

def error(r,code):
    assert r.status_code>=400,r.text
    assert r.json()['error']['code']==code,r.text

def test_real_review_delete_approve_execute_persist_and_replay(client,app,provider,tmp_path):
    state=create(client); assert not provider.requests and not state['plans'] and state['review_status']=='awaiting_review'
    initial=save(client,state); sid=state['id']
    assert initial['review_plan']['validated_plan']['coverage_status']=='complete'
    assert client.get(f'/api/v1/sessions/{sid}/plan').json()==initial['review_plan']
    error(client.post('/api/v1/executions',json=execution(initial)),'V1_APPROVAL_REQUIRED')
    r=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(initial,['A03'])); assert r.status_code==200,r.text
    current=r.json(); assert current['review_status']=='awaiting_approval' and current['current_plan_version']==2
    assert [t['task_id'] for t in current['review_plan']['validated_plan']['plan']['tasks']]==['A01','A02']
    assert client.get(f'/api/v1/sessions/{sid}/plans/1').json()==initial['review_plan']
    body=approval(current); r=client.post(f'/api/v1/sessions/{sid}/approvals',json=body); assert r.status_code==200,r.text
    approved=r.json(); assert approved['review_status']=='approved'
    assert client.post(f'/api/v1/sessions/{sid}/approvals',json=body).json()==approved
    audit=client.get(f'/api/v1/sessions/{sid}/approvals').json(); assert len(audit)==1 and audit[0]['plan_version']==2
    r=client.post('/api/v1/executions',json=execution(approved)); assert r.status_code==200,r.text
    result=r.json(); assert result['source']=='engine' and result['approval_id']==audit[0]['approval_id']
    assert result['tasks'][0]['result']['rows']==[{'field_0003':'华东','record_count':6,'sales_total':157000}]
    assert result['tasks'][1]['result']['rows']==[{'sales_total':263000,'record_count':12}]
    assert client.post('/api/v1/executions',json=execution(approved)).json()==result
    final=client.get(f'/api/v1/sessions/{sid}').json(); assert final['review_status']=='completed' and final['engine_execution_ids']==[result['execution_id']]
    assert client.get(f'/api/v1/sessions/{sid}/approvals').json()[0]['execution_ids']==[result['execution_id']]
    with TestClient(create_app(Settings(tmp_path),provider=provider)) as reopened:
        reopened.headers['X-Session-Token']=client.headers['X-Session-Token']
        assert reopened.get(f'/api/v1/executions/{result["execution_id"]}').json()==result
        assert reopened.get(f'/api/v1/sessions/{sid}/plan').json()==current['review_plan']
        assert reopened.get(f'/api/v1/sessions/{sid}/approvals').json()[0]['snapshot']==audit[0]['snapshot']

@pytest.mark.parametrize('ids,coverage',[(['A01'],'partial'),(['A01','A02'],'blocked'),(['A01','A02','A03'],'blocked')])
def test_delete_core_and_all_tasks_preserves_goal(client,ids,coverage):
    state=save(client,create(client)); sid=state['id']
    new=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,ids)).json(); checked=new['review_plan']['validated_plan']
    assert checked['coverage_status']==coverage
    assert checked['plan']['core_requirements']==state['review_plan']['validated_plan']['plan']['core_requirements']
    assert checked['intent_snapshot']['analysis_goal']==state['review_plan']['validated_plan']['intent_snapshot']['analysis_goal']
    error(client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(new)),'COVERAGE_BLOCKED' if coverage=='blocked' else 'WARNINGS_NOT_ACKNOWLEDGED')
    if coverage=='partial': assert client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(new,['partial_coverage'])).status_code==200

@pytest.mark.parametrize('field,value,code',[('plan_id','other','PLAN_VERSION_MISMATCH'),('plan_version',9,'PLAN_VERSION_MISMATCH'),('dataset_version','wrong','DATASET_VERSION_MISMATCH'),('dataset_id','wrong','DATASET_VERSION_MISMATCH'),('validation_version','wrong','PLAN_VALIDATION_STALE'),('expected_revision',0,'STALE_SESSION'),('approval_request_id',None,'APPROVAL_REQUEST_ID_REQUIRED'),('acknowledged_warnings',['invented'],'WARNINGS_NOT_ACKNOWLEDGED')])
def test_approval_context(client,field,value,code):
    state=save(client,create(client)); body=approval(state); body[field]=value
    error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=body),code)

def test_nonexistent_task_ai_interface_and_stale_change(client):
    state=save(client,create(client)); path=f'/api/v1/sessions/{state["id"]}/plan-revisions'
    error(client.post(path,json=revision(state,['missing'])),'TASK_NOT_FOUND')
    error(client.post(path,json=revision(state,[])|{'instruction':'增加预测任务'}),'AI_REVISION_NOT_AVAILABLE')
    assert client.post(path,json=revision(state,['A03'])).status_code==200
    error(client.post(path,json=revision(state,['A02'])),'STALE_SESSION')
    assert len(client.get(f'/api/v1/sessions/{state["id"]}/plans').json())==2

def test_edit_invalidates_approval_for_both_old_and_new_version(client):
    state=save(client,create(client)); sid=state['id']; body=approval(state)
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=body).json()
    new=client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(approved,['A03'])).json()
    assert new['engine_approval'] is None and new['approved_plan_version'] is None
    for s in (state,new): error(client.post('/api/v1/executions',json=execution(s)),'V1_APPROVAL_REQUIRED')
    error(client.post(f'/api/v1/sessions/{sid}/approvals',json=body),'PLAN_VERSION_MISMATCH')
    assert len(client.get(f'/api/v1/sessions/{sid}/approvals').json())==1
    r=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(new,request_id='user-confirmation-2')); assert r.status_code==200,r.text
    error(client.post('/api/v1/executions',json=execution(state)),'PLAN_VERSION_MISMATCH')

def test_f0_visible_and_never_executed(client):
    state=create(client); data=candidate(state); data['plan']['tasks'][2]['steps'][0]['operation']='python'
    state=save(client,state,data); checked=state['review_plan']['validated_plan']
    assert checked['blocked_task_ids']==['A03'] and checked['validation_results'][2]['feasibility']=='F0'
    error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)),'WARNINGS_NOT_ACKNOWLEDGED')
    approved=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state,['blocked_tasks'])).json()
    result=client.post('/api/v1/executions',json=execution(approved)).json(); assert result['tasks'][2]['status']=='skipped'
    r=client.post('/api/v1/executions',json=execution(approved)|{'plan':data['plan']}); assert r.status_code==422

@pytest.mark.parametrize('kind',['constraint','defer','clarify'])
def test_constraints_and_uncertainty_cannot_be_acknowledged_away(client,kind):
    state=create(client); data=candidate(state)
    if kind=='constraint': data['intent']['constraints']['filters']=[{'raw_text':'仅华东','validation_status':'unverified'}]
    else:
        data['intent']['uncertainties']=[{'id':'U1','description':'口径待确认','impact':'影响计算范围','action':kind,'resolve_at':'before_planning' if kind=='clarify' else 'plan_approval'}]
        if kind=='clarify': data['intent'].update(next_action='clarify',clarification_questions=['采用哪个口径？'])
    state=save(client,state,data)
    error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)),'UNVERIFIED_CONSTRAINTS' if kind=='constraint' else 'BLOCKING_UNCERTAINTY')

def test_validator_failure_rolls_back(client,monkeypatch):
    state=save(client,create(client)); sid=state['id']
    def fail(*args): raise AppError('PLAN_SCHEMA_INVALID','校验失败',422)
    monkeypatch.setattr('app.planning.validator.PlanValidator.validate',fail)
    error(client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,['A03'])),'PLAN_SCHEMA_INVALID')
    assert client.get(f'/api/v1/sessions/{sid}').json()==state
    assert len(client.get(f'/api/v1/sessions/{sid}/plans').json())==1

def test_audit_tables_immutable(client,app):
    state=save(client,create(client)); client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state))
    for table in ('plan_versions','plan_approvals'):
        for op in ('DELETE FROM','UPDATE'):
            with closing(app.state.repository.database.connect()) as conn,pytest.raises(sqlite3.IntegrityError):
                conn.execute(f'{op} {table}'+(' SET record=record' if op=='UPDATE' else ''))

def test_access_denied_without_correct_session_token(client,app):
    state=save(client,create(client)); token=client.headers.pop('X-Session-Token'); sid=state['id']
    for supplied in (None,'invalid'):
        headers={'X-Session-Token':supplied} if supplied else {}
        for path in (f'/sessions/{sid}',f'/sessions/{sid}/plan',f'/sessions/{sid}/plans',f'/sessions/{sid}/approvals',f'/sessions/{sid}/profile'):
            error(client.get('/api/v1'+path,headers=headers),'SESSION_ACCESS_DENIED')
        error(client.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,['A03']),headers=headers),'SESSION_ACCESS_DENIED')
        error(client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state),headers=headers),'SESSION_ACCESS_DENIED')
        error(client.post('/api/v1/executions',json=execution(state),headers=headers),'SESSION_ACCESS_DENIED')
    create(client); error(client.get(f'/api/v1/sessions/{sid}/plan'),'SESSION_ACCESS_DENIED')
    client.headers['X-Session-Token']=token
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    result=client.post('/api/v1/executions',json=execution(approved)).json(); client.headers.pop('X-Session-Token')
    error(client.get(f'/api/v1/executions/{result["execution_id"]}'),'SESSION_ACCESS_DENIED')
    error(client.get(f'/api/v1/executions/{result["execution_id"]}/results/{result["tasks"][0]["result_id"]}'),'SESSION_ACCESS_DENIED')

def test_concurrent_deletion_and_duplicate_approval_request(client,app):
    state=save(client,create(client)); token=client.headers['X-Session-Token']; sid=state['id']
    def remove(task):
        with TestClient(app) as caller: return caller.post(f'/api/v1/sessions/{sid}/plan-revisions',headers={'X-Session-Token':token},json=revision(state,[task]))
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(remove,['A03','A01']))
    assert sorted(r.status_code for r in results)==[200,409]
    latest=client.get(f'/api/v1/sessions/{sid}').json(); warnings=['partial_coverage'] if latest['review_plan']['validated_plan']['coverage_status']=='partial' else []
    body=approval(latest,warnings); assert client.post(f'/api/v1/sessions/{sid}/approvals',json=body).status_code==200
    error(client.post(f'/api/v1/sessions/{sid}/approvals',json=body|{'acknowledged_warnings':['different']}),'APPROVAL_REQUEST_CONFLICT')

def test_engine_failure_preserves_approval_and_replays_failure(client,app,monkeypatch):
    state=save(client,create(client)); sid=state['id']; approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    def fail(*args): raise ValueError('simulated deterministic kernel failure')
    from dataclasses import replace
    for name in ('aggregate','group_aggregate'):
        monkeypatch.setitem(app.state.capability_registry.operations,name,replace(app.state.capability_registry.operations[name],handler=fail))
    r=client.post('/api/v1/executions',json=execution(approved)); assert r.status_code==200,r.text
    result=r.json(); assert result['execution_status']=='failed'
    latest=client.get(f'/api/v1/sessions/{sid}').json(); assert latest['review_status']=='execution_failed' and latest['engine_approval']==approved['engine_approval']
    assert client.post('/api/v1/executions',json=execution(approved)).json()==result
    assert len(client.get(f'/api/v1/sessions/{sid}/approvals').json())==1

def test_goal_and_foreign_dataset_not_changed(client):
    state=create(client); data=candidate(state); data['intent']['analysis_goal']['business_goal']='different'
    error(client.post(f'/api/v1/sessions/{state["id"]}/plans',json={'expected_revision':state['revision'],**data}),'ANALYSIS_GOAL_MISMATCH')
    data=candidate(state); data['plan']['dataset_id']='foreign'
    error(client.post(f'/api/v1/sessions/{state["id"]}/plans',json={'expected_revision':state['revision'],**data}),'DATASET_VERSION_MISMATCH')


def test_history_list_hides_protected_titles_and_token_is_returned_only_once(client):
    state=create(client); token=client.headers.pop('X-Session-Token')
    assert not any(s['id']==state['id'] for s in client.get('/api/v1/sessions').json())
    client.headers['X-Session-Token']=token
    assert any(s['id']==state['id'] for s in client.get('/api/v1/sessions').json())
    assert 'review_access_token' not in client.get(f'/api/v1/sessions/{state["id"]}').json()
    client.headers.pop('X-Session-Token')
    assert any(s['id']==state['id'] for s in client.get('/api/v1/sessions',headers={'X-Session-Keys':__import__('json').dumps({state['id']:token})}).json())


@pytest.mark.parametrize('function,expected',[('extract_month','F1'),('parse_free_text','F0')])
def test_f1_requires_supported_explicit_transformation(client,function,expected):
    goal='按月份汇总销售额'
    r=client.post('/api/v1/sessions',data={'goal':goal,'manual_review':'true'},files={'file':('dated-sales.csv','日期,销售额\n2026-01-01,10\n2026-01-02,20'.encode(),'text/csv')})
    assert r.status_code==201,r.text
    state=r.json(); client.headers['X-Session-Token']=state.pop('review_access_token')
    data=candidate(state); data['intent']['analysis_goal']['business_goal']=goal
    data['plan']['core_requirements']=[{'requirement_id':'C01','description':goal}]
    task=data['plan']['tasks'][0]; data['plan']['tasks']=[task]
    task['steps']=[{'step_id':'S1','operation':'derive','params':{'field':'field_0001','function':function,'alias':'month'}},
                   {'step_id':'S2','operation':'group_aggregate','params':{'dimensions':['month'],'metrics':[{'function':'sum','field':'field_0002','alias':'total'}]}}]
    state=save(client,state,data)
    assert state['review_plan']['validated_plan']['validation_results'][0]['feasibility']==expected
    r=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state))
    if expected=='F0': error(r,'COVERAGE_BLOCKED')
    else:
        assert r.status_code==200,r.text
        result=client.post('/api/v1/executions',json=execution(r.json())).json()
        assert result['tasks'][0]['result']['rows']==[{'month':1,'total':30}]


def test_stale_validator_and_concurrent_duplicate_approval(client,app,monkeypatch):
    state=save(client,create(client)); sid=state['id']; body=approval(state)
    with monkeypatch.context() as changes:
        changes.setattr(app.state.capability_registry,'version','next')
        error(client.post(f'/api/v1/sessions/{sid}/approvals',json=body),'PLAN_VALIDATION_STALE')
    token=client.headers['X-Session-Token']
    def confirm(_):
        with TestClient(app) as caller: return caller.post(f'/api/v1/sessions/{sid}/approvals',headers={'X-Session-Token':token},json=body)
    with ThreadPoolExecutor(2) as pool: replies=list(pool.map(confirm,range(2)))
    assert [r.status_code for r in replies]==[200,200]
    assert replies[0].json()==replies[1].json()
    assert len(client.get(f'/api/v1/sessions/{sid}/approvals').json())==1


def test_engine_observes_executing_state_and_disallows_modification(client,app,monkeypatch):
    state=save(client,create(client)); sid=state['id']; approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state)).json()
    original=app.state.analysis_engine.runner.run
    observations=[]
    def inspect(*args,**kwargs):
        current=app.state.repository.get(sid); observations.append(current.review_status)
        from app.services.plan_review import RevisionRequest
        with pytest.raises(AppError) as exc:
            app.state.plan_review.revise(sid,RevisionRequest.model_validate(revision(current.model_dump(),['A03'])))
        assert exc.value.error.code=='PLAN_NOT_EDITABLE'
        return original(*args,**kwargs)
    monkeypatch.setattr(app.state.analysis_engine.runner,'run',inspect)
    assert client.post('/api/v1/executions',json=execution(approved)).status_code==200
    assert observations==['executing']*3


def test_unknown_session_and_legacy_approval_bypass_are_rejected(client):
    error(client.get('/api/v1/sessions/unknown/plan'),'SESSION_NOT_FOUND')
    state=save(client,create(client))
    response=client.post(f'/api/v1/sessions/{state["id"]}/execute',json=approval(state))
    error(response,'V1_EXECUTION_ENDPOINT_REQUIRED')
    error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)|{'approved':True}),'VALIDATION_ERROR')
