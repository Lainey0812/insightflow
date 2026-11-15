"""Real services and HTTP assembly with local scripted transport, never a model quality evaluation."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.prompt_registry import LLMCallRecord
from app.llm.base import LLMRequest
from app.llm.capture import CallRecorder
from app.llm.compatible_provider import CompatibleLLMProvider
from app.llm.templates import _source
from app.main import create_app
from app.observability.provenance import digest
from app.observability.recorder import TraceRecorder, TraceContext
from app.domain.tracing import TraceRun, RunManifest
from app.planning.capabilities import CapabilityRegistry
from app.services.intent_parser import IntentParserService
from app.services.analysis_planner import AnalysisPlannerService
from app.services.analysis_report import AnalysisReportService
from app.storage.prompt_registry import PromptRegistryRepository, template_content
from app.storage.trace_repository import TraceRepository
from intent_fixtures import intent_payload
from planning_fixtures import recruiting_profile, task
from report_fixtures import report_case, ReportProvider


def provider(tmp_path, outputs=None, *, recorder=None):
    bodies = []
    outputs = outputs or [intent_payload(business_goal='比较城市岗位数量')]
    async def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        selected = outputs[min(len(bodies)-1,len(outputs)-1)]
        if isinstance(selected,int): return httpx.Response(selected,json={'error':'private supplier detail'})
        if callable(selected): selected = selected(body)
        if asyncio.iscoroutine(selected): selected=await selected
        text = selected if isinstance(selected,str) else json.dumps(selected,ensure_ascii=False)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':text}}]})
    repo = PromptRegistryRepository(tmp_path/'registry')
    capture = recorder or CallRecorder(repo)
    llm = CompatibleLLMProvider('https://local-test.invalid/v1','qwen3.8-flash',api_key='secret-not-for-snapshot',
                                transport=httpx.MockTransport(handler),capture=capture)
    return llm,repo,bodies


def calls(repo):
    with repo.connect() as conn:
        return [LLMCallRecord.model_validate_json(r[0]) for r in conn.execute('SELECT record FROM llm_calls ORDER BY rowid')]


def report_output(body):
    from report_fixtures import selection_output
    return selection_output(json.loads(body['messages'][1]['content']))


@pytest.mark.parametrize('node',['intent','planner','report'])
def test_actual_http_body_equals_persisted_snapshot_and_restart(tmp_path,node):
    output = intent_payload(business_goal='比较城市岗位数量') if node=='intent' else ({'tasks':[task()]} if node=='planner' else report_output)
    llm,repo,bodies=provider(tmp_path,[output])
    profile=recruiting_profile()
    if node=='intent':
        service=IntentParserService(llm,enable_thinking=False)
        result=asyncio.run(service.parse('比较城市岗位数量',profile))
        assert result.next_action=='proceed'
    elif node=='planner':
        service=AnalysisPlannerService(llm,CapabilityRegistry())
        intent=report_case()[0]
        result=asyncio.run(service.plan(intent,profile))
        assert result.coverage_status=='complete'
    else:
        service=AnalysisReportService(llm,CapabilityRegistry())
        result=asyncio.run(service.generate(*report_case()))
        assert result.insights
    record=calls(repo)[0]
    restarted=PromptRegistryRepository(tmp_path/'registry')
    assert restarted.call(record.call_id)==record
    snapshot=restarted.snapshot(record.request_snapshot_id)
    assert restarted.payload(snapshot.payload_ref)==bodies[0]
    assert snapshot.messages_hash==digest(bodies[0]['messages'])
    assert snapshot.schema_hash==digest(bodies[0]['response_format'])
    assert snapshot.request_hash==digest(bodies[0])
    assert snapshot.model_parameters['model']=='qwen3.8-flash'
    assert snapshot.client_config['timeout_seconds']==30
    template=restarted.template(record.template_snapshot_id)
    assert template.system_template==bodies[0]['messages'][0]['content']
    assert template.content_hash==digest(template_content(template))
    assert record.status=='succeeded' and record.duration_ms>=0
    assert record.run_id is None and record.span_id is None
    assert 'secret-not-for-snapshot' not in json.dumps(bodies)
    assert 'Authorization' not in str(restarted.payload(snapshot.payload_ref))
    assert repo.path.stat().st_mode & 0o777 == 0o600
    assert repo.path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('node',['intent','planner'])
def test_each_retry_is_distinct_same_template_with_reason(tmp_path,node):
    valid=intent_payload(business_goal='比较城市岗位数量') if node=='intent' else {'tasks':[task()]}
    llm,repo,bodies=provider(tmp_path,['not JSON',valid])
    if node=='intent':
        asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    else:
        asyncio.run(AnalysisPlannerService(llm,CapabilityRegistry()).plan(report_case()[0],recruiting_profile()))
    a,b=calls(repo)
    assert a.operation_id==b.operation_id and [a.call_sequence,b.call_sequence]==[1,2]
    assert [a.retry_index,b.retry_index]==[0,1]
    assert b.retry_reason in {'LLM_INVALID_JSON','PLANNER_INVALID_JSON'}
    assert b.retry_of_call_id==a.call_id
    assert a.template_snapshot_id==b.template_snapshot_id
    assert a.request_snapshot_id!=b.request_snapshot_id and a.call_id!=b.call_id
    assert a.status==b.status=='succeeded'  # HTTP/protocol success, not consumer Schema success.
    assert 'validation_feedback' not in json.loads(bodies[0]['messages'][1]['content'])
    assert 'validation_feedback' in json.loads(bodies[1]['messages'][1]['content'])


def test_dynamic_evidence_schema_and_multiple_calls_share_template(tmp_path):
    llm,repo,bodies=provider(tmp_path,[report_output])
    service=AnalysisReportService(llm,CapabilityRegistry())
    asyncio.run(service.generate(*report_case()))
    asyncio.run(service.generate(*report_case(tasks=[task(tid='A01'),task(tid='A02')])))
    a,b=calls(repo)
    assert a.template_snapshot_id==b.template_snapshot_id
    assert repo.snapshot(a.request_snapshot_id).schema_hash!=repo.snapshot(b.request_snapshot_id).schema_hash
    for body in bodies:
        ids=[e['evidence_id'] for e in json.loads(body['messages'][1]['content'])['evidence']]
        assert body['response_format']['json_schema']['schema']['$defs']['SelectedInsight']['properties']['primary_evidence_id']['enum']==ids


def test_template_idempotency_order_independent_hash_and_version_conflict(tmp_path):
    llm,repo,_=provider(tmp_path)
    template=IntentParserService(llm).prompt_source.snapshot
    first=repo.register(template)
    assert repo.register(template.model_copy(update={'created_at':'another time'}))==first
    assert digest({'b':2,'a':1})==digest({'a':1,'b':2})
    changed=template.model_copy(update={'system_template':template.system_template+'changed'})
    sha=digest(template_content(changed))
    changed=changed.model_copy(update={'content_hash':sha,'template_snapshot_id':'pt_'+sha})
    with pytest.raises(AppError) as error:repo.register(changed)
    assert error.value.error.code=='PROMPT_VERSION_CONFLICT'
    assert repo.template(first.template_snapshot_id)==first
    with pytest.raises(sqlite3.IntegrityError),repo.connect() as conn:
        conn.execute('UPDATE prompt_templates SET version=? WHERE id=?',('illegal',first.template_snapshot_id))


def test_import_binding_mismatch_fails_before_http(tmp_path,monkeypatch):
    llm,repo,bodies=provider(tmp_path)
    service=IntentParserService(llm)
    import app.intent.prompt as prompt
    monkeypatch.setattr(prompt,'SYSTEM_PROMPT',prompt.SYSTEM_PROMPT+'changed-in-memory')
    with pytest.raises(AppError) as error:asyncio.run(service.parse('比较城市岗位数量',recruiting_profile()))
    assert error.value.error.code=='PROMPT_SOURCE_MISMATCH'
    assert not bodies and not calls(repo)


def test_loaded_old_code_cannot_be_claimed_as_current_source(tmp_path):
    path=tmp_path/'isolated_source.py'
    path.write_text('def render():\n    return "old"\n')
    spec=importlib.util.spec_from_file_location('isolated_source',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    path.write_text('def render():\n    return "new"\n')
    with pytest.raises(AppError) as error:_source(module)
    assert error.value.error.code=='PROMPT_SOURCE_MISMATCH'


def test_begin_failure_blocks_network_and_preserves_clear_error(tmp_path,monkeypatch,caplog):
    llm,repo,bodies=provider(tmp_path)
    service=IntentParserService(llm)
    def fail(*args):raise OSError('secret-not-for-snapshot private data')
    monkeypatch.setattr(repo,'begin',fail)
    with pytest.raises(AppError) as error:asyncio.run(service.parse('比较城市岗位数量',recruiting_profile()))
    assert error.value.error.code=='LLM_SNAPSHOT_UNAVAILABLE'
    assert not bodies and not calls(repo)
    assert 'secret-not-for-snapshot' not in caplog.text


def test_finish_failure_never_returns_success_and_recovery_is_explicit(tmp_path,monkeypatch):
    llm,repo,bodies=provider(tmp_path)
    service=IntentParserService(llm)
    def fail(*args):raise OSError('disk unavailable')
    monkeypatch.setattr(repo,'finish',fail)
    with pytest.raises(AppError) as error:asyncio.run(service.parse('比较城市岗位数量',recruiting_profile()))
    assert error.value.error.code=='LLM_CAPTURE_FINALIZE_FAILED' and len(bodies)==1
    assert calls(repo)[0].status=='running'
    restarted=PromptRegistryRepository(tmp_path/'registry');restarted.recover()
    assert calls(restarted)[0].status=='interrupted'


def test_http_error_saved_without_private_response_body(tmp_path):
    llm,repo,bodies=provider(tmp_path,[503])
    with pytest.raises(AppError):asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    record=calls(repo)[0]
    assert record.status=='failed' and record.error_code=='LLM_HTTP_ERROR'
    assert 'private supplier detail' not in record.model_dump_json()


def test_concurrent_calls_do_not_share_operation_or_payload(tmp_path):
    llm,repo,bodies=provider(tmp_path)
    service=IntentParserService(llm)
    async def run():return await asyncio.gather(*(service.parse(f'比较城市岗位数量，测试{i}',recruiting_profile()) for i in range(6)))
    asyncio.run(run())
    records=calls(repo)
    assert len({r.call_id for r in records})==len({r.operation_id for r in records})==6
    assert len({r.template_snapshot_id for r in records})==1
    recorded=[repo.payload(r.request_snapshot_id) for r in records]
    assert {digest(p) for p in recorded}=={digest(p) for p in bodies}


def test_timeout_records_cancelled_call(tmp_path):
    async def slow(body):
        await asyncio.sleep(.5)
        return intent_payload()
    llm,repo,_=provider(tmp_path,[slow])
    service=IntentParserService(llm,timeout_seconds=.2)
    with pytest.raises(AppError) as error:asyncio.run(service.parse('比较城市岗位数量',recruiting_profile()))
    assert error.value.error.code=='LLM_TIMEOUT'
    assert calls(repo)[0].status=='cancelled'


def test_guards_and_no_evidence_do_not_invent_model_calls(tmp_path):
    llm,repo,bodies=provider(tmp_path)
    assert asyncio.run(IntentParserService(llm).parse(' ',recruiting_profile())).parse_origin=='input_guard'
    assert asyncio.run(AnalysisReportService(llm,CapabilityRegistry()).generate(*report_case(failures=('A01',)))).report_status=='unavailable'
    assert not calls(repo) and not bodies


def test_body_mismatch_and_missing_template_are_rejected(tmp_path):
    llm,repo,bodies=provider(tmp_path)
    with pytest.raises(AppError) as error:asyncio.run(llm.generate(LLMRequest(purpose='test',instruction='x',response_schema={})))
    assert error.value.error.code=='LLM_TEMPLATE_REQUIRED'
    source=IntentParserService(llm).prompt_source
    request=LLMRequest(purpose='intent_v1',instruction='{}',system_prompt='wrong',response_schema={},call_binding=source.binding('binding-test'))
    with pytest.raises(AppError) as error:asyncio.run(llm.generate(request))
    assert error.value.error.code=='PROMPT_CONTENT_MISMATCH' and not bodies


def test_retention_removes_only_payload_not_metadata_or_template(tmp_path):
    llm,repo,_=provider(tmp_path)
    llm.capture.retention_days=1
    asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    record=calls(repo)[0]
    with repo.connect() as conn:
        # Expiration fixture replaces only the policy clock in the read query via an already-expired insertion.
        conn.execute('DELETE FROM llm_request_payloads WHERE snapshot_id=?',(record.request_snapshot_id,))
        conn.execute('INSERT INTO llm_request_payloads VALUES (?,?,?)',(record.request_snapshot_id,'{}',(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()))
    assert repo.payload(record.request_snapshot_id) is None
    assert repo.prune_expired()==1
    assert repo.call(record.call_id)==record and repo.snapshot(record.request_snapshot_id)
    assert repo.template(record.template_snapshot_id)


def trace_fixture(tmp_path):
    traces=TraceRecorder(TraceRepository(tmp_path/'observability'))
    run=TraceRun(run_id='run-test',session_id='session-test',execution_id='exec-test',attempt=1,
        owner_instance='test',status='running',queued_at='2026-10-29T00:00:00+00:00',manifest=RunManifest())
    traces.repository.create(run)
    return traces,TraceContext(traces,run)


def test_report_span_call_link_and_trace_write_failure_is_independent(tmp_path,monkeypatch):
    llm,repo,_=provider(tmp_path,[report_output])
    traces,context=trace_fixture(tmp_path)
    service=AnalysisReportService(llm,CapabilityRegistry())
    result=asyncio.run(service.generate(*report_case(),trace=context))
    record=calls(repo)[0]
    assert record.run_id=='run-test' and record.span_id
    assert traces.repository.span(record.span_id).name=='insight_generator'
    events=traces.repository.events(record.span_id)
    assert any(e.payload.get('call_id')==record.call_id for e in events)
    def fail(*args):raise OSError('trace unavailable')
    monkeypatch.setattr(traces.repository,'event',fail)
    second=asyncio.run(service.generate(*report_case(),trace=context))
    assert second.insights and result.insights and calls(repo)[1].status=='succeeded'
    assert traces.degraded


def test_admin_metadata_raw_authorization_and_legacy_unavailable(tmp_path):
    llm,_,_=provider(tmp_path/'transport')
    app=create_app(Settings(tmp_path/'app',admin_read_token='read',admin_snapshot_token='raw'),provider=llm)
    with TestClient(app) as client:
        asyncio.run(app.state.intent_parser.parse('比较城市岗位数量',recruiting_profile()))
        repo=app.state.llm_captures.repository;record=calls(repo)[0]
        url='/admin/llm-calls/'+record.call_id
        assert client.get(url).status_code==403
        metadata=client.get(url,headers={'X-Admin-Token':'read'})
        assert metadata.status_code==200 and 'messages' not in metadata.json()
        assert client.get(url+'/request',headers={'X-Admin-Token':'read'}).status_code==403
        raw=client.get(url+'/request',headers={'X-Admin-Token':'read','X-Admin-Snapshot-Token':'raw'})
        assert raw.status_code==200 and raw.headers['cache-control']=='no-store'
        assert raw.json()['payload']['messages'][0]['role']=='system'
        run=TraceRun(run_id='legacy',session_id='session',execution_id='exec',attempt=1,owner_instance='old',
            status='complete',queued_at='2026-10-28T00:00:00+00:00',manifest=RunManifest())
        app.state.traces.repository.create(run)
        missing=client.get('/admin/runs/legacy/llm-calls',headers={'X-Admin-Token':'read'})
        assert missing.json()['availability']=='unavailable' and missing.json()['items']==[]


@pytest.mark.parametrize('node,baseline',[('intent','I01-first'),('planner','P01-first'),('report','R01-imported')])
def test_request_body_unchanged_from_frozen_preimplementation_capture(tmp_path,node,baseline):
    from app.domain.intent import ParsedIntent
    historical=Path(__file__).resolve().parents[2]/'docs/audits/prompt-loading-paths-2026-10-29/captures-v3'
    expected=json.loads((historical/(baseline+'.json')).read_text())['calls'][0]['request']
    good=intent_payload(business_goal='比较城市岗位数量',analysis_object='招聘数据')
    output=good if node=='intent' else ({'tasks':[task()]} if node=='planner' else report_output)
    llm,repo,bodies=provider(tmp_path,[output])
    if node=='intent':
        asyncio.run(IntentParserService(llm,enable_thinking=False).parse('比较城市岗位数量',recruiting_profile(),['保留全部城市']))
    elif node=='planner':
        asyncio.run(AnalysisPlannerService(llm,CapabilityRegistry()).plan(ParsedIntent.model_validate(good),recruiting_profile()))
    else:
        asyncio.run(AnalysisReportService(llm,CapabilityRegistry()).generate(*report_case()))
    if node != 'report':
        assert bodies == [expected]
    else:
        # REQ-0090 deliberately versions the Report prompt and dynamic schema.
        # Keep the historical capture intact; verify the exact authorized delta
        # and that Registry captured the actual request, not a reconstruction.
        from app.reporting.prompt import SYSTEM_PROMPT
        current = bodies[0]
        assert current['model'] == expected['model']
        assert current['enable_thinking'] == expected['enable_thinking']
        assert current['messages'][0] == {'role': 'system', 'content': SYSTEM_PROMPT}
        old_input = json.loads(expected['messages'][1]['content'])
        new_input = json.loads(current['messages'][1]['content'])
        assert set(new_input) == set(old_input) | {'required_core_groups', 'required_metric_groups', 'primary_evidence_options', 'allowed_limitations', 'draft_schema_version', 'recommendation_options', 'limitation_pool'}
        for key in set(old_input) - {'limitations', 'scope_context'}:
            assert new_input[key] == old_input[key]
        # REQ-0093 makes the existing row-count basis explicit; no statistical
        # operation or other runtime input is changed by this display statement.
        before_scope = new_input['scope_context']
        normalized = [{**group, 'approved_steps': [line for line in group['approved_steps']
            if line != '按上传记录逐行计数，不代表去重后的业务实体数量。']} for group in before_scope]
        assert normalized == old_input['scope_context']
        assert set(old_input['limitations']) <= set(new_input['limitations'])
        assert new_input['required_core_groups']
        schema = current['response_format']['json_schema']['schema']
        assert schema['$defs']['SelectedInsight']['properties']['limitation_refs']['items']['enum'] == list(new_input['limitation_pool'])
        assert repo.payload(calls(repo)[0].request_snapshot_id) == current


def test_run_manifest_pins_same_template_as_report_call(tmp_path):
    from app.domain.execution import ApprovedExecutionSnapshot
    llm,repo,_=provider(tmp_path,[report_output])
    service=AnalysisReportService(llm,CapabilityRegistry())
    intent,validated,execution,profile=report_case()
    execution=execution.model_copy(update={'session_id':'session-test','approval_id':'approval-test'})
    approval=ApprovedExecutionSnapshot(approval_id='approval-test',approved_at='audit-time',validated_plan=validated,intent=intent)
    traces=TraceRecorder(TraceRepository(tmp_path/'trace'))
    traces.queue(execution,SimpleNamespace(attempt=1,queued_at='2026-10-29T00:00:00+00:00'),lambda:approval,service)
    run=traces.repository.attempt(execution.execution_id,1)
    assert run.manifest.prompt_template_snapshots['insight_generator']==service.prompt_source.snapshot.template_snapshot_id
    context=traces.start(execution.execution_id,1)
    asyncio.run(service.generate(intent,validated,execution,profile,trace=context))
    call=calls(repo)[0]
    assert call.run_id==run.run_id and call.template_snapshot_id==run.manifest.prompt_template_snapshots['insight_generator']


def test_simultaneous_template_registration_and_terminal_immutability(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    llm,repo,_=provider(tmp_path)
    service=IntentParserService(llm)
    with ThreadPoolExecutor(max_workers=4) as pool:
        registered=list(pool.map(repo.register,[service.prompt_source.snapshot]*4))
    assert len({r.template_snapshot_id for r in registered})==1
    asyncio.run(service.parse('比较城市岗位数量',recruiting_profile()))
    record=calls(repo)[0]
    with pytest.raises(ValueError):repo.finish(record)
    assert repo.call(record.call_id)==record


def test_plain_business_output_matches_uncaptured_provider(tmp_path):
    from intent_fixtures import StubProvider
    good=intent_payload(business_goal='比较城市岗位数量')
    llm,_,_=provider(tmp_path,[good])
    captured=asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    plain=asyncio.run(IntentParserService(StubProvider(good)).parse('比较城市岗位数量',recruiting_profile()))
    fields=['analysis_mode','next_action','analysis_goal','constraints','uncertainties','clarification_questions']
    assert all(getattr(captured,f)==getattr(plain,f) for f in fields)


def test_template_contains_explicit_retry_text_and_actual_capability_rules(tmp_path):
    llm,_,_=provider(tmp_path)
    intent=IntentParserService(llm).prompt_source.snapshot
    planner=AnalysisPlannerService(llm,CapabilityRegistry()).prompt_source.snapshot
    assert len(intent.user_composition['retry_instructions'])==2
    assert planner.user_composition['retry_instructions']['PLANNER_RETRY_INSTRUCTION']=='同一输入重新输出完整JSON；严格遵守参数Schema，不增加分析目标。'
    assert set(planner.user_composition['fixed_context']['capabilities']['operations'])=={'filter','aggregate','group_aggregate','sort','top_n','derive'}


def test_overlapping_reports_keep_explicit_run_and_span_bindings(tmp_path):
    async def delayed(body):
        await asyncio.sleep(.02)
        return report_output(body)
    llm,repo,_=provider(tmp_path,[delayed])
    traces=TraceRecorder(TraceRepository(tmp_path/'trace'))
    contexts=[]
    for name in ('left','right'):
        run=TraceRun(run_id='run-'+name,session_id='session-'+name,execution_id='exec-'+name,attempt=1,
            owner_instance='test',status='running',queued_at='2026-10-29T00:00:00+00:00',manifest=RunManifest())
        traces.repository.create(run);contexts.append(TraceContext(traces,run))
    service=AnalysisReportService(llm,CapabilityRegistry())
    async def run():
        return await asyncio.gather(*(service.generate(*report_case(),trace=context,original_query=context.run.run_id) for context in contexts))
    asyncio.run(run())
    for record in calls(repo):
        assert traces.repository.span(record.span_id).run_id==record.run_id
        body=repo.payload(record.request_snapshot_id)
        assert json.loads(body['messages'][1]['content'])['original_query']==record.run_id


def test_registry_migration_is_additive_and_preserves_existing_records(tmp_path):
    llm,repo,_=provider(tmp_path)
    asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    record=calls(repo)[0]
    restarted=PromptRegistryRepository(tmp_path/'registry')
    assert restarted.call(record.call_id)==record
    with restarted.connect() as conn:
        assert [r[0] for r in conn.execute('SELECT version FROM registry_migrations ORDER BY version')]==[1,2]


def test_optional_retention_config_requires_positive_days(tmp_path):
    assert Settings(tmp_path).llm_request_retention_days is None
    with pytest.raises(ValueError):Settings(tmp_path,llm_request_retention_days=0)


def test_finished_call_stores_status_usage_and_sampling_parameters(tmp_path):
    good = intent_payload(business_goal='比较城市岗位数量', analysis_object='招聘数据')
    bodies = []
    async def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(good, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18, 'prompt_tokens_details': {'cached_tokens': 2}}})
    repo = PromptRegistryRepository(tmp_path / 'registry')
    llm = CompatibleLLMProvider('https://local-test.invalid/v1', 'qwen3.8-flash', api_key='secret-not-for-snapshot',
        transport=httpx.MockTransport(handler), capture=CallRecorder(repo), temperature=0.7, top_p=0.8, max_tokens=8192,
        input_usd_per_million=1, output_usd_per_million=2)
    asyncio.run(IntentParserService(llm, enable_thinking=False).parse('比较城市岗位数量', recruiting_profile(), ['保留全部城市']))
    saved = calls(repo)[0]
    assert saved.http_status == 200
    assert saved.endpoint == 'https://local-test.invalid/v1/chat/completions'
    assert saved.usage['input_tokens'] == 11 and saved.usage['output_tokens'] == 7 and saved.usage['cached_tokens'] == 2
    assert saved.usage['estimated_cost'] == pytest.approx(25 / 1_000_000)
    assert bodies[0]['temperature'] == 0.7 and bodies[0]['top_p'] == 0.8 and bodies[0]['max_tokens'] == 8192
    assert 'secret-not-for-snapshot' not in saved.endpoint


def test_payload_integrity_is_checked_on_read(tmp_path):
    llm,repo,_=provider(tmp_path)
    asyncio.run(IntentParserService(llm).parse('比较城市岗位数量',recruiting_profile()))
    record=calls(repo)[0]
    with repo.connect() as conn:
        conn.execute('DELETE FROM llm_request_payloads WHERE snapshot_id=?',(record.request_snapshot_id,))
        conn.execute('INSERT INTO llm_request_payloads VALUES (?,?,NULL)',(record.request_snapshot_id,'{}'))
    with pytest.raises(AppError) as error:repo.payload(record.request_snapshot_id)
    assert error.value.error.code=='LLM_REQUEST_INTEGRITY_ERROR'
