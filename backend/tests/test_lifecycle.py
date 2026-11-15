"""Read-model fixtures use real storage/runtime with scripted transport, no live model calls."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.domain.models import WorkflowError
from app.services.lifecycle import aggregate, LifecycleService
from app.storage.lifecycle_reader import LifecycleReader, readonly
from test_report_workflow import Provider, run, SALES, QUERY
from workflow_v1_fixtures import create_real
from hitl_fixtures import approval, execution, revision

TOKEN='lifecycle-test-read-token'

@pytest.fixture
def completed(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),Provider())
    with TestClient(app) as client:
        approved,result,final=run(client)
        client.headers['X-Admin-Token']=TOKEN
        yield app,client,final,result


def snap(app, sid):
    return app.state.lifecycle.reader.read(sid)


def project(app,sid):
    return aggregate(snap(app,sid),sid)


def gen(snapshot,status,attempt=1,report=None):
    job=snapshot.generations[0]
    job.update(status=status,attempt=attempt,report_id=report,error=None)
    snapshot.session['report_generations']=[copy.deepcopy(job)]
    # Remove report Trace for this fixture; business facts can stand alone.
    snapshot.runs=[r for r in snapshot.runs if r['kind']=='workflow']


def test_delivered_and_trace_are_separate_and_get_is_readonly(completed,monkeypatch):
    app,client,state,result=completed; sid=state['id']
    before=app.state.repository.get(sid).model_dump_json()
    def forbidden(*args,**kwargs): raise AssertionError('Read path invoked business validation')
    monkeypatch.setattr(app.state.plan_review,'review_presentation',forbidden)
    monkeypatch.setattr(app.state.analysis_engine,'check_approval',forbidden)
    monkeypatch.setattr(app.state.analysis_planner,'generate',forbidden,raising=False)
    reader=app.state.lifecycle.reader
    def dump(path):
        with readonly(path) as conn:return list(conn.iterdump())
    original={p:dump(p) for p in (reader.business_path,reader.trace_path)}
    url=f'/admin/workflows/{sid}/lifecycle'
    for prefix in ('','/api/v1'):
        response=client.get(prefix+url); assert response.status_code==200,response.text
        body=response.json()
        assert body['business_lifecycle']['status']=='succeeded',body
        assert body['business_lifecycle']['report_delivery']=='delivered'
        assert body['collection']['integrity']=='incomplete'
        assert body['source_refs']['execution_id']==result['execution_id']
        assert body['consistency']['status']=='consistent'
        assert response.headers['cache-control']=='no-store'
        assert QUERY not in response.text and 'sales_total' not in response.text
    assert app.state.repository.get(sid).model_dump_json()==before
    assert {p:dump(p) for p in original}==original
    with readonly(reader.business_path) as conn:
        with pytest.raises(sqlite3.OperationalError):conn.execute("UPDATE sessions SET updated_at='bad'")
    # Existing endpoints remain independent contracts.
    root=client.get(f'/admin/workflows/{sid}').json()
    assert set(root)=={'availability','run','observation_gap','coverage_notice'}
    listing=client.get('/admin/runs').json()
    assert all(r['kind']=='report_generation' for r in listing['items'])
    assert client.get('/admin/prompts').status_code==200


def test_missing_trace_does_not_downgrade_business_success(completed):
    app,_,s,_=completed; snapshot=snap(app,s['id']);snapshot.runs=[];snapshot.spans=[]
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='succeeded'
    assert out.collection.availability=='not_collected' and out.collection.observed_spans==[]
    assert 'trace_not_collected' in out.reason_codes
    snapshot.trace_available=False
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='succeeded'


def test_report_failed_and_retry_uses_current_attempt(completed):
    app,_,s,_=completed; snapshot=snap(app,s['id'])
    gen(snapshot,'failed')
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='partially_succeeded'
    assert {'report_failed','report_not_delivered'}<=set(out.reason_codes)
    assert out.business_lifecycle.execution_status=='success'
    assert out.business_lifecycle.report_delivery=='not_delivered'
    gen(snapshot,'generating',2)
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='running' and out.activity=='reporting'
    assert 'report_retry' in out.reason_codes and 'report_failed' not in out.reason_codes
    snapshot.generations[0]['attempt']=1 # stale callback disagrees with Session's accepted attempt
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and out.consistency.status=='inconsistent'


def test_old_failed_report_trace_does_not_override_retry(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    old=next(r for r in snapshot.runs if r['kind']=='report_generation')
    gen(snapshot,'generating',2)
    old.update(status='failed',report_id=None)
    snapshot.runs.append(old)
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='running'
    assert out.source_refs.report_run_id is None


def test_report_missing_or_wrong_branch_never_succeeds(completed):
    app,_,s,_=completed
    for target,key,value in [('reports','dataset_version','other'),('reports','execution_id','other'),
                             ('executions','result',None)]:
        snapshot=snap(app,s['id']);snapshot.__dict__[target][0][key]=value
        out=aggregate(snapshot,s['id'])
        assert out.business_lifecycle.status=='unknown',out
    snapshot=snap(app,s['id']);snapshot.reports=[]
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and 'record_missing' in out.reason_codes


def test_engine_partial_and_failed(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    result=snapshot.executions[0]['result']
    failed=copy.deepcopy(result['tasks'][0]);failed.update(task_id='A02',status='failed',result=None,
        result_id=None,result_ref=None,row_count=None,failure_reason='fixture task failed',error=None)
    # A failed task has no successful aggregate-input sample facts.
    failed['execution_metadata']['sample_statistics'] = None
    result['tasks'].append(failed);result['execution_status']='partial_success'
    # Match the accepted plan contract in all three stored snapshots, without invoking Validator.
    for checked in (snapshot.session['review_plan']['validated_plan'], snapshot.plans[0]['validated_plan'],
        snapshot.session['engine_approval']['validated_plan'], snapshot.approvals[0]['snapshot']['validated_plan'],
        snapshot.executions[0]['approval']['validated_plan']):
        checked['executable_task_ids'].append('A02')
        extra=copy.deepcopy(checked['plan']['tasks'][0]);extra['task_id']='A02'
        checked['plan']['tasks'].append(extra)
    gen(snapshot,'failed')
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='partially_succeeded',out
    assert 'execution_partial' in out.reason_codes
    result['tasks']= [failed];result['execution_status']='failed'
    for checked in (snapshot.session['review_plan']['validated_plan'], snapshot.plans[0]['validated_plan'],
        snapshot.session['engine_approval']['validated_plan'], snapshot.approvals[0]['snapshot']['validated_plan'],
        snapshot.executions[0]['approval']['validated_plan']):
        checked['executable_task_ids']=['A02']
        checked['plan']['tasks']=[t for t in checked['plan']['tasks'] if t['task_id']=='A02']
    snapshot.session['status']='FAILED'
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='failed'


def test_approval_and_plan_binding_strict(completed):
    app,_,s,_=completed
    for mutate in [lambda x:x.approvals.clear(),lambda x:x.plans.clear(),
        lambda x:x.session.update(current_plan_version=2),
        lambda x:x.session['engine_approval'].update(status='revoked'),
        lambda x:x.executions[0]['approval'].update(approval_id='other'),
        lambda x:x.session.update(engine_execution_ids=[]),
        lambda x:x.profiles.clear()]:
        snapshot=snap(app,s['id']);mutate(snapshot)
        assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'


def test_revision_recheck_and_cross_db_conflicts(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id']);snapshot.changed=True
    out=aggregate(snapshot,s['id']);assert out.business_lifecycle.status=='unknown'
    assert 'session_changed' in out.reason_codes
    snapshot=snap(app,s['id'])
    root=next(r for r in snapshot.runs if r['kind']=='workflow')
    root['business_revision']=s['revision']+50
    out=aggregate(snapshot,s['id']);assert out.consistency.status=='inconsistent'
    assert out.business_lifecycle.status=='unknown'
    snapshot=snap(app,s['id'])
    report=next(r for r in snapshot.runs if r['kind']=='report_generation')
    report['manifest']['bindings']['dataset_id']='different'
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'


def test_absent_store_is_not_created_and_permissions(completed,tmp_path):
    app,client,s,_=completed
    absent=tmp_path/'absent'/'missing.sqlite'
    service=LifecycleService(LifecycleReader(absent,absent))
    assert service.get('unknown').business_lifecycle.status=='unknown'
    assert not absent.parent.exists()
    client.headers.pop('X-Admin-Token')
    assert client.get(f'/admin/workflows/{s["id"]}/lifecycle').status_code==403
    client.headers['X-Admin-Token']=TOKEN
    assert client.get('/admin/workflows/missing/lifecycle').status_code==404


def test_waiting_approval_and_deleted_version(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),Provider())
    with TestClient(app) as client:
        s=create_real(client,SALES,'sales.csv',QUERY)
        out=project(app,s['id'])
        assert out.business_lifecycle.status=='waiting_approval',out
        # Duplicate task fixture used only to exercise real immutable deletion version path.
        snapshot=snap(app,s['id'])
        newer=copy.deepcopy(snapshot.plans[0]);newer['plan_version']=2
        snapshot.plans.append(newer)
        assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'


def test_schema_contract_controlled_fields():
    from app.domain.lifecycle import LifecycleReadModel,SourceRefs
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LifecycleReadModel(source_refs=SourceRefs(session_id='x'),activity='fake-node')


def test_clarification_resume_and_planner_retry_with_real_records(tmp_path):
    from workflow_v1_fixtures import ControlledWorkflowProvider,intent,draft
    from intent_fixtures import intent_payload
    from app.domain.errors import AppError
    p=ControlledWorkflowProvider([intent_payload('undetermined','clarify'),intent()])
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),p)
    with TestClient(app) as client:
        s=create_real(client,goal='帮我处理一下');sid=s['id']
        first=project(app,sid)
        assert first.business_lifecycle.status=='waiting_input'
        root=first.source_refs.workflow_run_id
        response=client.post(f'/api/v1/sessions/{sid}/clarifications',json={
            'expected_revision':s['revision'],'answer':'探索销售记录的分布'})
        assert response.status_code==200,response.text
        out=project(app,sid)
        assert out.business_lifecycle.status=='waiting_approval'
        assert out.source_refs.workflow_run_id==root
    p=ControlledWorkflowProvider(planner=lambda ctx:AppError('LLM_TIMEOUT','test',504))
    app=create_app(Settings(tmp_path/'retry',admin_read_token=TOKEN),p)
    with TestClient(app) as client:
        s=create_real(client);sid=s['id']
        assert project(app,sid).business_lifecycle.status=='failed'
        p.planner=draft
        response=client.post(f'/api/v1/sessions/{sid}/retry-preparation',json={'expected_revision':s['revision']})
        assert response.status_code==200,response.text
        assert project(app,sid).business_lifecycle.status=='waiting_approval'


def test_real_report_failure_retry_and_read_after_reopen(tmp_path):
    from app.domain.errors import AppError
    p=Provider(report_error=AppError('LLM_TIMEOUT','fixture timeout',504))
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),p)
    with TestClient(app) as client:
        approved,result,final=run(client);sid=final['id']
        out=project(app,sid)
        assert out.business_lifecycle.status=='partially_succeeded',out
        assert out.business_lifecycle.report_generation_status=='failed'
        old_report_run=out.source_refs.report_run_id
        p.report_provider.error=None
        response=client.post(f'/api/v1/executions/{result["execution_id"]}/report',json={'expected_attempt':1})
        assert response.status_code==202,response.text
        out=project(app,sid)
        assert out.business_lifecycle.status=='succeeded',out
        assert out.source_refs.report_attempt==2 and out.source_refs.report_run_id!=old_report_run
        assert out.source_refs.execution_id==result['execution_id']
        saved=out.model_dump()
    # A new reader does not invoke startup recovery or initialize a database.
    reopened=LifecycleService(LifecycleReader(tmp_path/'insightflow.sqlite3',tmp_path/'observability'/'trace.sqlite3'))
    assert reopened.get(sid).model_dump()==saved


def test_real_partial_engine_and_report(tmp_path,monkeypatch):
    from dataclasses import replace
    from workflow_v1_fixtures import ControlledWorkflowProvider,CSV,intent,draft
    p=Provider();p.intents=[intent()];p.planner=draft
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),p)
    def fail(*args,**kwargs):raise ValueError('test auxiliary task failure')
    registry=app.state.capability_registry
    monkeypatch.setitem(registry.operations,'aggregate',replace(registry.operations['aggregate'],handler=fail))
    with TestClient(app) as client:
        s=create_real(client,CSV,goal='探索销售数据')
        response=client.post(f'/api/v1/sessions/{s["id"]}/approvals',json=approval(s))
        assert response.status_code==200,response.text
        result=client.post('/api/v1/executions',json=execution(response.json())).json()
        assert result['execution_status']=='partial_success'
        out=project(app,s['id'])
        assert out.business_lifecycle.status=='partially_succeeded',out
        assert out.business_lifecycle.report_status=='partial'


def test_real_revision_after_success_does_not_inherit_old_delivery(tmp_path):
    from workflow_v1_fixtures import intent,draft,CSV
    p=Provider();p.intents=[intent()];p.planner=draft
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),p)
    with TestClient(app) as client:
        s=create_real(client,CSV,goal='探索销售数据')
        approved=client.post(f'/api/v1/sessions/{s["id"]}/approvals',json=approval(s)).json()
        client.post('/api/v1/executions',json=execution(approved))
        before=project(app,s['id'])
        assert before.business_lifecycle.execution_status=='success'
        assert before.business_lifecycle.report_delivery=='delivered'
        current=client.get('/api/v1/sessions/'+s['id']).json()
        revised=client.post(f'/api/v1/sessions/{s["id"]}/plan-revisions',json=revision(current,['A02']))
        assert revised.status_code==200,revised.text
        out=project(app,s['id'])
        assert out.business_lifecycle.status=='waiting_approval',out
        assert out.source_refs.plan_version==2
        assert out.source_refs.execution_id is None and out.source_refs.report_id is None
        assert 'historical_branch_ignored' in out.reason_codes
        assert out.business_lifecycle.report_delivery=='unknown'
        # Simulate the existing old report callback; it must not change current branch lifecycle.
        snapshot=snap(app,s['id']);snapshot.session['status']='COMPLETED'
        assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'


def test_saved_running_execution_and_report_queued_are_not_fabricated_spans(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),Provider())
    with TestClient(app) as client:
        s=create_real(client,SALES,'sales.csv',QUERY)
        approved=client.post(f'/api/v1/sessions/{s["id"]}/approvals',json=approval(s)).json()
        assert project(app,s['id']).activity=='approved_not_started'
        from app.domain.execution import ExecutionRequest
        request=ExecutionRequest.model_validate(execution(approved))
        claim=app.state.executions.claim(request,approved['revision'],app.state.analysis_engine.check_approval)
        out=project(app,s['id'])
        assert out.business_lifecycle.status=='running' and out.activity=='executing',out
        assert not any(n.node=='analysis_engine' for n in out.collection.observed_spans)
        # Recovery changes authoritative records; the read model merely observes the result.
        app.state.analysis_engine.recover_interrupted()
        out=project(app,s['id'])
        assert out.business_lifecycle.status=='interrupted',out
        assert 'process_interrupted' in out.reason_codes


def test_empty_success_result_remains_success(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    task=snapshot.executions[0]['result']['tasks'][0]
    task['result'].update(rows=[],total_result_rows=0,truncated=False)
    task['row_count']=0
    # Report is deliberately absent: empty rows do not mean Engine failed.
    snapshot.generations=[];snapshot.session['report_generations']=[]
    snapshot.runs=[r for r in snapshot.runs if r['kind']=='workflow']
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.execution_status=='success',out
    assert out.business_lifecycle.status=='running'
    assert out.activity=='report_not_started'


@pytest.mark.parametrize('status,expected,activity',[
    ('queued','running','report_queued'),('generating','running','reporting'),
    ('failed','partially_succeeded','finished'),('unavailable','partially_succeeded','finished'),
])
def test_report_outcomes(completed,status,expected,activity):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    report_id=snapshot.generations[0]['report_id'] if status=='unavailable' else None
    gen(snapshot,status,report=report_id)
    if status=='unavailable':
        snapshot.reports[0].update(report_status='unavailable',goal_coverage='blocked')
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status==expected and out.activity==activity,out
    assert out.business_lifecycle.report_delivery=='not_delivered'


def test_multiple_current_executions_are_ambiguous_not_latest_success(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    another=copy.deepcopy(snapshot.executions[0]);another['id']='exec_second'
    snapshot.executions.append(another);snapshot.session['engine_execution_ids'].append(another['id'])
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and 'execution_ambiguous' in out.reason_codes


def test_missing_tables_invalid_snapshot_and_future_trace_attempt(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    snapshot.missing_tables={'plan_approvals'}
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'
    snapshot=snap(app,s['id']);snapshot.session['status']='NOT_A_STATE'
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'
    snapshot=snap(app,s['id'])
    # A matching attempt with failed observation but completed business is a conflict.
    report=next(r for r in snapshot.runs if r['kind']=='report_generation');report['status']='failed'
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and out.consistency.status=='inconsistent'


def test_legacy_success_is_not_real_workflow_success(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id']);snapshot.session['workflow_kind']='legacy_mock'
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and 'unsupported_workflow' in out.reason_codes


def test_midread_concurrent_revision_is_detected(completed,monkeypatch):
    app,_,s,_=completed
    import contextlib
    import app.storage.lifecycle_reader as module
    original=module.readonly
    touched=False
    @contextlib.contextmanager
    def changing(path):
        nonlocal touched
        with original(path) as conn:yield conn
        if path==app.state.lifecycle.reader.trace_path and not touched:
            touched=True
            # Another writer, outside the read model's own connection/transaction.
            with app.state.repository.database.connect() as conn:
                row=conn.execute('SELECT state FROM sessions WHERE id=?',(s['id'],)).fetchone()
                value=json.loads(row[0]);value['revision']+=1
                conn.execute('UPDATE sessions SET state=? WHERE id=?',(json.dumps(value),s['id']))
    monkeypatch.setattr(module,'readonly',changing)
    out=project(app,s['id'])
    assert touched and out.business_lifecycle.status=='unknown'
    assert 'session_changed' in out.reason_codes


def test_no_report_generation_does_not_reuse_historical_report(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    snapshot.generations=[];snapshot.session['report_generations']=[]
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and out.consistency.status=='inconsistent'
    # With no contradictory report Trace, the persisted Engine success stands alone.
    snapshot.runs=[r for r in snapshot.runs if r['kind']=='workflow']
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='running' and out.activity=='report_not_started'
    assert out.source_refs.report_id is None and out.source_refs.report_run_id is None


@pytest.mark.parametrize('trace_status',['partial','failed','unavailable'])
def test_conflicting_terminal_report_trace_is_not_business_success(completed,trace_status):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    run=next(r for r in snapshot.runs if r['kind']=='report_generation')
    run['status']=trace_status
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown'
    assert out.consistency.status=='inconsistent' and 'trace_state_conflict' in out.reason_codes


def test_future_report_attempt_cannot_override_accepted_attempt(completed):
    app,_,s,_=completed;snapshot=snap(app,s['id'])
    run=next(r for r in snapshot.runs if r['kind']=='report_generation')
    run['attempt']+=1
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and 'trace_binding_mismatch' in out.reason_codes


def test_durable_file_hash_and_approved_intent_must_match(completed):
    app,_,s,_=completed
    snapshot=snap(app,s['id']);snapshot.files[0]['content_sha256']='a'*64
    assert aggregate(snapshot,s['id']).business_lifecycle.status=='unknown'
    snapshot=snap(app,s['id'])
    for target in (snapshot.session['engine_approval'],snapshot.approvals[0]['snapshot'],snapshot.executions[0]['approval']):
        target['intent']['analysis_goal']['business_goal']='Another analysis goal'
    out=aggregate(snapshot,s['id'])
    assert out.business_lifecycle.status=='unknown' and 'branch_mismatch' in out.reason_codes
