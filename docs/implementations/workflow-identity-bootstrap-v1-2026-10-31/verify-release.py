"""Read back this Run's persisted business/Trace/call evidence; no LLM execution."""
from pathlib import Path
import json,sqlite3,hashlib
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow')
artifact=root/'docs/implementations/workflow-identity-bootstrap-v1-2026-10-31'
data=root/'var/verification/identity-bootstrap-v1-release'
saved=json.loads((artifact/'live-preparation-release.json').read_text())
def connect(path):
 c=sqlite3.connect(f'file:{path}?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
business=connect(data/'insightflow.sqlite3');trace=connect(data/'observability/trace.sqlite3');registry=connect(data/'prompt_registry/registry.sqlite3')
session=json.loads(business.execute('SELECT state FROM sessions WHERE id=?',(saved['session_id'],)).fetchone()[0])
workflows=business.execute('SELECT * FROM business_workflows WHERE session_id=?',(saved['session_id'],)).fetchall();assert len(workflows)==1
workflow=dict(workflows[0]);root_id=workflow['root_run_id'];wf_id=workflow['workflow_id']
assert (session['workflow_id'],session['root_run_id'])==(wf_id,root_id)
run=json.loads(trace.execute('SELECT record FROM trace_runs WHERE id=?',(root_id,)).fetchone()[0])
link=dict(trace.execute('SELECT * FROM trace_workflow_links WHERE run_id=?',(root_id,)).fetchone());assert link['workflow_id']==wf_id
spans=[json.loads(r[0]) for r in trace.execute('SELECT record FROM trace_spans WHERE run_id=?',(root_id,))]
calls=[json.loads(r[0]) for r in registry.execute('SELECT record FROM llm_calls WHERE json_extract(record,\'$.run_id\')=?',(root_id,))]
assert len(spans)==5 and len(calls)==2
assert run['manifest']['bindings']['workflow_id']==wf_id and run['status']=='waiting_approval'
assert all(s['parent_span_id'] is None and s['attributes']['workflow_id']==wf_id and s['status']=='complete' for s in spans)
assert {s['name'] for s in spans}=={'data_profiler','intent_parser','analysis_planner','plan_validator'}
assert all(c['status']=='succeeded' and c['span_id'] in {s['span_id'] for s in spans} for c in calls)
assert len({(s['node_key'],s['node_attempt']) for s in spans})==5
assert session['status']=='AWAITING_APPROVAL' and not session['engine_execution_ids'] and session['engine_approval'] is None
assert session['profile']['row_count']==60
for c in (business,trace,registry):assert not c.execute('PRAGMA foreign_key_check').fetchall();c.close()
proof={'verified':True,'session_id':session['id'],'workflow_id':wf_id,'root_run_id':root_id,
 'csv_sha256':session['file']['content_sha256'],'profile_row_count':60,
 'session_status':session['status'],'identity_authority':'business_workflows','business_authority':'SessionState',
 'state_switch_performed':False,'approval_or_execution_performed':False,'distinct_spans':len(spans),
 'distinct_calls':len(calls),'model_config':run['manifest']['model_config_snapshot'],
 'calls':calls,'spans':spans,'link':link,'checks':['business identity exact','Root exact by reserved ID','five direct Node Spans; two distinct validator invocations','call IDs scoped to this Root','no business/Trace/Registry FK violations','no Engine or HITL execution']}
(artifact/'live-release-readback-verified.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
print(json.dumps({k:proof[k] for k in ['verified','session_id','workflow_id','root_run_id','distinct_spans','distinct_calls']},ensure_ascii=False))
