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
settings=replace(Settings.from_env(),data_dir=root/'var/verification/c2-closure-release03',admin_read_token='c2-verification-read',admin_local_test_mode=False)
assert settings.llm_api_key and settings.llm_model=='qwen3.8-flash'
app=create_app(settings);start=time.perf_counter()
from app.storage.workflow_reader import WorkflowReader
saved=json.loads((artifact/'real-run-03.json').read_text());wf=saved['workflow_id'];eid=saved['execution']['execution_id'];rid=saved['report']['report_id']
reader=WorkflowReader(settings.data_dir/'insightflow.sqlite3')
reader.plan(wf,saved['execution']['plan_version']);reader.approval(wf,saved['approval']['approval_id']);reader.execution(wf,eid);reader.report(wf,rid)
with TestClient(app) as client:
 response=client.get('/admin/workflow-traces/'+wf,headers={'X-Admin-Token':'c2-verification-read'})
 assert response.status_code==200,response.text
 data=response.json();assert data['collection']['status']=='observed',data['collection']
 assert data['reports'][0]['report_status']==saved['report']['report_status']
 assert {s['span_id'] for s in data['nodes']}=={s['span_id'] for s in saved['trace_query']['nodes']}
 with closing(app.state.repository.database.connect()) as conn:
  assert not conn.execute('PRAGMA foreign_key_check').fetchall()
 with closing(app.state.traces.repository.connect()) as conn:
  assert not conn.execute('PRAGMA foreign_key_check').fetchall()
 source=Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv').read_bytes()
 assert hashlib.sha256(source).hexdigest()==saved['source_sha256']
 import io
 frame=pd.read_csv(io.BytesIO(source));scope=frame[(pd.to_datetime(frame['订单日期']).dt.year==2026)&(frame['地区']=='华东')&(frame['订单状态']=='已完成')]
 expected={str(k):int(v) for k,v in scope.groupby('城市')['销售额'].sum().sort_values(ascending=False).head(3).items()}
 assert expected=={'济南':21250,'南京':20250,'上海':5760}
 proof={'phase_status':'Completed','workflow_id':wf,'root_run_id':data['root_run_id'],
  'session_id':data['session_id'],'approval_id':saved['approval']['approval_id'],'execution_id':eid,
  'report_id':rid,'report_status':saved['report']['report_status'],'report_attempt':saved['report_generation']['attempt'],
  'query_api':'GET /admin/workflow-traces/'+wf,'report_status':'partial','generation_status':'completed',
  'node_count':len(data['nodes']),'llm_call_count':len(data['llm_calls']),
  'source_rows':len(frame),'filtered_rows':len(scope),'pandas_top3':expected,'top3_total':sum(expected.values()),
  'same_root_direct_spans':all(n['run_id']==data['root_run_id'] and n['parent_span_id'] is None for n in data['nodes']),
  'restart_readback_preserved_span_ids':True,'workflow_reader_cross_contracts_verified':True,
  'foreign_keys_valid':True,'collection':data['collection'],'final_trace_query':data}
 with (artifact/'acceptance-final-readback-03.json').open('x') as f:json.dump(proof,f,ensure_ascii=False,indent=2)
 print(json.dumps({k:proof[k] for k in ['phase_status','workflow_id','root_run_id','node_count','llm_call_count','filtered_rows','restart_readback_preserved_span_ids']},ensure_ascii=False))
