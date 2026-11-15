"""Read-only observation of actual persistent changes; no synthetic workflow events."""
import json,sqlite3,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).parent
B=ROOT/'var/insightflow.sqlite3';T=ROOT/'var/observability/trace.sqlite3';P=ROOT/'var/prompt_registry/registry.sqlite3'
def read(path,sql):
 with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=.05) as c:return c.execute(sql).fetchall()
old_sessions={r[0] for r in read(B,'SELECT id FROM sessions')};old_calls={r[0] for r in read(P,'SELECT id FROM llm_calls')}
(OUT/'baseline.json').write_text(json.dumps({'recorded_at':datetime.now(timezone.utc).isoformat(),'session_ids':sorted(old_sessions),'call_ids':sorted(old_calls),'runs':read(T,'SELECT count(*) FROM trace_runs')[0][0]},indent=2)+'\n')
last=None;deadline=time.monotonic()+1200
with (OUT/'observations.jsonl').open('x') as f:
 while time.monotonic()<deadline and not (OUT/'stop').exists():
  try:
   sessions=[]
   for sid,raw in read(B,'SELECT id,state FROM sessions'):
    if sid in old_sessions:continue
    s=json.loads(raw);sessions.append({k:s.get(k) for k in ['id','status','revision','workflow_events','node_runs','engine_execution_ids']})
   ids={s['id'] for s in sessions};runs=[json.loads(r[0]) for r in read(T,'SELECT record FROM trace_runs') if json.loads(r[0])['session_id'] in ids]
   run_ids={r['run_id'] for r in runs}
   spans=[json.loads(r[0]) for r in read(T,'SELECT record FROM trace_spans') if json.loads(r[0])['run_id'] in run_ids]
   events=[json.loads(r[0]) for r in read(T,'SELECT record FROM trace_events') if json.loads(r[0])['run_id'] in run_ids]
   calls=[json.loads(raw) for cid,raw in read(P,'SELECT id,record FROM llm_calls') if cid not in old_calls]
   data={'sessions':sessions,'runs':runs,'spans':spans,'events':events,'calls':calls};encoded=json.dumps(data,sort_keys=True,ensure_ascii=False)
   if encoded!=last:
    f.write(json.dumps({'observed_at':datetime.now(timezone.utc).isoformat(),**data},ensure_ascii=False)+'\n');f.flush();last=encoded
  except sqlite3.Error:pass
  time.sleep(.25)
