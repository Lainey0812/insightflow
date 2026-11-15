"""Real repositories/workflow; scripted transport is explicitly not a live LLM eval."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.models import now
from app.domain.tracing import RunManifest, TraceRun, TraceSpan, TraceEvent
from app.main import create_app
from app.observability.recorder import TraceRecorder, safe
from app.storage.trace_repository import TraceRepository
from app.reporting.fact_validation import materialize_candidates
from test_report_workflow import Provider, run
from hitl_fixtures import execution
from test_insight_reliability import saved

ADMIN='trace-test-admin-not-a-real-secret'

def settings(path, **kwargs): return Settings(path,admin_read_token=ADMIN,**kwargs)
def headers(): return {'X-Admin-Token':ADMIN}
def listing(client):
    response=client.get('/admin/runs',headers=headers())
    assert response.status_code==200,response.text
    return response.json()['items']
def trace_run(repo, key='exec_test', attempt=1):
    return repo.create(TraceRun(run_id='run_'+key+str(attempt),session_id='session_test',execution_id=key,
        attempt=attempt,owner_instance='test_process',status='queued',queued_at=now(),manifest=RunManifest()))


def test_complete_real_workflow_trace_manifest_steps_idempotency_and_restart(tmp_path):
    p=Provider();app=create_app(settings(tmp_path),p)
    with TestClient(app) as client:
        approved,result,final=run(client)
        item=listing(client)[0]
        assert item['execution_id']==result['execution_id'] and item['session_id']==final['id']
        assert item['status']=='success' and item['report_id']==final['report_generations'][0]['report_id']
        assert item['integrity']=='observed' and item['duration_ms']>=0
        manifest=item['manifest']
        assert manifest['bindings']['dataset_version']==result['dataset_version']
        assert manifest['bindings']['approval_id']==result['approval_id']
        from app.reporting.prompt import PROMPT_VERSION
        assert manifest['versions']['prompt_version'] == PROMPT_VERSION
        assert manifest['versions']['schema_version']=='analysis-report-v1' and manifest['source_sha256']
        assert manifest['raw_content_retained'] is False
        detail=client.get('/admin/runs/'+item['run_id'],headers=headers()).json()
        assert detail['business_source']['status']=='completed' and detail['business_source']['report_status']=='complete'
        spans=client.get('/admin/runs/'+item['run_id']+'/spans',headers=headers()).json()['items']
        assert [s['name'] for s in spans]==['evidence_builder','chart_builder','insight_generator','fact_validator','report_assembler','report_persistence']
        assert all(s['status']=='success' and s['duration_ms']>=0 for s in spans)
        gen=next(s for s in spans if s['name']=='insight_generator')
        assert gen['attributes']['candidate_count']==1 and gen['attributes']['is_mock'] is False
        validator=next(s for s in spans if s['name']=='fact_validator')
        assert validator['attributes']['accepted_count']==1 and validator['attributes']['rejected_count']==0
        events=client.get('/admin/spans/'+validator['span_id']+'/events',headers=headers()).json()['items']
        assert any(e['payload'].get('candidate_status')=='accepted' for e in events)
        assert all(e['run_id']==validator['run_id'] for e in events)
        assert validator['run_id']==item['workflow_run_id']
        assert client.post('/api/v1/executions',json=execution(approved)).json()==result
        assert len(listing(client))==1
        assert client.get('/api/v1/admin/runs',headers=headers()).json()['items']==listing(client)
        stored=[{key:value for key,value in row.items() if key!='user_query'} for row in (item if isinstance(item,list) else [item])]
        raw=json.dumps([stored,spans,events],ensure_ascii=False)
        assert ADMIN not in raw and '华东' not in raw and '济南' not in raw and '原始需求' not in raw
        assert item['user_query'] and '华东' in item['user_query']
    with TestClient(create_app(settings(tmp_path),Provider())) as restarted:
        assert listing(restarted)==[item]
        assert restarted.get('/admin/runs/'+item['run_id'],headers=headers()).status_code==200


def test_failed_llm_and_explicit_retry_preserve_old_attempt(tmp_path):
    p=Provider(report_error=AppError('LLM_TIMEOUT','timeout contains private text',504))
    app=create_app(settings(tmp_path),p)
    with TestClient(app) as client:
        _,result,_=run(client)
        first=listing(client)[0]
        assert first['status']=='error' and first['error_code']=='LLM_TIMEOUT'
        spans=app.state.traces.repository.spans(first['run_id'])
        gen=next(s for s in spans if s.name=='insight_generator')
        assert gen.status=='error' and gen.error_code=='LLM_TIMEOUT' and gen.attributes['candidate_count'] is None
        assert client.get('/api/v1/executions/'+result['execution_id']).json()==result
        p.report_provider.error=None
        response=client.post('/api/v1/executions/'+result['execution_id']+'/report',json={'expected_attempt':1})
        assert response.status_code==202
        items=listing(client)
        assert len(items)==2 and items[0]['retry_of_run_id']==first['run_id'] and items[0]['status']=='success'
        assert items[0]['attempt']==2 and items[1]==first
        detail=client.get('/admin/runs/'+first['run_id'],headers=headers()).json()
        assert detail['business_source']['same_attempt'] is False and detail['business_source']['latest_attempt']==2


class CandidateProvider(Provider):
    def __init__(self,mode):super().__init__();self.mode=mode
    async def generate(self, request):
        response=await super().generate(request)
        if request.purpose=='report_insights_v1':
            if self.mode=='json':return response.model_copy(update={'text':'not JSON'})
            value=json.loads(response.text)
            bad=copy.deepcopy(value['insights'][0]);bad['recommendation_id']='unregistered_option'
            value['insights']=([*value['insights'],bad] if self.mode=='partial' else [bad])
            return response.model_copy(update={'text':json.dumps(value)})
        return response


@pytest.mark.parametrize('mode,status,rule',[('partial','error',None),('bad','error','REPORT_INVALID_RECOMMENDATION'),('json','error',None)])
def test_partial_all_rejected_and_invalid_json(tmp_path,mode,status,rule):
    app=create_app(settings(tmp_path),CandidateProvider(mode))
    with TestClient(app) as client:
        _,result,_=run(client)
        record=listing(client)[0]
        assert record['status']==status
        spans=app.state.traces.repository.spans(record['run_id'])
        if mode=='json':
            assert next(s for s in spans if s.name=='insight_generator').attributes['candidate_count'] is None
        else:
            stage=next(s for s in spans if s.name=='fact_validator')
            assert stage.attributes['rejected_count']==1
            assert stage.attributes['accepted_count']==(1 if mode=='partial' else 0)
            events=app.state.traces.repository.events(stage.span_id)
            rejected=next(e for e in events if e.payload.get('candidate_status')=='rejected')
            if rule:assert rule in rejected.payload['rule_ids']
            assert '盈利能力' not in json.dumps([e.model_dump() for e in events],ensure_ascii=False)
        assert result['execution_status']=='success'


def test_unavailable_skips_llm_and_validation(tmp_path,monkeypatch):
    p=Provider();app=create_app(settings(tmp_path),p)
    spec=app.state.capability_registry.operations['group_aggregate']
    def fail(*args,**kwargs):raise ValueError('kernel test only')
    monkeypatch.setitem(app.state.capability_registry.operations,'group_aggregate',replace(spec,handler=fail))
    with TestClient(app) as client:
        _,result,_=run(client)
        item=listing(client)[0]
        assert item['status']=='error' and item['integrity']=='observed' and not p.report_provider.requests
        spans=app.state.traces.repository.spans(item['run_id'])
        assert all(s.status=='skipped' for s in spans if s.name in {'insight_generator','fact_validator'})
        assert result['execution_status']=='failed'


@pytest.mark.parametrize('configured,token,status',[(False,None,503),(True,None,403),(True,'incorrect',403)])
def test_admin_permission_is_independent_from_session_access(tmp_path,configured,token,status):
    config=settings(tmp_path) if configured else Settings(tmp_path)
    with TestClient(create_app(config,Provider())) as client:
        client.headers['X-Session-Token']='arbitrary-session-token'
        auth={'X-Admin-Token':token} if token else {}
        for path in ['/admin/runs','/admin/runs/unknown','/admin/runs/unknown/spans','/admin/spans/unknown/events','/api/v1/admin/runs']:
            assert client.get(path,headers=auth).status_code==status


def test_admin_bounded_query_and_no_write_endpoint(tmp_path):
    with TestClient(create_app(settings(tmp_path),Provider())) as client:
        assert client.get('/admin/runs',headers=headers()).json()['total']==0
        assert client.get('/admin/runs?limit=1000',headers=headers()).status_code==422
        assert client.get('/admin/runs/unknown',headers=headers()).status_code==404
        assert client.get('/admin/spans/unknown/events',headers=headers()).status_code==404
        assert client.post('/admin/runs',headers=headers()).status_code==405


@pytest.mark.parametrize('method',['create','update_run','save_span','event'])
def test_trace_write_failure_never_fails_successful_business(tmp_path,monkeypatch,method):
    app=create_app(settings(tmp_path),Provider())
    def broken(*a,**k):raise OSError('do not log private data or key')
    monkeypatch.setattr(app.state.traces.repository,method,broken)
    with TestClient(app) as client:
        _,result,final=run(client)
        assert result['execution_status']=='success' and final['report_generations'][0]['status']=='completed'
        assert app.state.traces.degraded is True
        records=listing(client)
        if method not in {'create','update_run'}:assert records[0]['integrity']=='incomplete'


def test_initialization_failure_keeps_business_and_admin_reports_unavailable(tmp_path,monkeypatch):
    def broken(*a,**k):raise OSError('no trace volume')
    monkeypatch.setattr('app.main.TraceRepository',broken)
    app=create_app(settings(tmp_path),Provider())
    with TestClient(app) as client:
        _,result,final=run(client)
        assert result['execution_status']=='success' and final['report_generations'][0]['status']=='completed'
        assert client.get('/admin/runs',headers=headers()).status_code==503


def test_restart_marks_only_unfinished_observations_interrupted(tmp_path):
    app=create_app(settings(tmp_path),Provider(report_error=AppError('LLM_TIMEOUT','test',504)))
    with TestClient(app) as client:
        _,result,_=run(client)
        second,fresh=app.state.report_workflow.enqueue(result['execution_id'],1)
        assert fresh
        context=app.state.traces.start(result['execution_id'],second.attempt)
        # Simulate process death: neither span nor Run gets a normal terminal write.
        stage=TraceSpan(span_id='span_interrupted',run_id=context.run.run_id,name='insight_generator',status='running',started_at=now())
        app.state.traces.repository.save_span(stage)
    with TestClient(create_app(settings(tmp_path),Provider())) as restarted:
        records=listing(restarted)
        assert records[0]['status']=='suspended' and records[0]['duration_ms'] is None
        assert records[0]['finished_at'] is None and records[0]['recovered_at']
        assert records[1]['status']=='error'
        stage=restarted.app.state.traces.repository.span('span_interrupted')
        assert stage.status=='suspended' and stage.duration_ms is None


def test_parallel_contexts_sequences_and_no_cross_run_parent_or_events(tmp_path):
    repo=TraceRepository(tmp_path);recorder=TraceRecorder(repo)
    for key in ['a','b']:trace_run(repo,key)
    async def task(key):
        ctx=recorder.start(key,1)
        with ctx.span('insight_generator') as stage:
            for index in range(4):
                await asyncio.sleep(0)
                stage.event('candidate.validated',candidate_index=index)
        ctx.finish('complete')
        return ctx.run.run_id
    async def both():return await asyncio.gather(task('a'),task('b'))
    ids=asyncio.run(both())
    for rid in ids:
        span=repo.spans(rid)[0];events=repo.events(span.span_id)
        assert len(events)==6 and all(e.run_id==rid for e in events)
        assert len({e.sequence for e in events})==6
    a,b=[repo.spans(rid)[0] for rid in ids]
    with pytest.raises(ValueError):repo.save_span(TraceSpan(span_id='bad',run_id=a.run_id,parent_span_id=b.span_id,name='bad',status='running',started_at=now()))
    with pytest.raises(ValueError):repo.event(TraceEvent(event_id='bad',run_id=a.run_id,span_id=b.span_id,sequence=999,event_type='invalid',recorded_at=now()))


def test_same_attempt_concurrent_claim_has_one_id_and_manifest_immutable(tmp_path):
    repo=TraceRepository(tmp_path)
    from uuid import uuid4
    def claim(_):
        return repo.create(TraceRun(run_id='run_'+uuid4().hex,session_id='session_test',execution_id='exec_same',
            attempt=1,owner_instance='test_process',status='queued',queued_at=now(),manifest=RunManifest()))
    with ThreadPoolExecutor(max_workers=3) as pool:
        runs=list(pool.map(claim,range(3)))
    assert len({r.run_id for r in runs})==1 and repo.runs()[1]==1
    changed=runs[0].model_copy(deep=True);changed.manifest.versions['prompt']='changed'
    with pytest.raises(ValueError):repo.update_run(changed)


def test_candidate_callback_records_rules_and_cannot_change_decisions():
    events=[]
    good,bad=materialize_candidates(*saved('O01'),observer=events.append)
    assert len(good)==1 and len(bad)==1
    assert any('ENDPOINT_NOT_INTERVAL_STABILITY' in e.get('rule_ids',[]) for e in events)
    assert events[-1]['accepted_count']==1 and events[-1]['rejected_count']==1
    def broken(_):raise RuntimeError('observation failure')
    good2,bad2=materialize_candidates(*saved('O01'),observer=broken)
    assert good2==good and bad2==bad


def test_whitelist_and_event_cap_are_explicit_gaps(tmp_path):
    assert safe({'raw_output':'private','instruction':'private','api_key':'secret','rule_ids':['NUMERIC'],'candidate_count':2})=={'rule_ids':['NUMERIC'],'candidate_count':2}
    repo=TraceRepository(tmp_path);trace_run(repo);ctx=TraceRecorder(repo).start('exec_test',1)
    with ctx.span('fact_validator') as stage:
        for index in range(300):stage.event('candidate.validated',candidate_index=index)
    ctx.finish('complete')
    assert repo.get(ctx.run.run_id).integrity=='incomplete'
    with closing(repo.connect()) as conn:assert conn.execute('SELECT COUNT(*) FROM trace_events').fetchone()[0]==256


def test_two_report_workflows_can_overlap_without_candidate_mixing(tmp_path,monkeypatch):
    from uuid import uuid4
    monkeypatch.setattr('test_report_workflow.execution',lambda state:{**execution(state),'execution_request_id':uuid4().hex})
    p=Provider(report_error=AppError('LLM_TIMEOUT','first attempts only',504))
    app=create_app(settings(tmp_path),p)
    with TestClient(app) as client:
        _,first,_=run(client);_,second,_=run(client)
        ids=[first['execution_id'],second['execution_id']]
        for eid in ids:app.state.report_workflow.enqueue(eid,1)
        p.report_provider.error=None
        async def generate():
            await asyncio.gather(*(app.state.report_workflow.generate(eid,2) for eid in ids))
        asyncio.run(generate())
        records=listing(client)
        for eid in ids:
            current=next(r for r in records if r['execution_id']==eid and r['attempt']==2)
            assert current['status']=='success'
            assert current['retry_of_run_id']==next(r['run_id'] for r in records if r['execution_id']==eid and r['attempt']==1)
            stages=app.state.traces.repository.spans(current['run_id'])
            assert all(s.run_id==current['workflow_run_id'] and s.parent_span_id is None for s in stages)
            assert next(s for s in stages if s.name=='fact_validator').attributes['accepted_count']==1


def test_core_coverage_failure_still_reports_accepted_candidate_count():
    draft,evidence,tasks,tables,limits=saved('R03')
    primary=evidence[0]
    extra=primary.model_copy(update={'task_id':'A_EXTRA','evidence_id':'E_EXTRA'})
    tasks={**tasks,'A_EXTRA':next(iter(tasks.values())).model_copy(update={'task_id':'A_EXTRA','priority':'P0'})}
    events=[]
    with pytest.raises(AppError) as error:materialize_candidates(draft,[*evidence,extra],tasks,tables,limits,observer=events.append)
    assert error.value.error.code=='REPORT_CORE_FINDINGS_MISSING'
    assert events[-1]['accepted_count']>0


def test_observation_gap_in_one_run_does_not_mark_another_run_incomplete(tmp_path,monkeypatch):
    repo=TraceRepository(tmp_path);recorder=TraceRecorder(repo)
    trace_run(repo,'a');trace_run(repo,'b')
    original=repo.event
    def flaky(event):
        if event.run_id=='run_a1':raise OSError('one run only')
        return original(event)
    monkeypatch.setattr(repo,'event',flaky)
    a=recorder.start('a',1);a.finish('complete')
    b=recorder.start('b',1);b.finish('complete')
    assert repo.get(a.run.run_id).integrity=='incomplete'
    assert repo.get(b.run.run_id).integrity=='observed'


def test_report_persistence_failure_is_not_observed_as_success(tmp_path,monkeypatch):
    app=create_app(settings(tmp_path),Provider());original=app.state.reports.finish
    def fail_save(*args,**kwargs):
        if kwargs.get('report'):raise AppError('REPORT_STORAGE_FAILED','storage test only',503)
        return original(*args,**kwargs)
    monkeypatch.setattr(app.state.reports,'finish',fail_save)
    with TestClient(app) as client:
        _,result,final=run(client)
        assert result['execution_status']=='success' and final['report_generations'][0]['status']=='failed'
        observed=listing(client)[0]
        assert observed['status']=='error' and observed['error_code']=='REPORT_STORAGE_FAILED'
        spans=app.state.traces.repository.spans(observed['run_id'])
        assert next(s for s in spans if s.name=='report_assembler').status=='success'
        assert next(s for s in spans if s.name=='report_persistence').status=='error'


def test_trace_disabled_does_not_block_business(tmp_path):
    with TestClient(create_app(settings(tmp_path,trace_enabled=False),Provider())) as client:
        _,_,final=run(client)
        assert final['report_generations'][0]['status']=='completed'
        assert client.get('/admin/runs',headers=headers()).status_code==503


def test_nested_spans_and_event_replay_contract(tmp_path):
    repo=TraceRepository(tmp_path);trace_run(repo);ctx=TraceRecorder(repo).start('exec_test',1)
    with ctx.span('report_assembler') as outer:
        with ctx.span('nested') as inner:
            assert inner.record.parent_span_id==outer.record.span_id
    ctx.finish('complete')
    event=repo.events(inner.record.span_id)[0]
    repo.event(event)
    with pytest.raises(ValueError):repo.event(event.model_copy(update={'event_type':'different'}))
