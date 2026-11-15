"""Read-only audit observation; never creates business/Trace state or stores credentials."""
import json,sqlite3,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).parent
BUSINESS=ROOT/'var/insightflow.sqlite3'
TRACE=ROOT/'var/observability/trace.sqlite3'
REGISTRY=ROOT/'var/prompt_registry/registry.sqlite3'
def rows(path,sql):
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=.05) as c:return c.execute(sql).fetchall()
base={r[0] for r in rows(BUSINESS,'SELECT id FROM sessions')}
(OUT/'baseline.json').write_text(json.dumps({'observed_at':datetime.now(timezone.utc).isoformat(),'session_ids':sorted(base),'trace_runs':rows(TRACE,'SELECT count(*) FROM trace_runs')[0][0],'llm_calls':rows(REGISTRY,'SELECT count(*) FROM llm_calls')[0][0]},indent=2)+'\n')
last=None
until=time.monotonic()+900
with (OUT/'observations.jsonl').open('x') as output:
 while time.monotonic()<until and not (OUT/'stop-observer').exists():
  sessions=[]
  try:
   for sid,raw in rows(BUSINESS,'SELECT id,state FROM sessions'):
    if sid in base:continue
    s=json.loads(raw)
    sessions.append({'session_id':sid,'status':s['status'],'revision':s['revision'],'workflow_kind':s['workflow_kind'],'dataset_ref':s.get('dataset_ref'),'node_runs':s.get('node_runs',[]),'workflow_events':s.get('workflow_events',[]),'intent_parse_id':s.get('intent',{}).get('parse_id') if s.get('intent') else None,'planner_parse_id':s.get('planner_result',{}).get('parse_id') if s.get('planner_result') else None,'execution_ids':s.get('engine_execution_ids',[]),'report_generations':s.get('report_generations',[]),'error_code':(s.get('error') or {}).get('code')})
   ids={s['session_id'] for s in sessions}
   trace_runs=[json.loads(r[0]) for r in rows(TRACE,'SELECT record FROM trace_runs') if json.loads(r[0])['session_id'] in ids]
   call_data=[json.loads(r[0]) for r in rows(REGISTRY,'SELECT record FROM llm_calls')]
   data={'sessions':sessions,'trace_runs':[{k:r.get(k) for k in ['run_id','session_id','execution_id','attempt','status','started_at','finished_at','duration_ms','error_code']} for r in trace_runs],'new_calls':[{k:c.get(k) for k in ['call_id','node_id','operation_id','call_sequence','retry_index','retry_of_call_id','status','started_at','finished_at','run_id','span_id','error_code','template_snapshot_id']} for c in call_data]}
   encoded=json.dumps(data,ensure_ascii=False,sort_keys=True)
   if encoded!=last:
    output.write(json.dumps({'observed_at':datetime.now(timezone.utc).isoformat(),**data},ensure_ascii=False)+'\n');output.flush();last=encoded
  except sqlite3.Error:pass
  time.sleep(.25)
