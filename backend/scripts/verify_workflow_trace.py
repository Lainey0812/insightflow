"""Opt-in live ReportWorkflow verification using a synthetic six-row CSV.

Intent/Planner use labelled controlled fixtures solely to construct approved test
inputs. The report calls the configured real provider; no report fallback exists.
No credentials, full model text, or raw request bodies are exported to the Trace.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'backend/tests'))
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.domain.errors import AppError
from app.llm.factory import create_provider
from app.main import create_app
from evaluate_report_insights import load_env
from test_report_workflow import Provider,run


def main(args):
    if not args.live:raise ValueError('--live is required for a real model call')
    if args.output.exists() or args.data_dir.exists():raise ValueError('Use new output and data directories; preserving earlier verification')
    load_env(ROOT/'backend/.env')
    original=Settings.from_env()
    if original.llm_model!='qwen3.8-flash':raise ValueError('Expected configured qwen3.8-flash')
    calls=[]
    class LiveReportProvider(Provider):
        def __init__(self):
            super().__init__();self.delegate=create_provider(original);self.model=original.llm_model
        async def generate(self,request):
            if request.purpose!='report_insights_v1':return await super().generate(request)
            meta={'purpose':request.purpose,'model':self.model,'status':'calling','is_mock':None}
            calls.append(meta);timer=perf_counter()
            try:
                response=await self.delegate.generate(request)
                if response.is_mock:raise ValueError('Real report verification rejects Mock')
                meta.update(status='returned',provider=response.provider,model=response.model,is_mock=False)
                return response
            except AppError as exc:
                meta.update(status='failed',error_code=exc.error.code)
                raise
            finally:meta['duration_ms']=(perf_counter()-timer)*1000
    config=replace(original,data_dir=args.data_dir.resolve(),admin_read_token=secrets.token_urlsafe(32),trace_enabled=True)
    app=create_app(config,LiveReportProvider())
    with TestClient(app) as client:
        _,execution,session=run(client)
        auth={'X-Admin-Token':config.admin_read_token}
        listed=client.get('/admin/runs',headers=auth).json()
        item=listed['items'][0]
        detail=client.get('/admin/runs/'+item['run_id'],headers=auth).json()
        spans=client.get('/admin/runs/'+item['run_id']+'/spans',headers=auth).json()
        events={s['span_id']:client.get('/admin/spans/'+s['span_id']+'/events',headers=auth).json() for s in spans['items']}
        assert len(calls)==1 and listed['total']==1
        assert execution['execution_status']=='success'
        values={row['field_0003']:row['sales_total'] for row in execution['tasks'][0]['result']['rows']}
        assert values=={'济南':21250,'南京':20250,'上海':5760}
        result={'scope':'real ReportWorkflow + real report LLM; upstream Intent/Planner are labelled test fixtures',
            'input':'synthetic six-row CSV from test_report_workflow.SALES',
            'model_calls':calls,'engine_values':values,'engine_status':execution['execution_status'],
            'report_generation':session['report_generations'][0],
            'api_examples':{'list':listed,'detail':detail,'spans':spans,'events':events}}
        sid=session['id'];eid=execution['execution_id'];rid=item['run_id']
    restarted=create_app(config,LiveReportProvider())
    with TestClient(restarted) as client:
        response=client.get('/admin/runs/'+rid,headers={'X-Admin-Token':config.admin_read_token})
        assert response.status_code==200 and response.json()['run']==item
        result['restart_query_verified']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    serialized=json.dumps(result,ensure_ascii=False,indent=2)
    if config.admin_read_token in serialized or (original.llm_api_key and original.llm_api_key in serialized):
        raise ValueError('Refusing credential export')
    with args.output.open('x') as stream:stream.write(serialized+'\n')
    print(json.dumps({'run_id':rid,'session_id':sid,'execution_id':eid,'status':item['status'],
        'spans':len(spans['items']),'model_calls':calls,'restart_query_verified':True},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    main(parser.parse_args())
