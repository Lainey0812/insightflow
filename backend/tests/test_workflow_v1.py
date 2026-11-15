import asyncio
import copy
import io
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.enums import SessionStatus as S
from app.main import create_app
from intent_fixtures import intent_payload
from hitl_fixtures import approval,execution,revision
from workflow_v1_fixtures import CSV,ControlledWorkflowProvider,create_real,draft,intent


def error(response, code):
    assert response.status_code >= 400, response.text
    assert response.json()['error']['code'] == code, response.text


def app_client(tmp_path,provider=None):
    app=create_app(Settings(tmp_path),provider or ControlledWorkflowProvider())
    return app,TestClient(app)


def approve(client,state,warnings=None):
    r=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state,warnings,request_id=f'confirmation-v{state["current_plan_version"]}'));assert r.status_code==200,r.text
    return r.json()


@pytest.mark.parametrize('xlsx',[False,True])
def test_upload_real_pipeline_approve_execute_pandas_and_replay(tmp_path,xlsx):
    provider=ControlledWorkflowProvider();app,client=app_client(tmp_path,provider)
    content=CSV;name='workflow.csv'
    if xlsx:
        output=io.BytesIO();pd.read_csv(io.BytesIO(CSV)).to_excel(output,index=False);content=output.getvalue();name='workflow.xlsx'
    with client:
        state=create_real(client,content,name)
        assert state['workflow_kind']=='real_v1' and state['status']=='AWAITING_APPROVAL'
        assert state['user_goal'] != state['intent']['analysis_goal']['business_goal']
        assert state['review_plan']['validated_plan']['intent_snapshot']['analysis_goal']==state['intent']['analysis_goal']
        assert [r.purpose for r in provider.requests]==['intent_v1','analysis_planner_v1']
        assert not state['plans'] and state['execution_result'] is None and state['report'] is None
        assert [e['status'] for e in state['workflow_events']]==['CREATED','PROFILING','PARSING_INTENT','PLANNING','VALIDATING','AWAITING_APPROVAL']
        error(client.post('/api/v1/executions',json=execution(state)),'V1_APPROVAL_REQUIRED')
        approved=approve(client,state);body=execution(approved)
        result=client.post('/api/v1/executions',json=body).json();assert result['execution_status']=='success' and result['source']=='engine'
        frame=pd.read_csv(io.BytesIO(CSV));expected=frame.groupby('地区',dropna=False)['销售额'].sum().to_dict()
        assert {r['field_0002']:r['sales_total'] for r in result['tasks'][0]['result']['rows']}==expected
        assert result['tasks'][1]['result']['rows']==[{'sales_total':int(frame['销售额'].sum())}]
        assert client.post('/api/v1/executions',json=body).json()==result
        final=client.get('/api/v1/sessions/'+state['id']).json();assert final['status']=='COMPLETED' and final['report'] is None
        assert [e['status'] for e in final['workflow_events']][-3:]==['APPROVED','RUNNING','COMPLETED']
        task=result['tasks'][0]
        assert client.get(f'/api/v1/executions/{result["execution_id"]}/results/{task["result_id"]}').json()['rows']==task['result']['rows']
        error(client.post('/api/v1/sessions/'+state['id']+'/execute',json=approval(final)),'V1_EXECUTION_ENDPOINT_REQUIRED')


def test_clarification_pauses_then_continues_and_versions_answers(tmp_path):
    unclear=intent_payload('undetermined','clarify');p=ControlledWorkflowProvider([unclear,intent()]);app,client=app_client(tmp_path,p)
    with client:
        state=create_real(client,goal='帮我处理一下');sid=state['id']
        assert state['status']=='WAITING_FOR_CLARIFICATION' and state['review_plan'] is None and len(p.requests)==1
        r=client.post(f'/api/v1/sessions/{sid}/clarifications',json={'expected_revision':state['revision'],'answer':'探索销售记录的主要分布'})
        assert r.status_code==200,r.text
        state=client.get(f'/api/v1/sessions/{sid}').json()
        assert state['status']=='AWAITING_APPROVAL' and len(state['intent_history'])==2
        assert state['clarification_answers']==['探索销售记录的主要分布']
        assert len(p.requests)==3 and state['intent']['user_query']=='帮我处理一下'
        error(client.post(f'/api/v1/sessions/{sid}/clarifications',json={'expected_revision':state['revision'],'answer':'再次补充'}),'CLARIFICATION_NOT_ALLOWED')


@pytest.mark.parametrize('kind',['constraint','defer'])
def test_unconfirmed_constraints_or_statistic_not_silently_dropped(tmp_path,kind):
    value=intent()
    if kind=='constraint':value['constraints']['filters']=[{'raw_text':'排除硬件','validation_status':'unverified'}]
    else:value['uncertainties']=[{'id':'basis','issue':'统计口径未确认','reason':'影响比较','action':'defer','resolve_at':'plan_approval'}]
    app,client=app_client(tmp_path,ControlledWorkflowProvider([value]))
    with client:
        state=create_real(client,goal='探索销售数据，排除硬件' if kind=='constraint' else '比较销售数据，统计口径未确认')
        saved=state['review_plan']['validated_plan']['intent_snapshot'];assert saved['constraints']==value['constraints']
        code='UNVERIFIED_CONSTRAINTS' if kind=='constraint' else 'BLOCKING_UNCERTAINTY'
        error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)),code)
        assert client.get(f'/api/v1/sessions/{state["id"]}').json()['engine_execution_ids']==[]


def test_multi_filter_exclusion_group_sort_top_n_chain_as_reviewed_exploration(tmp_path):
    def planned(ctx):
        d=draft(ctx);t=d['tasks'][0]
        t['steps']=[{'step_id':'F','operation':'filter','params':{'conditions':[
            {'field':'field_0001','operator':'gte','value':'2026-01-01'},
            {'field':'field_0001','operator':'lt','value':'2027-01-01'},
            {'field':'field_0003','operator':'ne','value':'硬件'},
            {'field':'field_0006','operator':'eq','value':'已完成'}]}},t['steps'][0],
            {'step_id':'SORT','operation':'sort','params':{'field':'sales_total','direction':'desc'}},
            {'step_id':'TOP','operation':'top_n','params':{'field':'sales_total','direction':'desc','n':2}}]
        t['title']='探索2026非硬件已完成订单地区分布';return d
    app,client=app_client(tmp_path,ControlledWorkflowProvider(planner=planned))
    with client:
        state=approve(client,create_real(client));result=client.post('/api/v1/executions',json=execution(state)).json()
        frame=pd.read_csv(io.BytesIO(CSV));dates=pd.to_datetime(frame['日期']);filtered=frame[(dates.dt.year==2026)&(frame['品类']!='硬件')&(frame['状态']=='已完成')]
        expected=filtered.groupby('地区')['销售额'].sum().sort_values(ascending=False).head(2).to_dict()
        assert {r['field_0002']:r['sales_total'] for r in result['tasks'][0]['result']['rows']}==expected
        assert [s['operation'] for s in result['tasks'][0]['execution_metadata']['steps']]==['filter','group_aggregate','sort','top_n']


def test_f0_core_is_retained_and_f1_transform_is_real(tmp_path):
    def blocked(ctx):
        d=draft(ctx);d['tasks'][0].update(steps=[],missing_inputs=['缺少利润率运算能力']);return d
    app,client=app_client(tmp_path/'blocked',ControlledWorkflowProvider(planner=blocked))
    with client:
        state=create_real(client);checked=state['review_plan']['validated_plan']
        assert checked['coverage_status']=='blocked' and checked['plan']['tasks'][0]['priority']=='P0'
        assert checked['validation_results'][0]['feasibility']=='F0' and checked['unmet_core_requirements']
        error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)),'COVERAGE_BLOCKED')
    def derived(ctx):
        d=draft(ctx);t=d['tasks'][0];t['steps']=[{'step_id':'D','operation':'derive','params':{'function':'extract_year','field':'field_0001','alias':'year'}},t['steps'][0]]
        t['steps'][1]['params']['dimensions']=['year'];return d
    app,client=app_client(tmp_path/'derived',ControlledWorkflowProvider(planner=derived))
    with client:
        state=create_real(client);assert state['review_plan']['validated_plan']['validation_results'][0]['feasibility']=='F1'
        state=approve(client,state);result=client.post('/api/v1/executions',json=execution(state)).json()
        frame=pd.read_csv(io.BytesIO(CSV));expected=frame.groupby(pd.to_datetime(frame['日期']).dt.year)['销售额'].sum().to_dict()
        assert {r['year']:r['sales_total'] for r in result['tasks'][0]['result']['rows']}==expected


def test_delete_revalidation_old_approval_invalid_and_single_task(tmp_path):
    app,client=app_client(tmp_path)
    with client:
        initial=create_real(client);approved=approve(client,initial)
        response=client.post(f'/api/v1/sessions/{initial["id"]}/plan-revisions',json=revision(approved,['A02']));assert response.status_code==200,response.text
        changed=response.json();assert changed['current_plan_version']==2 and len(changed['review_plan']['validated_plan']['plan']['tasks'])==1
        assert changed['engine_approval'] is None and client.get(f'/api/v1/sessions/{initial["id"]}/plans/1').json()==initial['review_plan']
        error(client.post('/api/v1/executions',json=execution(approved)),'V1_APPROVAL_REQUIRED')
        changed=approve(client,changed)
        assert client.post('/api/v1/executions',json=execution(changed)).json()['execution_status']=='success'


def test_task_failure_is_partial_and_other_results_persist(tmp_path):
    app,client=app_client(tmp_path)
    with client:
        state=approve(client,create_real(client))
        def broken(frame,params):raise ValueError('controlled unit fault')
        reg=app.state.capability_registry;reg.operations['aggregate']=replace(reg.operations['aggregate'],handler=broken)
        result=client.post('/api/v1/executions',json=execution(state)).json()
        assert result['execution_status']=='partial_success'
        assert [t['status'] for t in result['tasks']]==['success','failed']
        assert result['tasks'][1]['error']['step_id']=='S01'
        assert client.get(f'/api/v1/executions/{result["execution_id"]}').json()==result


@pytest.mark.parametrize('where,code',[('intent','LLM_TIMEOUT'),('planner','LLM_HTTP_ERROR')])
def test_llm_failure_is_persisted_retry_uses_checkpoint(tmp_path,where,code):
    provider=ControlledWorkflowProvider([AppError(code,'private detail',504)] if where=='intent' else None,
        planner=(lambda ctx:AppError(code,'private detail',502)) if where=='planner' else None)
    app,client=app_client(tmp_path,provider)
    with client:
        state=create_real(client);sid=state['id'];assert state['status']=='FAILED' and state['profile']['row_count']==4
        assert state['error']['retryable'] and state['review_plan'] is None and not state['engine_execution_ids']
        provider.intents=[intent()];provider.intent_calls=0;provider.planner=draft
        old=len(provider.requests);r=client.post(f'/api/v1/sessions/{sid}/retry-preparation',json={'expected_revision':state['revision']});assert r.status_code==200,r.text
        ready=client.get(f'/api/v1/sessions/{sid}').json();assert ready['status']=='AWAITING_APPROVAL'
        assert len([n for n in ready['node_runs'] if n['node_name']=='data_profiler'])==1
        assert len(provider.requests)-old==(2 if where=='intent' else 1)
        error(client.post(f'/api/v1/sessions/{sid}/retry-preparation',json={'expected_revision':ready['revision']}),'PREPARATION_RETRY_NOT_ALLOWED')


@pytest.mark.parametrize('stage',['intent','planner'])
def test_mock_sources_rejected_before_review_or_execution(tmp_path,stage):
    p=ControlledWorkflowProvider(mock=stage=='intent')
    if stage=='planner':
        async def changed(req):
            response=await original(req)
            return response.model_copy(update={'is_mock':req.purpose=='analysis_planner_v1'})
        original=p.generate;p.generate=changed
    app,client=app_client(tmp_path,p)
    with client:
        state=create_real(client);assert state['status']=='FAILED' and state['error']['code']=='MOCK_SOURCE_FORBIDDEN'
        assert state['review_plan'] is None and state['report'] is None


def test_refresh_restart_ready_and_running_preparation_recovery(tmp_path):
    provider=ControlledWorkflowProvider();app,client=app_client(tmp_path,provider)
    with client:
        state=create_real(client);sid=state['id'];token=client.headers['X-Session-Token']
        assert client.get('/api/v1/sessions/'+sid).json()==state
    with TestClient(create_app(Settings(tmp_path))) as reopened:
        reopened.headers['X-Session-Token']=token
        assert reopened.get('/api/v1/sessions/'+sid).json()==state
        approved=approve(reopened,state)
        assert reopened.post('/api/v1/executions',json=execution(approved)).json()['execution_status']=='success'
    checkpoint_path=tmp_path/'checkpoint'
    before,first=app_client(checkpoint_path,provider)
    def fail_validation(*args):raise AppError('PLAN_SCHEMA_INVALID','受控校验中断',422)
    before.state.plan_review.validate_v1=fail_validation
    with first:
        interrupted=create_real(first);iid=interrupted['id'];itoken=first.headers['X-Session-Token']
        assert interrupted['planner_result'] is not None and interrupted['review_plan'] is None
        assert first.get(f'/api/v1/sessions/{iid}/plans').json()==[]
        def simulate_crash(s):s.status=S.VALIDATING;s.error=None
        # Resume a genuine stored model checkpoint, with no fabricated approval/audit.
        before.state.repository.mutate(iid,simulate_crash)
    calls=len(provider.requests)
    with TestClient(create_app(Settings(checkpoint_path),provider)) as reopened:
        reopened.headers['X-Session-Token']=itoken
        failed=reopened.get('/api/v1/sessions/'+iid).json()
        assert failed['status']=='FAILED' and failed['error']['code']=='PROCESS_INTERRUPTED'
        r=reopened.post(f'/api/v1/sessions/{iid}/retry-preparation',json={'expected_revision':failed['revision']});assert r.status_code==200
        again=reopened.get('/api/v1/sessions/'+iid).json();assert again['status']=='AWAITING_APPROVAL'
        assert len(provider.requests)==calls  # Validation checkpoint needs no second LLM call.
        assert len(reopened.get(f'/api/v1/sessions/{iid}/plans').json())==1


def test_real_plan_not_replaceable_by_manual_import(tmp_path):
    app,client=app_client(tmp_path)
    with client:
        state=create_real(client)
        error(client.post(f'/api/v1/sessions/{state["id"]}/plans',json={'expected_revision':state['revision'],'plan':state['review_plan']['validated_plan']['plan'],'intent':state['review_plan']['validated_plan']['intent_snapshot']}),'GENERATED_PLAN_MANAGED_BY_WORKFLOW')


def test_partial_core_plan_requires_acknowledgement_and_skips_f0(tmp_path):
    def partial(ctx):
        d=draft(ctx);d['tasks'][1].update(priority='P0',requirement_ids=[r['requirement_id'] for r in ctx['core_requirements']],steps=[],missing_inputs=['缺少核心利润率计算能力'])
        return d
    app,client=app_client(tmp_path,ControlledWorkflowProvider(planner=partial))
    with client:
        state=create_real(client);checked=state['review_plan']['validated_plan']
        assert checked['coverage_status']=='partial' and checked['blocked_task_ids']==['A02']
        error(client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)),'WARNINGS_NOT_ACKNOWLEDGED')
        approved=approve(client,state,['partial_coverage','blocked_tasks'])
        result=client.post('/api/v1/executions',json=execution(approved)).json()
        assert result['execution_status']=='partial_success' and [t['status'] for t in result['tasks']]==['success','skipped']
        assert result['tasks'][1]['error']['code']=='MISSING_FIELD'


def test_review_answer_replans_the_same_file_into_a_new_unapproved_version(tmp_path):
    blocked=intent();blocked['constraints']['filters']=[{'raw_text':'排除硬件','validation_status':'unverified'}]
    provider=ControlledWorkflowProvider([blocked,intent()]);app,client=app_client(tmp_path,provider)
    with client:
        state=create_real(client,goal='探索销售数据，排除硬件');sid=state['id'];file_id=state['file']['id'];dataset=state['dataset_ref']
        view=client.get(f'/api/v1/sessions/{sid}/review').json()
        assert any('排除硬件' in question for question in view['confirmation_questions']) and not view['can_approve']
        reply=client.post(f'/api/v1/sessions/{sid}/review-answers',json={'expected_revision':state['revision'],'answer':'排除品类为硬件的记录'})
        assert reply.status_code==200,reply.text
        current=client.get(f'/api/v1/sessions/{sid}').json()
        assert current['status']=='AWAITING_APPROVAL' and current['user_goal']=='探索销售数据，排除硬件'
        assert current['clarification_answers']==['排除品类为硬件的记录'] and current['file']['id']==file_id and current['dataset_ref']==dataset
        assert current['review_plan']['plan_version']==2 and current['review_plan']['change_type']=='review_answered'
        assert current['engine_approval'] is None and current['engine_execution_ids']==[]
        assert client.get(f'/api/v1/sessions/{sid}/plans/1').json()['plan_version']==1
        assert any('排除品类为硬件的记录' in request.instruction or '排除品类为硬件的记录' in request.system_prompt for request in provider.requests)
        error(client.post(f'/api/v1/sessions/{sid}/review-answers',json={'expected_revision':current['revision'],'answer':'再补充一次'}),'REVIEW_ANSWER_NOT_REQUIRED')


def test_failed_review_answer_keeps_the_uploaded_plan(tmp_path):
    blocked=intent();blocked['constraints']['filters']=[{'raw_text':'排除硬件','validation_status':'unverified'}]
    calls={'n':0}
    def planned(ctx):
        calls['n']+=1
        if calls['n']>1:raise RuntimeError('planner down')
        return draft(ctx)
    app,client=app_client(tmp_path,ControlledWorkflowProvider([blocked,intent()],planner=planned))
    with client:
        state=create_real(client,goal='探索销售数据，排除硬件');sid=state['id'];version=state['review_plan']['plan_version']
        reply=client.post(f'/api/v1/sessions/{sid}/review-answers',json={'expected_revision':state['revision'],'answer':'排除硬件'})
        assert reply.status_code==200,reply.text
        current=client.get(f'/api/v1/sessions/{sid}').json()
        assert current['status']=='AWAITING_APPROVAL' and current['review_plan']['plan_version']==version
        assert current['engine_execution_ids']==[] and any('原来的待确认方案仍在' in message['content'] for message in current['messages'])
