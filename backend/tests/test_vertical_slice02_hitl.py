"""Only the audited HITL path is enabled. No Engine/Report integration is claimed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.execution import ExecutionRequest
from app.main import create_app
from workflow_v1_fixtures import ControlledWorkflowProvider, create_real
from hitl_fixtures import approval, execution, revision
from test_report_workflow import Provider, QUERY, SALES


def make(path):
    return create_app(Settings(path), ControlledWorkflowProvider())


def spans(app,state):
    return [s for s in app.state.traces.repository.spans(state['root_run_id']) if s.name=='hitl']


def test_approval_replay_and_denial_have_committed_refs(tmp_path):
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client);assert spans(app,state)==[]
        body=approval(state);url='/api/v1/sessions/'+state['id']+'/approvals'
        first=client.post(url,json=body);assert first.status_code==200
        assert client.post(url,json=body).json()==first.json()
        denied=client.post(url,json={**body,'plan_version':999})
        assert denied.status_code==409
        observed=spans(app,state)
        assert [s.status for s in observed]==['success','success','error']
        assert [s.attributes.get('outcome') for s in observed]==['approved','replayed',None]
        assert observed[-1].error_code=='PLAN_VERSION_MISMATCH'
        assert all(s.parent_span_id is None and s.attributes['workflow_id']==state['workflow_id'] for s in observed)
        assert len({s.span_id for s in observed})==3
        assert [s.node_attempt for s in observed]==[1,2,3]
        assert len(app.state.plan_review.audit.approvals(state['id']))==1
        assert observed[0].attributes['approval_id']==first.json()['engine_approval']['approval_id']
        assert all(s.duration_ms>=0 and s.finished_at for s in observed)


def test_revision_real_validation_and_no_long_waiting_span(tmp_path):
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client)
        response=client.post('/api/v1/sessions/'+state['id']+'/plan-revisions',json=revision(state,['A02']))
        assert response.status_code==200,response.text
        updated=response.json();assert updated['review_plan']['plan_version']==2
        observed=spans(app,state);assert len(observed)==1
        assert observed[0].attributes['outcome']=='revised' and observed[0].attributes['plan_version']==2
        assert 'approval_id' not in observed[0].attributes
        assert all(s.status!='running' and s.parent_span_id is None for s in app.state.traces.repository.spans(state['root_run_id']))
        assert len(app.state.plan_review.audit.versions(state['id']))==2
        validators=[s for s in app.state.traces.repository.spans(state['root_run_id']) if s.name=='plan_validator']
        assert validators[-1].attributes['validation_role']=='hitl_revise'


@pytest.mark.parametrize('target',['event','reserve_workflow_span','save_span'])
def test_trace_fault_does_not_change_approval(tmp_path,monkeypatch,target):
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client)
        monkeypatch.setattr(app.state.traces.repository,target,lambda *a,**k: (_ for _ in ()).throw(OSError('down')))
        response=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state))
        assert response.status_code==200 and response.json()['status']=='APPROVED'
        assert len(app.state.plan_review.audit.approvals(state['id']))==1


def test_proof_read_failure_preserves_business_and_not_success_span(tmp_path,monkeypatch):
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client)
        monkeypatch.setattr(app.state.plan_review.observations,'_proof',lambda *a: (_ for _ in ()).throw(OSError('proof read down')))
        response=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state))
        assert response.status_code==200 and response.json()['status']=='APPROVED'
        assert spans(app,state)[0].status=='error'
        assert spans(app,state)[0].error_code=='TRACE_COMMIT_UNVERIFIED'


def test_concurrent_replay_classified_at_business_branch(tmp_path):
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client)
        from app.services.plan_review import ApprovalRequest
        request=ApprovalRequest(**approval(state))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:app.state.plan_review.approve_v1(state['id'],request),range(2)))
        assert results[0].engine_approval==results[1].engine_approval
        assert sorted(s.attributes['outcome'] for s in spans(app,state))==['approved','replayed']
        assert len(app.state.plan_review.audit.approvals(state['id']))==1


def test_engine_finish_fencing_gap_is_closed_in_isolated_state(tmp_path):
    """The REQ-0085 isolated drift reproduction is now a rejection regression."""
    app=make(tmp_path)
    with TestClient(app) as client:
        state=create_real(client);approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        request=ExecutionRequest(**execution(approved))
        current=app.state.repository.get(state['id']);engine=app.state.analysis_engine
        claim=app.state.executions.claim(request,current.revision,engine.check_approval)
        result=engine.outcome(claim['execution_id'],request,claim['approval'],claim['started_at'],[],0)
        def branch_drift(s):s.current_plan_version+=1
        app.state.repository.mutate(state['id'],branch_drift)
        with pytest.raises(AppError) as error:app.state.executions.finish(result)
        assert error.value.error.code=='WORKFLOW_EXECUTION_STALE'
        assert app.state.repository.get(state['id']).status.value=='RUNNING'
        with closing(app.state.repository.database.connect()) as conn:
            assert conn.execute('SELECT status FROM executions WHERE id=?',(result.execution_id,)).fetchone()[0]=='running' 


def test_report_attempt_guard_now_fences_changed_plan(tmp_path):
    """Only synthetic Session drift is used; the full observed production path is not enabled."""
    app=create_app(Settings(tmp_path),Provider())
    with TestClient(app) as client:
        state=create_real(client,SALES,'sales.csv',QUERY)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        execution_result=app.state.analysis_engine.execute(ExecutionRequest(**execution(approved)))
        record,fresh=app.state.report_workflow.enqueue(execution_result.execution_id)
        assert fresh
        assert app.state.reports.start(execution_result.execution_id,record.attempt)
        def branch_drift(s):s.current_plan_version+=1
        app.state.repository.mutate(state['id'],branch_drift)
        # The repaired commit primitive rejects the obsolete authorization.
        accepted=app.state.reports.finish(execution_result.execution_id,record.attempt,
            error=AppError('TEST_FAILURE','isolated test').error)
        assert not accepted and app.state.reports.generation(execution_result.execution_id).status=='generating'
        assert not [s for s in app.state.traces.repository.spans(state['root_run_id']) if s.name=='report_persistence']
