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
settings=replace(Settings.from_env(),data_dir=root/'var/verification/c2-closure',admin_read_token='c2-verification-read',admin_local_test_mode=False)
assert settings.llm_api_key and settings.llm_model=='qwen3.8-flash'
app=create_app(settings);start=time.perf_counter()
with closing(app.state.repository.database.connect()) as conn:
 row=conn.execute("SELECT l.* FROM workflow_execution_links l JOIN executions e ON e.id=l.execution_id WHERE e.request_id=?",('c2-real-execution',)).fetchone()
 assert row is not None
 workflow_id=row['workflow_id'];execution_id=row['execution_id'];session_id=row['session_id']
with TestClient(app) as client:
 response=client.get('/admin/workflow-traces/'+workflow_id,headers={'X-Admin-Token':'c2-verification-read'})
 assert response.status_code==200,response.text
 trace=response.json();execution=app.state.executions.complete(execution_id)
 generation=app.state.reports.generation(execution_id);report=app.state.reports.get(generation.report_id)
 session=app.state.repository.get(session_id)
 expected={'济南':21250,'南京':20250,'上海':5760};actual={}
 for task in execution.tasks:
  if task.result:
   for row in task.result.rows:
    label=next((v for v in row.values() if isinstance(v,str) and v in expected),None)
    if label:actual[label]=next(v for v in row.values() if isinstance(v,(float,int)) and v in expected.values())
 assert actual==expected,actual
 assert generation.status=='completed' and trace['collection']['status']=='observed',trace['collection']
 assert len(trace['llm_calls'])==3 and all(c['status']=='succeeded' for c in trace['llm_calls'])
 assert all(n['run_id']==trace['root_run_id'] and n['parent_span_id'] is None for n in trace['nodes'])
 assert {n['name'] for n in trace['nodes']}=={'data_profiler','intent_parser','analysis_planner','plan_validator','hitl','analysis_engine','evidence_builder','chart_builder','insight_generator','fact_validator','report_assembler','report_persistence'}
 receipt=trace['reports'][0]['commit_receipt'];assert receipt['report_sha256']==hashlib.sha256(report.model_dump_json().encode()).hexdigest()
 persistence=next(n for n in trace['nodes'] if n['name']=='report_persistence')
 assert receipt['persistence_span_id']==persistence['span_id'] and persistence['status']=='complete'
 result={'acceptance':'Completed','workflow_id':workflow_id,'root_run_id':trace['root_run_id'],
  'verification_note':'Original public business API run committed successfully; first Admin read hit local-test-client authorization mismatch. This authorized read-only API call verifies the same persisted Workflow, without rerunning LLM or business actions.',
  'expected_sales':expected,'actual_sales':actual,'total_top3':sum(actual.values()),
  'data_directory':str(settings.data_dir),'trace_query':trace,'execution':execution.model_dump(mode='json'),
  'report_generation':generation.model_dump(mode='json'),'report':report.model_dump(mode='json'),
  'source_sha256':session.file.content_sha256,'row_count':session.profile.row_count}
 with (artifact/'real-verified-01.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 print(json.dumps({'acceptance':result['acceptance'],'workflow_id':workflow_id,'root_run_id':trace['root_run_id'],'nodes':len(trace['nodes']),'calls':len(trace['llm_calls']),'report_status':report.report_status,'generation':generation.status,'collection':trace['collection']},ensure_ascii=False))
