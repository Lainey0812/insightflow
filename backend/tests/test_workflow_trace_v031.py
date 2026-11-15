"""Real app/storage with explicit local test transport, not live model acceptance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.models import now
from app.domain.tracing import RunManifest, TraceRun, TraceSpan, TraceEvent
from app.llm.compatible_provider import CompatibleLLMProvider
from app.main import create_app
from app.observability.context import bind_trace,current_trace
from app.observability.recorder import TraceContext,SpanHandle
from app.observability.workflow import register_root
from app.storage.trace_repository import TraceRepository
from intent_fixtures import intent_payload
from workflow_v1_fixtures import ControlledWorkflowProvider,create_real,draft,intent
from test_prompt_registry import calls
from test_report_workflow import Provider as ReportProvider,run as report_run
AUTH={'X-Admin-Token':'read'}
def config(path):return Settings(path,admin_read_token='read')
def root(app,state):return app.state.traces.repository.workflow(state['id'])
def http_provider(control=None,bad_intent=False):
    control=control or ControlledWorkflowProvider();requests=[]
    async def handler(request):
        body=json.loads(request.content);requests.append(body)
        if bad_intent and len(requests)==1:text='not JSON'
        else:
            response=await control.generate(SimpleNamespace(purpose=body['response_format']['json_schema']['name'],instruction=body['messages'][1]['content']))
            text=response.text
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':text}}]})
    return CompatibleLLMProvider('https://test.invalid/v1','qwen3.8-flash',api_key='PRIVATE-KEY',transport=httpx.MockTransport(handler)),requests

def test_normal_preparation_and_two_validator_sites_and_call_links(tmp_path):
    llm,bodies=http_provider();app=create_app(config(tmp_path),llm)
    with TestClient(app) as client:
        state=create_real(client);record=root(app,state);repo=app.state.traces.repository
        assert state['status']=='AWAITING_APPROVAL'
        assert record.kind=='workflow' and record.workflow_run_id==record.run_id and record.execution_id is None
        assert record.status=='suspended' and record.finished_at is None and record.duration_ms is None
        spans=repo.spans(record.run_id)
        assert [s.name for s in spans]==['data_profiler','intent_parser','analysis_planner','plan_validator','plan_validator']
        profiled=next(s for s in spans if s.name=='data_profiler')
        assert isinstance(profiled.attributes['quality_issue_count'], int) and profiled.attributes['file_format'] in ('csv','xlsx')
        assert profiled.attributes['row_count']>0 and profiled.attributes['column_count']>0
        assert all(s.status=='success' and s.started_at and s.finished_at and s.duration_ms>=0 for s in spans)
        planner=next(s for s in spans if s.name=='analysis_planner');validators=[s for s in spans if s.name=='plan_validator']
        assert all(s.parent_span_id is None for s in validators)
        assert [s.node_attempt for s in validators]==[1,2]
        assert [s.attributes['validation_role'] for s in validators]==['planner_output','initial_plan_save']
        records=calls(app.state.llm_captures.repository);assert len(records)==len(bodies)==2
        for call in records:
            span=next(s for s in spans if s.span_id==call.span_id)
            assert call.run_id==record.run_id and span.name==call.node_id and span.attributes['operation_id']==call.operation_id
        assert client.get('/admin/runs',headers=AUTH).json()['total']==0
        assert client.get('/admin/runs?kind=workflow',headers=AUTH).json()['total']==1
        assert client.get('/admin/workflows/'+state['id'],headers=AUTH).json()['run']['run_id']==record.run_id
        assert client.get('/admin/runs/'+record.run_id+'/events',headers=AUTH).json()['items']
        assert client.get('/admin/workflows/'+state['id']).status_code==403 and current_trace() is None

def test_internal_retry_has_one_node_and_distinct_call_attempts(tmp_path):
    llm,_=http_provider(bad_intent=True);app=create_app(config(tmp_path),llm)
    with TestClient(app) as client:
        state=create_real(client);record=root(app,state)
        spans=[s for s in app.state.traces.repository.spans(record.run_id) if s.name=='intent_parser'];assert len(spans)==1
        records=[c for c in calls(app.state.llm_captures.repository) if c.node_id=='intent_parser']
        assert [c.call_sequence for c in records]==[1,2]
        assert records[1].retry_of_call_id==records[0].call_id and records[1].retry_reason=='LLM_INVALID_JSON'
        assert {c.span_id for c in records}=={spans[0].span_id} and all(c.status=='succeeded' for c in records)

def test_clarification_keeps_root_and_old_attempt_and_sequences(tmp_path):
    llm,_=http_provider(ControlledWorkflowProvider([intent_payload('undetermined','clarify'),intent()]))
    app=create_app(config(tmp_path),llm)
    with TestClient(app) as client:
        state=create_real(client,goal='帮我处理一下');first=root(app,state)
        assert first.status=='suspended'
        assert not [s for s in app.state.traces.repository.spans(first.run_id) if s.name=='analysis_planner']
        assert client.post('/api/v1/sessions/'+state['id']+'/clarifications',json={'expected_revision':state['revision'],'answer':'探索销售数据的主要分布'}).status_code==200
        state=client.get('/api/v1/sessions/'+state['id']).json();second=root(app,state)
        assert second.run_id==first.run_id and second.manifest==first.manifest and second.status=='suspended'
        spans=app.state.traces.repository.spans(first.run_id)
        assert [(s.node_attempt,s.status) for s in spans if s.name=='intent_parser']==[(1,'success'),(2,'success')]
        events=app.state.traces.repository.run_events(first.run_id)
        assert [e.sequence for e in events]==list(range(1,len(events)+1))
        assert any(e.event_type=='workflow.suspended' for e in events) and any(e.event_type=='workflow.resumed' for e in events)
        assert len([s for s in spans if s.name=='data_profiler'])==1

def test_timeout_and_checkpoint_retry_preserve_failed_span_and_call(tmp_path):
    control=ControlledWorkflowProvider(planner=lambda _:(_ for _ in ()).throw(httpx.ReadTimeout('PRIVATE-TEXT')))
    llm,_=http_provider(control);app=create_app(config(tmp_path),llm)
    with TestClient(app) as client:
        state=create_real(client);first=root(app,state);repo=app.state.traces.repository
        assert state['status']=='FAILED' and first.status=='error' and first.error_code=='LLM_TIMEOUT'
        old=next(s for s in repo.spans(first.run_id) if s.name=='analysis_planner')
        assert old.status=='error' and old.error_code=='LLM_TIMEOUT' and old.error_message=='模型调用超时。'
        assert next(c for c in calls(app.state.llm_captures.repository) if c.span_id==old.span_id).error_code=='LLM_TIMEOUT'
        control.planner=draft
        assert client.post('/api/v1/sessions/'+state['id']+'/retry-preparation',json={'expected_revision':state['revision']}).status_code==200
        state=client.get('/api/v1/sessions/'+state['id']).json();second=root(app,state)
        assert second.run_id==first.run_id and second.status=='suspended' and repo.span(old.span_id)==old
        assert [(s.node_attempt,s.status) for s in repo.spans(first.run_id) if s.name=='analysis_planner']==[(1,'error'),(2,'success')]
        data=json.dumps([e.model_dump() for e in repo.run_events(first.run_id)],ensure_ascii=False)
        assert 'PRIVATE-TEXT' not in data and 'PRIVATE-KEY' not in data
        assert not [s for s in repo.spans(first.run_id) if s.name in {'analysis_engine','insight_generator'}]

def test_f0_is_not_runtime_failure(tmp_path):
    def unavailable(ctx):
        value=draft(ctx);value['tasks'][0]['steps'][0]['params']['dimensions']=['field_missing'];return value
    llm,_=http_provider(ControlledWorkflowProvider(planner=unavailable));app=create_app(config(tmp_path),llm)
    with TestClient(app) as client:
        state=create_real(client);record=root(app,state)
        assert state['review_plan']['validated_plan']['coverage_status']=='blocked'
        spans=app.state.traces.repository.spans(record.run_id)
        assert all(s.status=='success' for s in spans if s.name in {'analysis_planner','plan_validator'})
        assert next(s for s in spans if s.name=='analysis_planner').attributes['coverage_status']=='blocked'

@pytest.mark.parametrize('method',['create_registered_root','reserve_workflow_span','event','update_run'])
def test_trace_faults_do_not_change_business(tmp_path,monkeypatch,method):
    app=create_app(config(tmp_path),ControlledWorkflowProvider())
    def unavailable(*a,**kw):raise OSError('PRIVATE-STORAGE-DETAIL')
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.traces.repository,method,unavailable)
        state=create_real(client);assert state['status']=='AWAITING_APPROVAL' and not state['engine_execution_ids']
        assert app.state.traces.degraded
        if method=='create':
            gap=client.get('/admin/workflows/'+state['id'],headers=AUTH).json()
            assert gap['availability']=='not_collected' and gap['observation_gap'] is True

def test_historical_missing_and_report_child_association(tmp_path):
    app=create_app(config(tmp_path),ReportProvider())
    with TestClient(app) as client:
        _,result,final=report_run(client);workflow=root(app,final)
        report=app.state.traces.repository.attempt(result['execution_id'],1)
        assert report.kind=='report_generation' and report.workflow_run_id==workflow.run_id
        assert report.manifest.capture_scope=='report_generation' and report.manifest.bindings['execution_id']==result['execution_id']
        response=client.get('/admin/workflows/old-uncollected',headers=AUTH).json()
        assert response['availability']=='not_collected' and response['run'] is None
        assert len(app.state.traces.repository.spans(report.run_id))==6

def test_unique_root_and_concurrent_sequences_and_attempts(tmp_path):
    app=create_app(config(tmp_path),ControlledWorkflowProvider())
    with TestClient(app) as client:
        state=create_real(client);record=root(app,state);repo=app.state.traces.repository;current=app.state.repository.get(state['id'])
        def duplicate(_):return register_root(app.state.traces,current,app.state.intent_parser,app.state.analysis_planner).run_id
        with ThreadPoolExecutor(max_workers=2) as pool:assert set(pool.map(duplicate,range(4)))=={record.run_id}
        def observe(_):
            ctx=TraceContext(app.state.traces,repo.get(record.run_id))
            with ctx.span('parallel_probe'):ctx.event('probe')
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(observe,range(4)))
        assert sorted(s.node_attempt for s in repo.spans(record.run_id) if s.name=='parallel_probe')==[1,2,3,4]
        events=repo.run_events(record.run_id);assert [e.sequence for e in events]==list(range(1,len(events)+1))

def test_restart_interruption_waiting_and_resume_reuse_root(tmp_path):
    control=ControlledWorkflowProvider(planner=lambda _:(_ for _ in ()).throw(AppError('LLM_TIMEOUT','timeout')))
    app=create_app(config(tmp_path),control)
    with TestClient(app) as client:
        initial=create_real(client);record=root(app,initial);repo=app.state.traces.repository;token=client.headers['X-Session-Token']
        def mid_retry(s):s.status=type(s.status).PLANNING;s.error=None
        state=app.state.repository.mutate(initial['id'],mid_retry)
        # Simulate an accepted business retry, not a same-revision late callback.
        record.business_revision=state.revision
        record.status='running';record.finished_at=None;assert repo.update_run(record)
        handle=SpanHandle(TraceContext(app.state.traces,record),'analysis_planner');interrupted_id=handle.record.span_id
    restarted=create_app(config(tmp_path),ControlledWorkflowProvider())
    with TestClient(restarted) as client:
        client.headers['X-Session-Token']=token;repo=restarted.state.traces.repository
        observed=repo.get(record.run_id);span=repo.span(interrupted_id)
        assert observed.status=='suspended' and observed.duration_ms is None and observed.finished_at is None
        assert span.status=='suspended' and span.duration_ms is None and span.finished_at is None
        current=client.get('/api/v1/sessions/'+state.id).json()
        assert client.post('/api/v1/sessions/'+state.id+'/retry-preparation',json={'expected_revision':current['revision']}).status_code==200
        assert repo.workflow(state.id).run_id==record.run_id and repo.workflow(state.id).status=='suspended'
        assert repo.span(interrupted_id).status=='suspended'
    another=create_app(config(tmp_path),ControlledWorkflowProvider())
    with TestClient(another):assert another.state.traces.repository.get(record.run_id).status=='suspended'

def test_old_notnull_schema_migration_preserves_bytes_and_children(tmp_path):
    repo=TraceRepository(tmp_path)
    record=repo.create(TraceRun(run_id='legacy',session_id='s',execution_id='e',attempt=1,owner_instance='old',status='queued',queued_at=now(),manifest=RunManifest(versions={'prompt_version':'old'})))
    span=TraceSpan(span_id='span_old',run_id='legacy',name='evidence_builder',status='running',started_at=now());repo.save_span(span)
    repo.event(TraceEvent(event_id='evt_old',run_id='legacy',span_id='span_old',sequence=1,event_type='span.started',recorded_at=now()))
    with closing(repo.connect()) as conn:
        raw=conn.execute('SELECT record FROM trace_runs WHERE id=?',('legacy',)).fetchone()[0];conn.execute('PRAGMA foreign_keys=OFF')
        conn.executescript('''CREATE TABLE old_shape (id TEXT PRIMARY KEY,execution_id TEXT NOT NULL,attempt INTEGER NOT NULL,queued_at TEXT NOT NULL,status TEXT NOT NULL,record TEXT NOT NULL,UNIQUE(execution_id,attempt));
            INSERT INTO old_shape SELECT * FROM trace_runs;DROP TABLE trace_runs;ALTER TABLE old_shape RENAME TO trace_runs;''')
    migrated=TraceRepository(tmp_path)
    assert migrated.get('legacy')==record and migrated.span('span_old')==span and migrated.run_events('legacy')[0].event_id=='evt_old'
    with closing(migrated.connect()) as conn:
        assert conn.execute('SELECT record FROM trace_runs WHERE id=?',('legacy',)).fetchone()[0]==raw
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert next(r for r in conn.execute('PRAGMA table_info(trace_runs)') if r['name']=='execution_id')['notnull']==0
    assert TraceRepository(tmp_path).get('legacy')==record

@pytest.mark.parametrize('failure',['schema','protocol','node'])
def test_schema_protocol_and_node_errors_are_real_failures_without_secret_text(tmp_path,monkeypatch,failure):
    value=intent();value['analysis_mode']='illegal-mode'
    llm,_=http_provider(ControlledWorkflowProvider([value] if failure=='schema' else [httpx.ReadTimeout('PRIVATE-INTENT')]))
    app=create_app(config(tmp_path),llm)
    if failure=='node':
        def crash(*a,**kw):raise RuntimeError('PRIVATE-NODE-TEXT')
        monkeypatch.setattr(app.state.profiler,'profile',crash)
    with TestClient(app) as client:
        state=create_real(client);record=root(app,state);repo=app.state.traces.repository
        assert state['status']=='FAILED' and record.status=='error'
        spans=repo.spans(record.run_id);failed=next(s for s in spans if s.status=='error')
        assert failed.error_code==('NODE_FAILED' if failure=='node' else 'INTENT_SCHEMA_INVALID' if failure=='schema' else 'LLM_TIMEOUT')
        text=json.dumps([s.model_dump() for s in spans]+[e.model_dump() for e in repo.run_events(record.run_id)],ensure_ascii=False)
        assert 'PRIVATE-' not in text
        assert not [s for s in spans if s.name=='analysis_planner']


def test_task_local_contexts_do_not_mix_two_concurrent_llm_calls(tmp_path):
    llm,_=http_provider();app=create_app(config(tmp_path),llm);repo=app.state.traces.repository
    from planning_fixtures import recruiting_profile
    roots=[repo.create(TraceRun(run_id='root_'+str(i),kind='workflow',workflow_run_id='root_'+str(i),session_id='s'+str(i),
        attempt=1,owner_instance='test',status='running',queued_at=now(),manifest=RunManifest())) for i in range(2)]
    async def one(record):
        context=TraceContext(app.state.traces,record)
        with bind_trace(context),context.span('intent_parser'):
            await asyncio.sleep(0)
            await app.state.intent_parser.parse('探索销售数据',recruiting_profile())
    async def both():await asyncio.gather(*(one(record) for record in roots))
    asyncio.run(both())
    records=calls(app.state.llm_captures.repository);assert len(records)==2
    for call in records:assert repo.span(call.span_id).run_id==call.run_id
    assert {c.run_id for c in records}=={r.run_id for r in roots} and current_trace() is None


def test_actual_cancellation_marks_span_interrupted_not_success(tmp_path):
    repo=TraceRepository(tmp_path)
    record=repo.create(TraceRun(run_id='root',kind='workflow',workflow_run_id='root',session_id='s',attempt=1,
        owner_instance='test',status='running',queued_at=now(),manifest=RunManifest()))
    from app.observability.recorder import TraceRecorder
    from app.observability.workflow import interrupt
    context=TraceContext(TraceRecorder(repo),record)
    async def cancel():
        try:
            with bind_trace(context),context.span('intent_parser'):raise asyncio.CancelledError()
        except asyncio.CancelledError as exc:interrupt(context,exc)
    asyncio.run(cancel())
    assert repo.spans(record.run_id)[0].status=='suspended'
    assert repo.spans(record.run_id)[0].finished_at is not None  # observed cancel, not guessed crash time
    assert repo.get(record.run_id).status=='suspended' and current_trace() is None
