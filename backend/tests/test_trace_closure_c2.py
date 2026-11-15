"""Real APIs and persisted records with a declared local HTTP test transport."""
import json
from contextlib import closing
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.domain.errors import AppError
from app.main import create_app
from test_report_workflow import Provider,run,QUERY,SALES
from test_workflow_trace_v031 import http_provider
AUTH={'X-Admin-Token':'read'}


def application(path,control=None):
    provider,_=http_provider(control or Provider())
    return create_app(Settings(path,admin_read_token='read'),provider)


def trace(client,workflow_id):
    response=client.get('/admin/workflow-traces/'+workflow_id,headers=AUTH)
    assert response.status_code==200,response.text
    return response.json()


def test_public_workflow_id_full_trace_and_business_refs_persist(tmp_path):
    app=application(tmp_path)
    with TestClient(app) as client:
        _,execution,session=run(client)
        data=trace(client,session['workflow_id'])
        assert data['collection']['status']=='observed',data['collection']
        assert data['root_run_id']==session['root_run_id']
        assert {s['name'] for s in data['nodes']}=={'data_profiler','intent_parser','analysis_planner','plan_validator','hitl','analysis_engine','evidence_builder','chart_builder','insight_generator','fact_validator','report_assembler','report_persistence'}
        assert all(s['run_id']==session['root_run_id'] and s['parent_span_id'] is None and s['duration_ms']>=0 for s in data['nodes'])
        assert len({s['span_id'] for s in data['nodes']})==len(data['nodes'])
        assert all(s['status']=='success' for s in data['nodes'])
        assert len(data['llm_calls'])==3 and all(c['status']=='succeeded' for c in data['llm_calls'])
        assert data['executions'][0]['execution_id']==execution['execution_id']
        report=data['reports'][0];receipt=report['commit_receipt']
        persistence=next(s for s in data['nodes'] if s['name']=='report_persistence')
        assert receipt['persistence_span_id']==persistence['span_id']
        assert receipt['workflow_id']==session['workflow_id'] and receipt['execution_id']==execution['execution_id']
        assert data['approvals'][0]['approval_id']==execution['approval_id']
        from app.storage.workflow_reader import WorkflowReader
        reader=WorkflowReader(app.state.repository.database.path)
        reader.plan(session['workflow_id'],execution['plan_version'])
        reader.approval(session['workflow_id'],execution['approval_id'])
        reader.execution(session['workflow_id'],execution['execution_id'])
        reader.report(session['workflow_id'],report['report_id'])
        assert data['executions'][0]['plan_version_id']==data['plan_versions'][0]['plan_version_id']
        assert client.get('/admin/workflow-traces/'+session['workflow_id']).status_code==403
        assert client.get('/admin/workflow-traces/missing',headers=AUTH).status_code==404
        stored=json.dumps(data['nodes'],sort_keys=True)
    with TestClient(application(tmp_path)) as client:
        assert json.dumps(trace(client,session['workflow_id'])['nodes'],sort_keys=True)==stored


def test_report_commit_acknowledgement_lost_reads_durable_fact(tmp_path,monkeypatch):
    app=application(tmp_path);finish=app.state.reports.finish
    def lost_ack(*args,**kwargs):
        result=finish(*args,**kwargs)
        if kwargs.get('report') and result:raise OSError('commit acknowledgement lost')
        return result
    monkeypatch.setattr(app.state.reports,'finish',lost_ack)
    with TestClient(app) as client:
        _,execution,session=run(client)
        assert session['report_generations'][0]['status']=='completed'
        data=trace(client,session['workflow_id'])
        assert next(s for s in data['nodes'] if s['name']=='report_persistence')['status']=='success'
        assert app.state.executions.get(execution['execution_id']).execution_status=='success'


@pytest.mark.parametrize('failure',['disabled','terminal_write'])
def test_trace_unavailable_or_write_failure_preserves_business(tmp_path,monkeypatch,failure):
    app=application(tmp_path)
    if failure=='disabled':app.state.traces.repository=None
    else:monkeypatch.setattr(app.state.traces.repository,'save_span',lambda *a: (_ for _ in ()).throw(OSError('down')))
    with TestClient(app) as client:
        _,execution,session=run(client)
        assert execution['execution_status']=='success' and session['report_generations'][0]['status']=='completed'
        data=trace(client,session['workflow_id'])
        assert data['collection']['status']=='incomplete' and data['collection']['gaps']
        if failure=='disabled':assert data['nodes']==[]
        assert data['reports'][0]['report_id']==session['report_generations'][0]['report_id']


def test_failed_report_and_retry_keep_separate_nodes_and_attempts(tmp_path):
    control=Provider(report_error=AppError('LLM_TIMEOUT','timeout',504));app=application(tmp_path,control)
    with TestClient(app) as client:
        _,execution,session=run(client)
        first=trace(client,session['workflow_id'])
        generation=next(s for s in first['nodes'] if s['name']=='insight_generator')
        assert generation['status']=='error'
        old_id=generation['span_id']
        assert not [s for s in first['nodes'] if s['name']=='report_persistence']
        control.report_provider.error=None
        response=client.post('/api/v1/executions/'+execution['execution_id']+'/report',json={'expected_attempt':1})
        assert response.status_code==202,response.text
        final=trace(client,session['workflow_id'])
        candidates=[s for s in final['nodes'] if s['name']=='insight_generator']
        assert len(candidates)==2 and [s['attributes']['report_attempt'] for s in candidates]==[1,2]
        assert candidates[0]['span_id']==old_id and candidates[0]['status']=='error' and candidates[1]['status']=='success'
        assert len(final['report_artifact_runs'])==2


def test_missing_persistence_span_is_a_gap_not_a_synthetic_node(tmp_path,monkeypatch):
    app=application(tmp_path);reserve=app.state.traces.repository.reserve_workflow_span
    def missing(span):
        if span.name=='report_persistence':raise OSError('single node observation unavailable')
        return reserve(span)
    monkeypatch.setattr(app.state.traces.repository,'reserve_workflow_span',missing)
    with TestClient(app) as client:
        _,_,session=run(client);data=trace(client,session['workflow_id'])
        assert session['report_generations'][0]['status']=='completed'
        assert not [s for s in data['nodes'] if s['name']=='report_persistence']
        assert any(g['code']=='REPORT_COMMIT_SPAN_NOT_COLLECTED' for g in data['collection']['gaps'])
        assert data['reports'][0]['commit_receipt']['persistence_span_id'] is None


def test_real_engine_partial_outcome_has_partial_node_and_exact_errors(tmp_path,monkeypatch):
    from workflow_v1_fixtures import ControlledWorkflowProvider,create_real
    from hitl_fixtures import approval,execution
    app=create_app(Settings(tmp_path,admin_read_token='read'),ControlledWorkflowProvider())
    runner=app.state.analysis_engine.runner.run
    def fail_second(task,*args):
        if task.task_id=='A02':
            error=app.state.analysis_engine.skipped(task.task_id,'TEST_TASK_FAILURE','isolated task failure')
            error=error.model_copy(update={'status':'failed'})
            return error,None,None,0
        return runner(task,*args)
    monkeypatch.setattr(app.state.analysis_engine.runner,'run',fail_second)
    with TestClient(app) as client:
        state=create_real(client)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        from app.domain.execution import ExecutionRequest
        result=app.state.analysis_engine.execute(ExecutionRequest(**execution(approved)))
        assert result.execution_status=='partial_success'
        data=trace(client,state['workflow_id'])
        node=next(s for s in data['nodes'] if s['name']=='analysis_engine')
        assert node['status']=='error' and node['error_code']=='TEST_TASK_FAILURE'
        assert data['executions'][0]['outcome']=='partial_success'


def test_waiting_root_active_node_is_interrupted_on_recovery(tmp_path):
    from app.observability.recorder import SpanHandle
    from workflow_v1_fixtures import create_real,ControlledWorkflowProvider
    from app.observability.workflow import preparation_context
    app=create_app(Settings(tmp_path),ControlledWorkflowProvider())
    with TestClient(app) as client:
        state=create_real(client);saved=app.state.repository.get(state['id'])
        identity=app.state.workflow.identity(saved)
        context=preparation_context(app.state.traces,saved.id,identity,explicit_only=True)
        span=SpanHandle(context,'hitl')
        app.state.traces.recover()
        stored=app.state.traces.repository.span(span.record.span_id)
        assert stored.status=='suspended' and stored.duration_ms is None
        span.finish()
        assert app.state.traces.repository.span(span.record.span_id).status=='suspended'


def test_pre_c2_approval_is_registered_by_reference_without_reapproval(tmp_path,monkeypatch):
    from workflow_v1_fixtures import ControlledWorkflowProvider,create_real
    from hitl_fixtures import approval,execution
    from app.domain.execution import ExecutionRequest
    app=create_app(Settings(tmp_path),ControlledWorkflowProvider())
    with TestClient(app) as client:
        state=create_real(client)
        # Reproduce an immutable Approval created by the previous release (before link writes existed).
        with monkeypatch.context() as patch:
            patch.setattr('app.storage.workflow_bindings.bind_approval',lambda *a,**k:None)
            approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        original=app.state.plan_review.audit.approvals(state['id'])[0].model_dump_json()
        result=app.state.analysis_engine.execute(ExecutionRequest(**execution(approved)))
        assert result.execution_status=='success'
        assert len(app.state.plan_review.audit.approvals(state['id']))==1
        assert app.state.plan_review.audit.approvals(state['id'])[0].model_dump_json()==original
        with closing(app.state.repository.database.connect()) as conn:
            assert conn.execute('SELECT source_kind FROM workflow_approval_links WHERE approval_id=?',(result.approval_id,)).fetchone()[0]=='legacy_ref'


def test_pre_identity_legacy_report_runs_remain_owning_spans(tmp_path):
    provider,_=http_provider(Provider())
    app=create_app(Settings(tmp_path,admin_read_token='read'),provider,bootstrap_identity=False)
    with TestClient(app) as client:
        _,result,session=run(client)
        assert session['workflow_id'] is None
        report_run=app.state.traces.repository.attempt(result['execution_id'],1)
        nodes=app.state.traces.repository.spans(report_run.run_id)
        assert len(nodes)==6 and all(n.run_id==report_run.run_id for n in nodes)
        assert report_run.status=='success'


def test_no_evidence_records_skip_decision_without_unexecuted_llm_span(tmp_path,monkeypatch):
    app=application(tmp_path)
    def unavailable(task,*args,**kwargs):
        failure=app.state.analysis_engine.skipped(task.task_id,'TEST_TASK_FAILURE','isolated failure')
        return failure.model_copy(update={'status':'failed'}),None,None,0
    monkeypatch.setattr(app.state.analysis_engine.runner,'run',unavailable)
    with TestClient(app) as client:
        _,result,session=run(client);data=trace(client,session['workflow_id'])
        assert result['execution_status']=='failed' and data['report_generations'][0]['status']=='unavailable'
        assert not [s for s in data['nodes'] if s['name'] in {'insight_generator','fact_validator'}]
        assert {e['payload']['node_name'] for e in data['events'] if e['event_type']=='report.node_skipped'}=={'insight_generator','fact_validator'}
        assert len(data['llm_calls'])==2


def test_artifact_snapshot_failure_is_a_collection_gap(tmp_path,monkeypatch):
    app=application(tmp_path)
    monkeypatch.setattr(app.state.traces.repository,'save_snapshot',lambda *a: (_ for _ in ()).throw(OSError('snapshots down')))
    with TestClient(app) as client:
        _,_,session=run(client);data=trace(client,session['workflow_id'])
        assert session['report_generations'][0]['status']=='completed'
        assert any(g['code']=='REPORT_ARTIFACT_COLLECTION_GAP' for g in data['collection']['gaps'])


def test_missing_historical_ownership_is_explicit_not_inferred(tmp_path,monkeypatch):
    from workflow_v1_fixtures import ControlledWorkflowProvider,create_real
    from hitl_fixtures import approval
    app=create_app(Settings(tmp_path,admin_read_token='read'),ControlledWorkflowProvider())
    with TestClient(app) as client:
        state=create_real(client)
        with monkeypatch.context() as patch:
            patch.setattr('app.storage.workflow_bindings.bind_approval',lambda *a,**k:None)
            response=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state))
            assert response.status_code==200
        data=trace(client,state['workflow_id'])
        assert data['approvals']==[]
        assert any(g['code']=='APPROVAL_OWNERSHIP_NOT_REGISTERED' for g in data['collection']['gaps'])


def test_native_context_lookup_failure_does_not_reparent_nodes_to_artifact_run(tmp_path,monkeypatch):
    app=application(tmp_path)
    monkeypatch.setattr(app.state.report_workflow.observations,'context',lambda *a: (_ for _ in ()).throw(OSError('binding read temporarily unavailable')))
    with TestClient(app) as client:
        _,_,session=run(client);data=trace(client,session['workflow_id'])
        assert session['report_generations'][0]['status']=='completed'
        assert data['collection']['status']=='incomplete'
        artifact=data['report_artifact_runs'][0]
        with closing(app.state.traces.repository.connect()) as conn:
            assert conn.execute('SELECT count(*) FROM trace_spans WHERE run_id=?',(artifact['run_id'],)).fetchone()[0]==0
        assert data['reports'][0]['commit_receipt']['persistence_span_id'] is None


def test_process_loss_after_report_commit_retains_business_delivery_on_restart(tmp_path,monkeypatch):
    import asyncio
    from workflow_v1_fixtures import create_real
    from hitl_fixtures import approval,execution
    from app.domain.execution import ExecutionRequest
    class SimulatedProcessLoss(BaseException):pass
    app=application(tmp_path);finish=app.state.reports.finish
    def crash_after_commit(*args,**kwargs):
        accepted=finish(*args,**kwargs)
        if accepted and kwargs.get('report'):raise SimulatedProcessLoss()
        return accepted
    with TestClient(app) as client:
        state=create_real(client,SALES,'sales.csv',QUERY)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        result=app.state.analysis_engine.execute(ExecutionRequest(**execution(approved)))
        generation,_=app.state.report_workflow.enqueue(result.execution_id)
        with monkeypatch.context() as patch:
            patch.setattr(app.state.reports,'finish',crash_after_commit)
            with pytest.raises(SimulatedProcessLoss):
                asyncio.run(app.state.report_workflow.generate(result.execution_id,generation.attempt))
        saved=app.state.reports.generation(result.execution_id)
        assert saved.status=='completed' and saved.report_id
    with TestClient(application(tmp_path)) as client:
        data=trace(client,state['workflow_id'])
        assert data['report_generations'][0]['status']=='completed'
        assert data['reports'][0]['report_id']==saved.report_id
        assert data['collection']['status']=='incomplete'
        persistence=next(n for n in data['nodes'] if n['name']=='report_persistence')
        assert persistence['status']=='suspended'


def test_recover_obsolete_execution_keeps_history_without_mutating_new_branch(tmp_path):
    from workflow_v1_fixtures import create_real
    from hitl_fixtures import approval,execution
    from app.domain.execution import ExecutionRequest
    app=application(tmp_path)
    with TestClient(app) as client:
        state=create_real(client,SALES,'sales.csv',QUERY)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        current=app.state.repository.get(state['id'])
        claim=app.state.executions.claim(ExecutionRequest(**execution(approved)),current.revision,app.state.analysis_engine.check_approval)
        app.state.repository.mutate(state['id'],lambda s:setattr(s,'current_plan_version',2))
        before=app.state.repository.get(state['id'])
        app.state.analysis_engine.recover_interrupted()
        assert app.state.repository.get(state['id'])==before
        historical=app.state.executions.get(claim['execution_id'])
        assert historical.plan_version==1 and any(e.code=='EXECUTION_INTERRUPTED' for e in historical.errors)
