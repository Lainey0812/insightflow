"""Read-only local verification; never copies user rows, prompts or tokens to docs."""
from pathlib import Path
import sqlite3,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'backend'))
from app.observability.provenance import digest
from app.domain.analysis_report import AnalysisReport
from app.reporting.claims import missing_metrics
DATA=ROOT.parent/'var';SID='d855167be480454689e4c425f9e8a797';EID='exec_f86303595be2401d9b7541f9fbe0c8af'
def ro(path):
    c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
current=ro(DATA/'insightflow.sqlite3');previous=ro(DATA/'backups/report-capacity-v1-before-recovery-2026-11-05/insightflow.sqlite3')
old_execution=previous.execute('SELECT * FROM executions WHERE id=?',(EID,)).fetchone()
execution=current.execute('SELECT * FROM executions WHERE id=?',(EID,)).fetchone()
state=json.loads(current.execute('SELECT state FROM sessions WHERE id=?',(SID,)).fetchone()['state'])
generation=json.loads(current.execute('SELECT record FROM report_generations WHERE execution_id=?',(EID,)).fetchone()['record'])
row=current.execute('SELECT report,audit FROM analysis_reports WHERE id=?',(generation['report_id'],)).fetchone()
report=AnalysisReport.model_validate_json(row['report']);audit=json.loads(row['audit']);receipt=audit['commit_receipt']
root=state['root_run_id'];traces=ro(DATA/'observability/trace.sqlite3')
spans=[json.loads(r['record']) for r in traces.execute('SELECT record FROM trace_spans WHERE run_id=?',(root,))]
report_spans=[s for s in spans if s['attributes'].get('report_attempt')==generation['attempt']]
runs=[json.loads(r['record']) for r in traces.execute('SELECT record FROM trace_runs WHERE execution_id=?',(EID,))]
registry=ro(DATA/'prompt_registry/registry.sqlite3')
calls=[json.loads(r['record']) for r in registry.execute('SELECT record FROM llm_calls')]
calls=[r for r in calls if r.get('span_id') in {s['span_id'] for s in report_spans}]
call_checks=[]
for call in calls:
    s=json.loads(registry.execute('SELECT record FROM llm_request_snapshots WHERE id=?',(call['request_snapshot_id'],)).fetchone()['record'])
    # Read under local authority, emit only hashes/controlled ID counts.
    payload=json.loads(registry.execute('SELECT payload FROM llm_request_payloads WHERE snapshot_id=?',(call['request_snapshot_id'],)).fetchone()['payload'])
    body=json.loads(payload['messages'][1]['content'])
    call_checks.append({'call_id':call['call_id'],'span_id':call['span_id'],'run_id':call['run_id'],
        'status':call['status'],'retry_index':call['retry_index'],'duration_ms':call['duration_ms'],
        'template_snapshot_id':call['template_snapshot_id'],'request_snapshot_id':call['request_snapshot_id'],
        'messages_hash_valid':s['messages_hash']==digest(payload['messages']),
        'schema_hash_valid':s['schema_hash']==digest(payload['response_format']),
        'request_hash_valid':s['request_hash']==digest(payload),
        'evidence_group_count':len(body['evidence_groups']),'core_group_count':len(body['required_core_groups'])})
immutable={}
for table in ['plan_versions','plan_approvals']:
    columns={r['name'] for r in current.execute('PRAGMA table_info('+table+')')}
    if 'session_id' in columns:
        old=[tuple(r) for r in previous.execute('SELECT * FROM '+table+' WHERE session_id=? ORDER BY rowid',(SID,))]
        new=[tuple(r) for r in current.execute('SELECT * FROM '+table+' WHERE session_id=? ORDER BY rowid',(SID,))]
        immutable[table]=old==new
covered={(e.task_id,e.result_field) for e in report.evidence if any(e.evidence_id in i.evidence_refs for i in report.insights)}
required={(e.task_id,e.result_field) for e in report.evidence if report.task_metadata[e.task_id].priority=='P0' and not e.result_field.startswith('$')}
output={'session_id':SID,'workflow_id':state['workflow_id'],'root_run_id':root,'execution_id':EID,'report_id':report.report_id,
 'execution_unchanged':tuple(old_execution)==tuple(execution),'immutable_records_unchanged':immutable,
 'execution_count_unchanged':previous.execute('SELECT count(*) FROM executions WHERE session_id=?',(SID,)).fetchone()[0]==current.execute('SELECT count(*) FROM executions WHERE session_id=?',(SID,)).fetchone()[0],
 'report_attempt':generation['attempt'],'report_status':report.report_status,'goal_coverage':report.goal_coverage,
 'required_core_metric_count':len(required),'covered_core_metric_count':len(required & covered),
 'missing_core_metrics':missing_metrics(report.evidence,report.task_metadata,report.insights),
 'insight_count':len(report.insights),'unique_insight_ids':len({i.insight_id for i in report.insights})==len(report.insights),
 'report_batches':next(iter(report.execution_metadata.values()))['report_batches'],
 'calls':call_checks,'commit_bound_to_same_workflow':receipt['workflow_id']==state['workflow_id'] and receipt['execution_id']==EID,
 'persistence_span_verified':any(s['span_id']==receipt['persistence_span_id'] and s['status']=='complete' for s in report_spans),
 'all_current_nodes_direct_root':all(s['run_id']==root and s['parent_span_id'] is None for s in report_spans),
 'current_report_spans':[{k:s.get(k) for k in ['span_id','name','node_attempt','status','duration_ms','error_code']} for s in report_spans],
 'report_run_history':[{'run_id':v['run_id'],'attempt':v['attempt'],'status':v['status'],'error_code':v.get('error_code')} for v in runs if v.get('kind')!='workflow']}
with (Path(__file__).parent/'live-recovery-evidence.json').open('x') as h:json.dump(output,h,ensure_ascii=False,indent=2)
print(json.dumps({k:output[k] for k in ['execution_unchanged','immutable_records_unchanged','execution_count_unchanged','report_status','required_core_metric_count','covered_core_metric_count','insight_count','persistence_span_verified']}))
