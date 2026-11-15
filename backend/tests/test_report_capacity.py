"""Capacity preflight, real kernel outputs, batching and preserved core coverage."""
import asyncio
import copy
import json

import pytest
from app.domain.errors import AppError
from app.planning.capabilities import CapabilityRegistry
from app.reporting.capacity import preflight
from app.reporting.batches import partition
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.services.analysis_report import AnalysisReportService
from report_fixtures import report_case, ReportProvider
from planning_fixtures import task, step

RAW='地区,销售额,成本\n华东,100,30\n华东,200,70\n华南,300,100\n'.encode()


def inputs(n=9, *, core=True):
    metrics=[{'function':'count','alias':'rows'}]
    for field in ['field_0002','field_0003']:
        metrics += [{'function':fn,'field':field,'alias':field+'_'+fn} for fn in ['sum','avg','min','max','median','distinct_count']]
    while len(metrics)<n:
        metrics.append({'function':'count','alias':f'count_{len(metrics)}'})
    tasks=[]
    for index in range(0,n,20):
        tasks.append(task([step('aggregate',{'metrics':metrics[index:min(index+20,n)]})],tid=f'A{index//20+1:02}',priority='P0' if core else 'P1'))
    return report_case(tasks,RAW)


class CountingProvider(ReportProvider):
    def __init__(self,failed=(),omit=False):super().__init__();self.failed=set(failed);self.counter=0;self.omit=omit
    async def generate(self,request):
        self.counter+=1
        if self.counter in self.failed:
            self.requests.append(request)
            raise AppError('LLM_TIMEOUT','declared test timeout',504)
        response=await super().generate(request)
        if self.omit:
            data=json.loads(response.text);data['insights']=data['insights'][:1]
            return response.model_copy(update={'text':json.dumps(data)})
        return response


def generate(case,provider=None):
    return asyncio.run(AnalysisReportService(provider or ReportProvider(),CapabilityRegistry()).generate(*case))


@pytest.mark.parametrize('n,batches',[(1,1),(8,1),(9,2),(17,3)])
def test_all_core_metrics_survive_batching_and_unique_final_ids(n,batches):
    case=inputs(n);before=case[2].model_dump_json();p=CountingProvider();r=generate(case,p)
    assert r.report_status==r.goal_coverage=='complete'
    assert p.counter==batches
    assert len(r.insights)==n and len({i.insight_id for i in r.insights})==n
    assert case[2].model_dump_json()==before
    by_id={e.evidence_id:e for e in r.evidence}
    covered={(by_id[ref].task_id,by_id[ref].result_field) for i in r.insights for ref in i.evidence_refs}
    required={(e.task_id,e.result_field) for e in r.evidence if not e.result_field.startswith('$')}
    assert covered==required
    for request in p.requests:
        payload=json.loads(request.instruction)
        assert len(payload['evidence_groups'])<=8
        assert len(payload['evidence'])<=80
        assert len(request.instruction.encode())<=160*1024
        assert 'result_data' not in payload
        enum=request.response_schema['$defs']['SelectedInsight']['properties']['primary_evidence_id']['enum']
        assert set(enum)=={e['evidence_id'] for e in payload['evidence']}


@pytest.mark.parametrize('failed',[(1,),(2,)])
def test_one_failed_batch_keeps_valid_results_and_declares_uncovered_metrics(failed):
    p=CountingProvider(failed);case=inputs();r=generate(case,p)
    assert p.counter==2 and r.report_status==r.goal_coverage=='partial'
    metadata=r.execution_metadata['A01']
    assert metadata['missing_core_metrics']
    assert any('生成失败' in s for s in r.limitations)
    assert len(r.result_data['R001'].columns)==9
    assert r.uncompleted_tasks[0].task_id=='A01'
    assert [b['status'] for b in metadata['report_batches']].count('failed')==1


def test_all_batches_fail_does_not_save_an_empty_success_and_errors_are_serializable():
    p=CountingProvider((1,2))
    with pytest.raises(AppError) as e:generate(inputs(),p)
    assert e.value.error.code=='LLM_TIMEOUT' and p.counter==2
    assert len(e.value.error.details['batch_results'])==2
    json.dumps(e.value.error.model_dump())


def test_schema_valid_but_omitted_core_metrics_cannot_claim_complete():
    r=generate(inputs(),CountingProvider(omit=True))
    assert r.report_status==r.goal_coverage=='partial'
    assert len(r.execution_metadata['A01']['missing_core_metrics'])==7


def test_batch_ids_cannot_reference_other_batch_evidence():
    class CrossBatch(CountingProvider):
        ids=None
        async def generate(self,request):
            response=await super().generate(request)
            payload=json.loads(request.instruction)
            if self.ids is None:self.ids=payload['evidence'][0]['evidence_id']
            else:
                data=json.loads(response.text)
                data['insights'][0]['evidence_refs']=[self.ids]
                return response.model_copy(update={'text':json.dumps(data)})
            return response
    r=generate(inputs(),CrossBatch())
    assert r.report_status=='partial'
    assert r.execution_metadata['A01']['report_batches'][1]['error_code']=='REPORT_INVALID_EVIDENCE_REFERENCE'


def test_total_capacity_is_checked_before_llm_and_preflight_does_not_delete_plan():
    case=inputs(65);before=case[1].model_dump_json();capacity=preflight(case[1],case[3]);p=CountingProvider()
    assert not capacity.supported and capacity.metric_count==65 and capacity.context_estimate_only
    with pytest.raises(AppError) as e:generate(case,p)
    assert e.value.error.code=='REPORT_TOTAL_CAPACITY_EXCEEDED' and not p.requests
    assert before==case[1].model_dump_json()


def test_runtime_bytes_limit_keeps_group_intact_and_makes_no_call():
    case=inputs();_,descs=prepare(*case,CapabilityRegistry());evidence=EvidenceBuilder().build(case[2],case[3],descs)
    tasks={t.task_id:t for t in case[1].plan.tasks}
    base={'tasks':[],'scope_context':[],'task_sample_context':[],'huge':'x'*(160*1024)}
    with pytest.raises(AppError) as e:partition(evidence,tasks,base,{})
    assert e.value.error.code=='REPORT_CONTEXT_TOO_LARGE'


def test_global_goal_blocked_when_only_optional_batch_survives():
    case=inputs(9)
    # Separate 8 core metrics and one supplemental metric, without changing any values.
    first=case[1].plan.tasks[0].model_dump();all_metrics=first['steps'][0]['params']['metrics']
    case=report_case([task([step('aggregate',{'metrics':all_metrics[:8]})]),
                      task([step('aggregate',{'metrics':all_metrics[8:]})],tid='A02',priority='P1')],RAW)
    r=generate(case,CountingProvider((1,)))
    assert r.report_status=='partial' and r.goal_coverage=='blocked'


def test_preflight_plan_nine_metrics_is_allowed_and_reports_two_estimated_calls():
    case=inputs();value=preflight(case[1],case[3])
    assert value.supported and value.metric_count==value.core_metric_count==9
    assert value.estimated_batches==2 and '分 2 批' in value.message


@pytest.mark.parametrize('n,allowed',[(9,True),(65,False)])
def test_api_eligibility_and_transaction_use_same_capacity_guard(client,n,allowed):
    case=inputs(n)
    response=client.post('/api/v1/sessions',data={'goal':'销售概况','manual_review':'true'},files={'file':('sales.csv',RAW,'text/csv')})
    state=response.json();client.headers['X-Session-Token']=state.pop('review_access_token')
    plan=case[1].plan.model_dump();plan.update(state['dataset_ref'])
    intent=case[0].model_dump();intent['analysis_goal']['business_goal']='销售概况'
    response=client.post('/api/v1/sessions/'+state['id']+'/plans',json={'expected_revision':state['revision'],'plan':plan,'intent':intent})
    assert response.status_code==200,response.text
    state=response.json()
    view=client.get('/api/v1/sessions/'+state['id']+'/review').json()
    assert view['can_approve'] is allowed and view['report_capacity']['supported'] is allowed
    assert view['report_capacity']['metric_count']==n
    from hitl_fixtures import approval
    result=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state))
    assert result.status_code==(200 if allowed else 422),result.text
    if not allowed:assert result.json()['error']['code']=='REPORT_CAPACITY_EXCEEDED'


def test_two_calls_share_template_but_have_distinct_requests_spans_and_one_projection(tmp_path):
    from test_prompt_registry import provider, report_output, calls
    from test_workflow_trace import trace_run
    from app.storage.trace_repository import TraceRepository
    from app.observability.recorder import TraceRecorder, TraceContext
    llm,registry,bodies=provider(tmp_path,[report_output])
    repository=TraceRepository(tmp_path/'traces')
    root=trace_run(repository)
    trace=TraceContext(TraceRecorder(repository),root)
    report=asyncio.run(AnalysisReportService(llm,CapabilityRegistry()).generate(*inputs(),trace=trace))
    records=calls(registry)
    assert report.report_status=='complete' and len(records)==2
    assert len({r.call_id for r in records})==len({r.request_snapshot_id for r in records})==2
    assert len({r.template_snapshot_id for r in records})==1
    assert all(r.run_id==root.run_id and r.retry_index==0 for r in records)
    assert len({r.operation_id for r in records})==2
    spans=repository.spans(root.run_id)
    gen=[s for s in spans if s.name=='insight_generator'];valid=[s for s in spans if s.name=='fact_validator']
    assert len(gen)==len(valid)==2
    assert all(s.parent_span_id is None for s in gen+valid)
    assert {r.span_id for r in records}=={s.span_id for s in gen}
    output=[s for s in repository.snapshots(root.run_id) if s.kind=='llm_output']
    assert len(output)==1 and output[0].projection['batch_count']==2


def test_empty_filtered_numeric_metric_remains_uncovered_instead_of_silent_complete():
    source=inputs(9)
    metrics=source[1].plan.tasks[0].steps[0].params['metrics']
    case=report_case([task([
        step('filter',{'conditions':[{'field':'field_0001','operator':'eq','value':'无匹配地区'}]}),
        step('aggregate',{'metrics':metrics},'S02')])],RAW)
    report=generate(case)
    assert report.report_status=='partial' and report.goal_coverage=='partial'
    assert report.execution_metadata['A01']['missing_core_metrics']
    assert any('尚未形成有效洞察' in x for x in report.limitations)
