import ast,os,re,sys,json,time
from pathlib import Path
from dataclasses import replace
from contextlib import closing
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow')
os.chdir(root/'backend')
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
artifact=root/'docs/implementations/workflow-identity-bootstrap-v1-2026-10-31'
settings=replace(Settings.from_env(),data_dir=root/'var/verification/identity-bootstrap-v1-release')
assert settings.llm_api_key and settings.llm_model=='qwen3.8-flash'
app=create_app(settings)
start=time.perf_counter()
with TestClient(app) as client:
 response=client.post('/api/v1/sessions',data={'real_workflow':'true','goal':'帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。'},files={'file':('insightflow_sales_orders_test.csv',Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv').read_bytes(),'text/csv')})
 assert response.status_code==201,response.status_code
 initial=response.json();state=app.state.repository.get(initial['id'])
 identity=app.state.workflow.identity(state);repo=app.state.traces.repository
 run=repo.get(identity.root_run_id);spans=repo.spans(identity.root_run_id)
 with closing(app.state.repository.database.connect()) as conn:
  business=dict(conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?',(identity.workflow_id,)).fetchone())
 with closing(repo.connect()) as conn:
  link=dict(conn.execute('SELECT * FROM trace_workflow_links WHERE run_id=?',(identity.root_run_id,)).fetchone())
 with closing(app.state.llm_captures.repository.connect()) as conn:
  rows=conn.execute('SELECT record FROM llm_calls').fetchall()
  calls=[json.loads(r[0]) for r in rows if json.loads(r[0]).get('run_id')==identity.root_run_id]
 result={'elapsed_seconds':time.perf_counter()-start,'database':str(settings.data_dir/'insightflow.sqlite3'),
  'csv_sha256':state.file.content_sha256,'session_id':state.id,'session_status':state.status.value,
  'business_workflow':business,'trace_link':link,'root':run.model_dump(mode='json'),
  'spans':[s.model_dump(mode='json') for s in spans],
  'calls':[{k:c.get(k) for k in ['call_id','node_id','run_id','span_id','status','model','call_sequence','retry_of_call_id','template_snapshot_id','duration_ms','error_code']} for c in calls],
  'error':state.error.model_dump(mode='json') if state.error else None,
  'profile_rows':state.profile.row_count if state.profile else None,
  'validated_plan':state.planner_result.model_dump(mode='json') if state.planner_result else None}
 (artifact/'live-preparation-release.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:result[k] for k in ['session_id','session_status','elapsed_seconds','profile_rows','error']},ensure_ascii=False))
 assert state.status.value=='AWAITING_APPROVAL'
 assert all(s.parent_span_id is None and s.attributes['workflow_id']==identity.workflow_id for s in spans)
 assert {s.name for s in spans}=={'data_profiler','intent_parser','analysis_planner','plan_validator'}
 assert calls and all(c['run_id']==identity.root_run_id for c in calls)
