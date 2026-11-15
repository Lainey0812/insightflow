"""Append real ReportWorkflow diagnostic runs to an existing verification database.

Report calls the real configured model. Upstream structured test input/plan are
labelled controlled fixtures, not model-quality claims. No trace rows are seeded.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/tests'))
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.llm.factory import create_provider
from app.domain.errors import AppError
from evaluate_report_insights import load_env
from workflow_v1_fixtures import ControlledWorkflowProvider,create_real
from intent_fixtures import intent_payload
from hitl_fixtures import approval,execution
from test_report_workflow import SALES


def main(args):
    if not args.live or args.output.exists():raise ValueError('Explicit live call and new output path required')
    load_env(ROOT/'backend/.env');settings=Settings.from_env()
    if settings.llm_model!='qwen3.8-flash':raise ValueError('Expected configured existing qwen3.8-flash')
    records=[]
    def planner(context):
        task={'task_id':'A01','title':'上传记录总数','business_question':'本次上传数据共有多少条记录？',
            'priority':'P0','priority_reason':'删除后不能回答总记录数','requirement_ids':[r['requirement_id'] for r in context['core_requirements']],
            'depends_on':[],'missing_inputs':[],'steps':[{'step_id':'S01','operation':'aggregate',
                'params':{'metrics':[{'function':'count','alias':'total_records'}]}}]}
        tasks=[task]
        if provider.partial:
            tasks.append({'task_id':'A02','title':'辅助维度缺失检查（验收用）','business_question':'是否可以按未提供的客户维度汇总？',
                'priority':'P1','priority_reason':'补充方向，删除仍能回答记录总数','requirement_ids':[],
                'depends_on':[],'missing_inputs':['缺少辅助客户维度'],
                'steps':[{'step_id':'S01','operation':'group_aggregate','params':{
                    'dimensions':['field_unavailable_customer'],'metrics':[{'function':'count','alias':'count_records'}]}}]})
        return {'tasks':tasks}
    class Provider(ControlledWorkflowProvider):
        def __init__(self):
            super().__init__(intents=[intent_payload(business_goal='统计本次上传记录总数')],planner=planner)
            self.delegate=create_provider(settings);self.model=settings.llm_model;self.partial=False;self.calls=[]
        async def generate(self,request):
            if request.purpose!='report_insights_v1':return await super().generate(request)
            try:
                response=await self.delegate.generate(request)
                if response.is_mock:raise ValueError('No mock allowed')
                self.calls.append({'provider':response.provider,'model':response.model,'is_mock':response.is_mock,'status':'returned'})
                return response
            except AppError as exc:
                self.calls.append({'status':'failed','error_code':exc.error.code});raise
    provider=Provider();secret=secrets.token_urlsafe(32)
    config=replace(settings,data_dir=args.data_dir.resolve(),admin_read_token=secret)
    app=create_app(config,provider)
    with TestClient(app) as client:
        for partial in ([False] if args.only_complete else [False,True]):
            provider.partial=partial
            content='记录编号\n1\n2\n3\n4\n5\n6\n'.encode() if args.simple_data else SALES
            state=create_real(client,content,'trace-v02-synthetic-records.csv' if args.simple_data else 'trace-v02-synthetic-sales.csv','统计本次上传记录总数，供核对文件规模与数据覆盖范围')
            checked=app.state.repository.get(state['id']).review_plan.validated_plan
            warnings=app.state.plan_review.warning_ids(checked)
            r=client.post('/api/v1/sessions/'+state['id']+'/approvals',json=approval(state,warnings,uuid4().hex))
            assert r.status_code==200,r.text
            r=client.post('/api/v1/executions',json=execution(r.json(),uuid4().hex))
            assert r.status_code==200,r.text
            result=r.json();assert result['tasks'][0]['result']['rows'][0]['total_records']==6
            job=app.state.reports.generation(result['execution_id'])
            observed=app.state.traces.repository.attempt(result['execution_id'],job.attempt)
            spans=app.state.traces.repository.spans(observed.run_id)
            events={s.span_id:[e.model_dump(mode='json') for e in app.state.traces.repository.events(s.span_id)] for s in spans}
            records.append({'case':'partial_missing_auxiliary_field' if partial else 'complete_count',
                'expected_status':'partial' if partial else 'complete','actual_status':observed.status,
                'engine_status':result['execution_status'],'total_records':6,'run':observed.model_dump(mode='json'),
                'spans':[s.model_dump(mode='json') for s in spans],'events':events,
                'calls':provider.calls[-1:]})
            print(json.dumps({'case':records[-1]['case'],'run_id':observed.run_id,'status':observed.status,'engine_status':result['execution_status']},ensure_ascii=False),flush=True)
    payload={'scope':'Real ReportWorkflow/LLM and deterministic engine; upstream Intent/Planner labelled controlled fixtures; synthetic CSV only',
             'records':records,'expected_states_achieved':all(r['actual_status']==r['expected_status'] for r in records)}
    text=json.dumps(payload,ensure_ascii=False,indent=2)
    assert secret not in text and (not settings.llm_api_key or settings.llm_api_key not in text)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:out.write(text+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true')
    p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--only-complete',action='store_true');p.add_argument('--simple-data',action='store_true')
    main(p.parse_args())
