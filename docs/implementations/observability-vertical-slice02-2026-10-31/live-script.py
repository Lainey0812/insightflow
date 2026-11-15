"""Real CSV/LLM preparation and committed HITL only; blocked paths are not triggered."""
import ast,os,re,sys,json,time
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
artifact=root/'docs/implementations/observability-vertical-slice02-2026-10-31'
settings=replace(Settings.from_env(),data_dir=root/'var/verification/vertical-slice02-hitl')
assert settings.llm_api_key and settings.llm_model=='qwen3.8-flash'
app=create_app(settings);start=time.perf_counter()
with TestClient(app) as client:
 response=client.post('/api/v1/sessions',data={'real_workflow':'true','goal':'帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。'},files={'file':('insightflow_sales_orders_test.csv',Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv').read_bytes(),'text/csv')})
 assert response.status_code==201
 initial=response.json();client.headers['X-Session-Token']=initial['review_access_token']
 state=app.state.repository.get(initial['id']);prepare_seconds=time.perf_counter()-start
 assert state.status.value=='AWAITING_APPROVAL',state.error
 record=state.review_plan
 body={k:getattr(record,k) for k in ('plan_id','plan_version','dataset_id','dataset_version','validation_version')}
 body.update(expected_revision=state.revision,approval_request_id='slice02-live-approval',acknowledged_warnings=app.state.plan_review.warning_ids(record.validated_plan))
 approved=client.post('/api/v1/sessions/'+state.id+'/approvals',json=body)
 assert approved.status_code==200,approved.text
 assert client.post('/api/v1/sessions/'+state.id+'/approvals',json=body).json()==approved.json()
 final=app.state.repository.get(state.id);identity=app.state.workflow.identity(final);repo=app.state.traces.repository
 with closing(app.state.repository.database.connect()) as conn:
  workflow=dict(conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?',(identity.workflow_id,)).fetchone())
  approvals=[json.loads(r[0]) for r in conn.execute('SELECT record FROM plan_approvals WHERE session_id=?',(state.id,))]
  assert conn.execute('SELECT count(*) FROM executions WHERE session_id=?',(state.id,)).fetchone()[0]==0
  assert conn.execute('SELECT count(*) FROM report_generations WHERE session_id=?',(state.id,)).fetchone()[0]==0
 spans=repo.spans(identity.root_run_id);hitl=[s for s in spans if s.name=='hitl']
 assert [s.attributes['outcome'] for s in hitl]==['approved','replayed']
 assert len(approvals)==1 and all(s.attributes['approval_id']==approvals[0]['approval_id'] for s in hitl)
 assert all(s.run_id==identity.root_run_id and s.parent_span_id is None and s.finished_at and s.duration_ms>=0 for s in spans)
 assert final.status.value=='APPROVED'
 with closing(app.state.llm_captures.repository.connect()) as conn:
  calls=[json.loads(r[0]) for r in conn.execute("SELECT record FROM llm_calls WHERE json_extract(record,'$.run_id')=?",(identity.root_run_id,))]
 assert len(calls)==2 and all(c['status']=='succeeded' for c in calls)
 result={'verified_scope':'preparation_and_hitl_only','full_slice02_accepted':False,
  'blocked_nodes':['analysis_engine','reporting'],'prepare_seconds':prepare_seconds,
  'total_seconds':time.perf_counter()-start,'database_directory':str(settings.data_dir),
  'session_id':state.id,'session_status':final.status.value,'workflow':workflow,
  'profile_rows':state.profile.row_count,'csv_sha256':state.file.content_sha256,
  'root':repo.get(identity.root_run_id).model_dump(mode='json'),
  'spans':[s.model_dump(mode='json') for s in spans],
  'events':[e.model_dump(mode='json') for e in repo.run_events(identity.root_run_id)],
  'approvals':approvals,'calls':calls,'execution_count':0,'report_generation_count':0}
 with (artifact/'live-preparation-hitl.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 print(json.dumps({k:result[k] for k in ['session_id','session_status','prepare_seconds','total_seconds','profile_rows','execution_count']},ensure_ascii=False))
