"""Read-only business/Trace projections; synthetic HTTP transport is declared in fixtures."""
from contextlib import closing
import hashlib,json
from fastapi.testclient import TestClient
from test_trace_closure_c2 import application,AUTH
from test_report_workflow import run


def rows(app):
    result={}
    for name,connect in [('business',app.state.repository.database.connect),('trace',app.state.traces.repository.connect)]:
        with closing(connect()) as conn:
            tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            result[name]=hashlib.sha256(json.dumps({t:[tuple(r) for r in conn.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables},sort_keys=True).encode()).hexdigest()
    return result


def test_list_detail_business_success_sorted_nodes_and_readonly(tmp_path):
    app=application(tmp_path)
    with TestClient(app) as client:
        _,_,session=run(client);before=rows(app)
        page=client.get('/admin/workflow-observability',headers=AUTH).json()
        assert page['total']==1 and page['items'][0]['business_lifecycle']['status']=='succeeded',page
        detail=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH).json()
        assert detail['duration_ms']>=0 and detail['collection']['status']=='observed'
        assert len(detail['trace']['nodes'])==14 and len(detail['trace']['llm_calls'])==3
        intent=next(n for n in detail['trace']['nodes'] if n['name']=='intent_parser')
        assert intent['intent_result']['parse_id']==intent['attributes']['operation_id']
        assert set(intent['intent_result']['analysis_goal'])=={'analysis_object','business_goal','decision_goal'}
        assert all('intent_result' not in n for n in detail['trace']['nodes'] if n['name']!='intent_parser')
        planner=next(n for n in detail['trace']['nodes'] if n['name']=='analysis_planner')
        assert planner['planner_result']['plan']['tasks'] and planner['planner_result']['approval_required'] is True
        assert all('planner_result' not in n for n in detail['trace']['nodes'] if n['name']!='analysis_planner')
        saved=next(n for n in detail['trace']['nodes'] if n['name']=='plan_validator' and n['attributes'].get('validation_role')=='initial_plan_save')
        assert saved['validator_view']['corrected_plan'] is None and saved['validator_view']['validation_results']
        engine=next(n for n in detail['trace']['nodes'] if n['name']=='analysis_engine')
        assert engine['execution_view']['rows_omitted'] is True and all('rows' not in task for task in engine['execution_view']['tasks'])
        hitl=next(n for n in detail['trace']['nodes'] if n['name']=='hitl')
        assert hitl['approval_view']['matched_approval'] is True and hitl['approval_view']['decision']['approval_id']
        approve_check=next(n for n in detail['trace']['nodes'] if n['name']=='plan_validator' and n['attributes'].get('validation_role')=='hitl_approve')
        line=approve_check['validator_view']['version_line']
        assert approve_check['validator_view']['plan_brief']['tasks']
        assert line['validated_plan_version']==line['approved_plan_version']==line['executed_plan_version']
        assert hitl['approval_view']['approved_plan']['plan_version']==line['approved_plan_version']
        assert hitl['approval_view']['submitted_plan']['tasks']
        assert all(task.get('rule') is not None and 'rows' not in task for task in engine['execution_view']['tasks'])
        assembled=next(n for n in detail['trace']['nodes'] if n['name']=='report_assembler')
        assert assembled['report_view']['result_rows_omitted'] is True and 'result_data' not in assembled['report_view']
        assert detail['trace']['nodes']==sorted(detail['trace']['nodes'],key=lambda n:(n['started_at'],n['span_id']))
        assert detail['trace']['root']['status']=='suspended'
        assert detail['business_lifecycle']['status']=='succeeded'
        assert client.get('/admin/workflow-observability?status=failed',headers=AUTH).json()['total']==0
        assert client.get('/admin/workflow-observability?workflow_id=unknown',headers=AUTH).json()['items']==[]
        assert client.get('/admin/workflow-observability?session_id='+session['id'],headers=AUTH).json()['total']==1
        assert client.get('/admin/workflow-observability?limit=1&offset=1',headers=AUTH).json()['items']==[]
        assert client.get('/admin/workflow-observability?limit=0',headers=AUTH).status_code==422
        assert client.get('/admin/workflow-observability?status=imaginary',headers=AUTH).status_code==422
        assert rows(app)==before
        assert client.get('/admin/workflow-observability').status_code==403
        assert client.get('/admin/workflow-observability/'+session['workflow_id']).status_code==403


def test_trace_down_keeps_business_delivery(tmp_path,monkeypatch):
    app=application(tmp_path)
    with TestClient(app) as client:
        _,_,session=run(client)
        monkeypatch.setattr(app.state.traces.repository,'connect',lambda: (_ for _ in ()).throw(OSError('down')))
        response=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH)
        assert response.status_code==200,response.text
        detail=response.json()
        assert detail['business_lifecycle']['status']=='succeeded'
        assert detail['business_lifecycle']['report_delivery']=='delivered'
        assert detail['trace']['reports'][0]['report_id']==session['report_generations'][0]['report_id']
        assert detail['collection']['status']=='incomplete' and detail['trace']['nodes']==[]
        assert any(f['category']=='executed_trace_missing' for f in detail['collection']['findings'])


def test_inconsistent_trace_retains_independent_business_result(tmp_path,monkeypatch):
    from app.domain.errors import AppError
    app=application(tmp_path)
    with TestClient(app) as client:
        _,_,session=run(client)
        monkeypatch.setattr(app.state.workflow_trace,'get',lambda _: (_ for _ in ()).throw(AppError('WORKFLOW_TRACE_IDENTITY_MISMATCH','unsafe',409)))
        response=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH)
        assert response.status_code==200,response.text
        detail=response.json()
        assert detail['business_lifecycle']['status']=='succeeded' and detail['trace'] is None
        assert detail['collection']['findings'][0]['category']=='inconsistent'


def test_status_filter_is_before_stable_pagination(tmp_path):
    from workflow_v1_fixtures import create_real
    from test_report_workflow import SALES,QUERY
    app=application(tmp_path)
    with TestClient(app) as client:
        _,_,completed=run(client)
        waiting=create_real(client,SALES,'other.csv',QUERY)
        query='/admin/workflow-observability'
        first=client.get(query+'?limit=1&offset=0',headers=AUTH).json()
        second=client.get(query+'?limit=1&offset=1',headers=AUTH).json()
        assert first['total']==second['total']==2
        assert first['items'][0]['workflow_id']==waiting['workflow_id']
        assert second['items'][0]['workflow_id']==completed['workflow_id']
        only=client.get(query+'?status=succeeded&limit=1',headers=AUTH).json()
        assert only['total']==1 and only['items'][0]['workflow_id']==completed['workflow_id']
        assert client.get(query+'?workflow_id='+completed['workflow_id'][:-1],headers=AUTH).json()['total']==0
        assert client.post(query,json={},headers=AUTH).status_code==405


def test_report_failure_business_status_does_not_depend_on_trace(tmp_path,monkeypatch):
    from test_report_workflow import Provider
    from app.domain.errors import AppError
    app=application(tmp_path,Provider(report_error=AppError('LLM_TIMEOUT','unit timeout',504)))
    with TestClient(app) as client:
        _,_,session=run(client)
        monkeypatch.setattr(app.state.traces.repository,'connect',lambda: (_ for _ in ()).throw(OSError('down')))
        data=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH).json()
        assert data['business_lifecycle']['status']=='partially_succeeded'
        assert data['business_lifecycle']['execution_status']=='success'
        assert data['business_lifecycle']['report_delivery']=='not_delivered'
        assert 'report_failed' in data['reason_codes'] and data['has_exception']


def test_explicit_skip_events_are_distinct_from_missing_trace(tmp_path,monkeypatch):
    app=application(tmp_path)
    def unavailable(task,*args):
        failure=app.state.analysis_engine.skipped(task.task_id,'UNIT_FAILURE','unit failure')
        return failure.model_copy(update={'status':'failed'}),None,None,0
    monkeypatch.setattr(app.state.analysis_engine.runner,'run',unavailable)
    with TestClient(app) as client:
        _,_,session=run(client)
        data=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH).json()
        skips=[f for f in data['collection']['findings'] if f['category']=='not_executed']
        assert {f['node_key'] for f in skips}=={'insight_generator','fact_validator'}
        assert data['collection']['status']=='observed'
        assert not any(n['name']=='insight_generator' for n in data['trace']['nodes'])


def test_claim_without_node_start_does_not_assert_engine_has_executed(tmp_path):
    from workflow_v1_fixtures import create_real
    from test_report_workflow import SALES,QUERY
    from hitl_fixtures import approval,execution
    from app.domain.execution import ExecutionRequest
    app=application(tmp_path)
    with TestClient(app) as client:
        state=create_real(client,SALES,'sales.csv',QUERY)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        current=app.state.repository.get(state['id'])
        app.state.executions.claim(ExecutionRequest(**execution(approved)),current.revision,app.state.analysis_engine.check_approval)
        data=client.get('/admin/workflow-observability/'+state['workflow_id'],headers=AUTH).json()
        assert any(f['code']=='EXECUTION_SPAN_NOT_COLLECTED' and f['category']=='unknown' for f in data['collection']['findings'])
        assert not any(n['name']=='analysis_engine' for n in data['trace']['nodes'])


def test_concurrent_business_revision_change_is_not_silently_combined(tmp_path,monkeypatch):
    app=application(tmp_path)
    with TestClient(app) as client:
        _,_,session=run(client)
        original=app.state.workflow_trace.get
        def changed(workflow_id):
            data=original(workflow_id)
            app.state.repository.mutate(session['id'],lambda s:setattr(s,'title','unit concurrent update'))
            return data
        monkeypatch.setattr(app.state.workflow_trace,'get',changed)
        data=client.get('/admin/workflow-observability/'+session['workflow_id'],headers=AUTH).json()
        assert data['business_lifecycle']['status']=='unknown'
        assert data['consistency']['status']=='unknown'
        assert any(f['code']=='SESSION_CHANGED_DURING_READ' for f in data['collection']['findings'])


def test_engine_partial_is_an_exception_even_while_report_is_queued_and_trace_is_down(tmp_path,monkeypatch):
    from app.main import create_app
    from app.core.config import Settings
    from app.domain.execution import ExecutionRequest
    from workflow_v1_fixtures import ControlledWorkflowProvider,create_real
    from hitl_fixtures import approval,execution
    app=create_app(Settings(tmp_path,admin_read_token='read'),ControlledWorkflowProvider())
    original=app.state.analysis_engine.runner.run
    def partial(task,*args):
        if task.task_id=='A02':
            failure=app.state.analysis_engine.skipped(task.task_id,'UNIT_FAILURE','unit failure')
            return failure.model_copy(update={'status':'failed'}),None,None,0
        return original(task,*args)
    monkeypatch.setattr(app.state.analysis_engine.runner,'run',partial)
    with TestClient(app) as client:
        state=create_real(client)
        approved=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state)).json()
        result=app.state.analysis_engine.execute(ExecutionRequest(**execution(approved)))
        app.state.report_workflow.enqueue(result.execution_id)
        app.state.traces.repository=None
        data=client.get('/admin/workflow-observability/'+state['workflow_id'],headers=AUTH).json()
        assert data['business_lifecycle']['execution_status']=='partial_success'
        assert data['business_lifecycle']['report_generation_status']=='queued'
        assert data['has_exception'] is True
