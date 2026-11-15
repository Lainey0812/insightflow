"""Real configured model and public business/Admin APIs. No Mock transport."""
import ast,os,re,sys,json,time,hashlib
from pathlib import Path
from dataclasses import replace
from contextlib import closing
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');os.chdir(root/'backend')
for raw in (root/'backend/.env').read_text().splitlines():
 line=raw.strip()
 if not line or line.startswith('#'):continue
 if line.startswith('export '):line=line[7:]
 key,sep,value=line.partition('=')
 if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key.strip()):continue
 value=value.strip()
 if value[:1] in ('"',"'"):value=ast.literal_eval(value)
 os.environ[key.strip()]=value
sys.path.insert(0,str(root/'backend'))
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
import pandas as pd
artifact=root/'docs/implementations/trace-closure-c2-2026-10-31'
settings=replace(Settings.from_env(),data_dir=root/'var/verification/c2-closure',admin_read_token='c2-verification-read')
assert settings.llm_api_key and settings.llm_model=='qwen3.8-flash'
app=create_app(settings);start=time.perf_counter()
with TestClient(app) as client:
 response=client.post('/api/v1/sessions',data={'real_workflow':'true','goal':'帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。'},files={'file':('insightflow_sales_orders_test.csv',Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv').read_bytes(),'text/csv')})
 assert response.status_code==201
 initial=response.json();client.headers['X-Session-Token']=initial['review_access_token']
 state=app.state.repository.get(initial['id']);assert state.status.value=='AWAITING_APPROVAL',state.error
 record=state.review_plan
 body={k:getattr(record,k) for k in ('plan_id','plan_version','dataset_id','dataset_version','validation_version')}
 body.update(expected_revision=state.revision,approval_request_id='c2-real-approval',acknowledged_warnings=app.state.plan_review.warning_ids(record.validated_plan))
 approved=client.post('/api/v1/sessions/'+state.id+'/approvals',json=body);assert approved.status_code==200,approved.text
 approved=approved.json()
 request={'session_id':state.id,'plan_id':record.plan_id,'plan_version':record.plan_version,'execution_request_id':'c2-real-execution'}
 execution=client.post('/api/v1/executions',json=request);assert execution.status_code==200,execution.text
 executed=execution.json();generation=client.get('/api/v1/executions/'+executed['execution_id']+'/report').json()
 trace_response=client.get('/admin/workflow-traces/'+state.workflow_id,headers={'X-Admin-Token':'c2-verification-read'})
 assert trace_response.status_code==200,trace_response.text
 trace=trace_response.json();report=app.state.reports.get(generation['report_id']) if generation.get('report_id') else None
 result={'elapsed_seconds':time.perf_counter()-start,'model':settings.llm_model,'data_directory':str(settings.data_dir),
  'workflow_id':state.workflow_id,'root_run_id':state.root_run_id,'execution':executed,'report_generation':generation,
  'report':report.model_dump(mode='json') if report else None,'trace_query':trace,
  'approval':approved['engine_approval'],'source_sha256':state.file.content_sha256}
 with (artifact/'real-run-01.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 print(json.dumps({'workflow_id':state.workflow_id,'root_run_id':state.root_run_id,'engine_status':executed['execution_status'],
  'generation_status':generation['status'],'report_status':report.report_status if report else None,'collection':trace['collection'],
  'elapsed_seconds':result['elapsed_seconds']},ensure_ascii=False))
 assert generation['status']=='completed',generation
 assert report is not None
 assert trace['collection']['status']=='observed',trace['collection']
 assert len(trace['llm_calls'])==3 and all(c['status']=='succeeded' for c in trace['llm_calls'])
 expected={'济南':21250,'南京':20250,'上海':5760}
 full=app.state.executions.complete(executed['execution_id']);actual={}
 for task in full.tasks:
  if task.result:
   for row in task.result.rows:
    labels=[v for v in row.values() if isinstance(v,str) and v in expected]
    if labels:
     actual[labels[0]]=next(v for v in row.values() if isinstance(v,(int,float)) and v in expected.values())
 assert actual==expected,actual
 assert all(n['run_id']==state.root_run_id and n['parent_span_id'] is None for n in trace['nodes'])
 assert any(n['name']=='report_persistence' and n['status']=='complete' and n['attributes'].get('report_id')==report.report_id for n in trace['nodes'])
 assert trace['reports'][0]['commit_receipt']['report_sha256']==hashlib.sha256(report.model_dump_json().encode()).hexdigest()
 with (artifact/'real-acceptance-01.json').open('x') as f:json.dump({'completed':True,'workflow_id':state.workflow_id,'root_run_id':state.root_run_id,'expected_city_sales':expected,'actual_city_sales':actual,'trace_nodes':len(trace['nodes']),'llm_calls':len(trace['llm_calls'])},f,ensure_ascii=False,indent=2)
