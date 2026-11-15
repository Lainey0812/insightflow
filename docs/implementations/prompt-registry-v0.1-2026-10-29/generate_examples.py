"""Capture actual service/Provider assembly with local scripted HTTP only.
No external model, user upload, API key or business database is accessed.
The approval below is a constructed test fixture, not a user approval.
Each rerun must use a NEW output path; never overwrite archived examples.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
import httpx
from app.domain.execution import ApprovedExecutionSnapshot
from app.domain.models import now
from app.domain.prompt_registry import LLMCallRecord
from app.llm.capture import CallRecorder
from app.llm.compatible_provider import CompatibleLLMProvider
from app.services.intent_parser import IntentParserService, INTENT_RETRY_INSTRUCTION, GROUNDING_RETRY_INSTRUCTION
from app.services.analysis_planner import AnalysisPlannerService, PLANNER_RETRY_INSTRUCTION
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from app.storage.prompt_registry import PromptRegistryRepository
from app.storage.trace_repository import TraceRepository
from app.observability.recorder import TraceRecorder
from intent_fixtures import intent_payload
from planning_fixtures import recruiting_profile, task
from report_fixtures import report_case

OUT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('examples')
OUT.mkdir(exist_ok=False)


async def main(directory):
    repo=PromptRegistryRepository(directory/'registry')
    trace_repo=TraceRepository(directory/'trace')
    bodies=[]
    intent_calls=0
    async def handler(request):
        nonlocal intent_calls
        body=json.loads(request.content);bodies.append(body)
        purpose=body['response_format']['json_schema']['name']
        if purpose=='intent_v1':
            intent_calls+=1
            output='not JSON' if intent_calls==1 else intent_payload(business_goal='比较城市岗位数量',analysis_object='招聘数据')
        elif purpose=='analysis_planner_v1':
            output={'tasks':[task()]}
        else:
            payload=json.loads(body['messages'][1]['content'])
            chosen={}
            for evidence in payload['evidence']:
                if evidence['evidence_type']=='ranking':chosen.setdefault(evidence['task_id'],evidence)
            output={'insights':[{'primary_evidence_id':e['evidence_id'],'evidence_refs':[e['evidence_id']],
                'finding_type':'highlight','implication':'当前结果值得结合参与记录继续核查。',
                'recommendation':'比较相关分组的记录构成；补充分析尚未执行。',
                'limitations':['结论仅适用于当前返回范围。']} for e in chosen.values()]}
        text=output if isinstance(output,str) else json.dumps(output,ensure_ascii=False)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':text}}]})
    llm=CompatibleLLMProvider('https://local-fixture.invalid/v1','qwen3.8-flash',transport=httpx.MockTransport(handler),capture=CallRecorder(repo))
    intent_service=IntentParserService(llm,enable_thinking=False)
    planner=AnalysisPlannerService(llm,CapabilityRegistry(),enable_thinking=False)
    report_service=AnalysisReportService(llm,CapabilityRegistry())
    intent=await intent_service.parse('比较城市岗位数量',recruiting_profile())
    plan=await planner.plan(intent,recruiting_profile())
    traces=TraceRecorder(trace_repo)
    reports=[];runs=[]
    for index,tasks in enumerate((None,[task(tid='A01'),task(tid='A02')]),1):
        parsed,validated,execution,profile=report_case(tasks=tasks)
        execution=execution.model_copy(update={'source':'engine','session_id':'fixture_session_'+str(index),
            'approval_id':'constructed_test_approval_'+str(index),'execution_id':'fixture_execution_'+str(index)})
        approval=ApprovedExecutionSnapshot(approval_id=execution.approval_id,session_id=execution.session_id,
            approved_at=now(),intent=parsed,validated_plan=validated,constraints_confirmed=True)
        traces.queue(execution,SimpleNamespace(attempt=1,queued_at=now()),lambda:approval,report_service,
            input_reader=lambda:(execution,approval,profile,'比较城市岗位数量'))
        context=traces.start(execution.execution_id,1)
        report=await report_service.generate(parsed,validated,execution,profile,approved_snapshot=approval,
            original_query='比较城市岗位数量',trace=context)
        context.finish(report.report_status,report=report)
        runs.append(context.run);reports.append(report)
    with repo.connect() as conn:
        records=[LLMCallRecord.model_validate_json(r[0]) for r in conn.execute('SELECT record FROM llm_calls ORDER BY rowid')]
    assert len(records)==5 and len(bodies)==5
    assert records[1].retry_of_call_id==records[0].call_id
    assert all(repo.payload(c.request_snapshot_id)==body for c,body in zip(records,bodies))
    assert repo.snapshot(records[3].request_snapshot_id).schema_hash!=repo.snapshot(records[4].request_snapshot_id).schema_hash
    templates={c.template_snapshot_id:repo.template(c.template_snapshot_id) for c in records}
    def save(name,value):
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    save('calls-and-requests.json',{'evidence_class':'synthetic_local_transport_capture','external_calls':0,
        'constructed_test_approval':True,'not_real_llm_evaluation':True,
        'calls':[{'call':c.model_dump(mode='json'),'snapshot':repo.snapshot(c.request_snapshot_id).model_dump(mode='json'),
            'payload':repo.payload(c.request_snapshot_id)} for c in records]})
    save('templates.json',[t.model_dump(mode='json') for t in templates.values()])
    save('trace-links.json',[{'run':run.model_dump(mode='json'),
        'spans':[s.model_dump(mode='json') for s in trace_repo.spans(run.run_id)],
        'calls':[c.model_dump(mode='json') for c in repo.calls(run_id=run.run_id)]} for run in runs])
    save('business-outputs.json',{'not_real_model':True,'intent':intent.model_dump(mode='json'),
        'plan':plan.model_dump(mode='json'),'reports':[r.model_dump(mode='json') for r in reports]})
    old=ROOT/'docs/audits/prompt-loading-paths-2026-10-29/captures-v3'
    for case,expected in [('I02-json-retry',INTENT_RETRY_INSTRUCTION),('I03-grounding-retry',GROUNDING_RETRY_INSTRUCTION),('P02-json-retry',PLANNER_RETRY_INSTRUCTION)]:
        data=json.loads((old/(case+'.json')).read_text())
        assert json.loads(data['calls'][1]['request']['messages'][1]['content'])['validation_feedback']['instruction']==expected
    save('checks.json',{'nodes':3,'calls':5,'retry_links':1,'report_runs_with_span_links':2,
        'payload_equals_actual_transport_body':True,'dynamic_schema_distinguished':True,
        'all_3_retry_instruction_texts_unchanged_from_frozen_audit':True,'external_calls':0})
    print(json.dumps({'nodes':3,'calls':5,'linked_report_runs':2,'external_calls':0}))


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='insightflow-registry-examples-') as directory:
        asyncio.run(main(Path(directory)))
