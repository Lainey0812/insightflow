from pathlib import Path
import json,hashlib,collections,shutil,zipfile
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');base=root/'docs/evaluations/direction-first-acceptance-v1-2026-11-09';mid=root/'docs/evaluations/report-reliability-v2.1-2026-11-09';latest=root/'docs/evaluations/report-reliability-v2.1.1-2026-11-09';impl=root/'docs/implementations/report-reliability-v2.1-2026-11-09'

def save(path,value):
 with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)

rows=[];call_count=0;problems=[]
for d in sorted((latest/'runs/candidate-v211-01').iterdir()):
 r=json.loads((d/'result.json').read_text());trace=json.loads((d/'workflow-trace.json').read_text());calls=json.loads((d/'llm-calls.json').read_text());call_count+=len(calls)
 report=json.loads((d/'analysis-report.json').read_text()) if (d/'analysis-report.json').exists() else None
 before=json.loads((base/'runs/frozen-baseline-01'/d.name/'result.json').read_text())
 nodes=trace['nodes'];spanids={n['span_id'] for n in nodes}
 oracle=json.loads((d/'execution-oracle.json').read_text()) if (d/'execution-oracle.json').exists() else []
 value_errors=[x for x in oracle if x.get('status') not in {'failed','skipped'} and not x['passed']]
 skipped=[x for x in oracle if x.get('status') in {'failed','skipped'}]
 record={'case_id':d.name,'baseline_report_status':before.get('report_status','expected_stop'),
   'report_status':report['report_status'] if report else 'expected_stop','goal_coverage':r.get('goal_coverage'),
   'execution_status':r.get('execution_status'),'raw_runner_status':r['status'],'raw_runner_errors':r.get('errors'),
   'workflow_id':r['workflow_id'],'root_run_id':r['root_run_id'],'report_id':r.get('report_id'),
   'span_count':len(nodes),'call_count':len(calls),'elapsed_seconds':r['elapsed_seconds'],
   'collection':trace['collection'],'direct_root_links':all(n['run_id']==r['root_run_id'] and n['parent_span_id'] is None for n in nodes),
   'call_links':all(c['run_id']==r['root_run_id'] and c['span_id'] in spanids for c in calls),
   'successful_task_value_mismatches':value_errors,'skipped_or_failed_tasks':skipped,
   'missing_direction_ids':next(iter(report['execution_metadata'].values())).get('missing_direction_ids',[]) if report else [],
   'insight_count':len(report['insights']) if report else 0}
 rows.append(record)
 if r.get('errors'):
  state=json.loads((d/'prepared-session.json').read_text());checked=state['review_plan']['validated_plan']
  problems.append({'case_id':d.name,'workflow_id':r['workflow_id'],'raw_runner_errors':r['errors'],
   'classification':'upstream_planning_f0_partial_execution','validator_results':checked['validation_results'],
   'report_status':report['report_status'],'report_uncompleted_tasks':report['uncompleted_tasks'],
   'explanation':'Two originally planned tasks are deterministically non-executable; Engine skips them and preserves successful tasks. The inherited runner reports CALCULATION for any skipped task. No successful task numeric mismatch found. Do not relabel as a fully passed case or modify Planner/Engine in this Report-only task.'})
fixed=json.loads((latest/'fixed-upstream-release-results.json').read_text());fixed_old=json.loads((latest/'fixed-upstream-results.json').read_text())
summary={'full_workflow_cases':10,'report_statuses':dict(collections.Counter(r['report_status'] for r in rows)),
 'execution_statuses':dict(collections.Counter(r['execution_status'] for r in rows if r['execution_status'])),
 'full_workflow_llm_calls':call_count,'fixed_upstream_release_reports':dict(collections.Counter(r['report_status'] for r in fixed)),
 'fixed_upstream_release_calls':sum(r['http_calls'] for r in fixed),
 'missing_direction_count':sum(len(r['missing_direction_ids']) for r in rows),
 'successful_task_value_mismatch_count':sum(len(r['successful_task_value_mismatches']) for r in rows),
 'trace_links_all_valid':all(r['direct_root_links'] and r['call_links'] and r['collection']['status']=='observed' for r in rows),
 'latest_full_chain_mvp_pass':False,'unresolved_full_chain_case_ids':[r['case_id'] for r in rows if r['raw_runner_errors']],
 'note':'Final exact-reference normalization was tested with full automated suite and fixed original upstream real reports. The fresh full-chain run uses the immediately preceding composition-v0.11; final patch is composition-v0.12. Do not present these as one identical-source experiment.'}
save(latest/'final-case-comparison.json',rows);save(latest/'final-summary.json',summary);save(latest/'remaining-bad-cases.json',problems)
release=json.loads((latest/'release-source.json').read_text());save(latest/'release-source-verified.json',{'all_unchanged':all(hashlib.sha256((root/f).read_bytes()).hexdigest()==h for f,h in release.items()),'files':len(release)})
for src,dest in [('/tmp/run-req104.py',mid/'run_batch.py'),('/tmp/run-req104-v211.py',latest/'run_batch.py'),('/tmp/fixed-upstream-req104-v211.py',latest/'fixed-upstream-runner.py'),('/tmp/fixed-upstream-req104-release.py',latest/'fixed-upstream-release-runner.py')]:shutil.copy2(src,dest)
for name in ['req104-fixed-upstream-v211.log','req104-fixed-upstream-release.log']:shutil.copy2(Path('/tmp')/name,latest/name)
files=['backend/app/reporting/draft_v2.py','backend/app/reporting/materialize_v2.py','backend/app/reporting/batches.py','backend/app/reporting/prompt.py','backend/app/services/analysis_report.py','backend/app/llm/templates.py','backend/app/reporting/presentation.py','backend/app/review/output_boundaries.py','backend/tests/test_prompt_registry.py','backend/tests/test_report_reliability_v21.py','backend/tests/test_report_module.py']
save(impl/'changed-files.json',files)
with zipfile.ZipFile(impl/'after.zip','x',zipfile.ZIP_DEFLATED) as z:
 for name in files:z.write(root/name,name)
# Store prompt deltas without overwriting previous snapshots or source files.
import difflib
with zipfile.ZipFile(impl/'before.zip') as z:old=z.read('backend/app/reporting/prompt.py').decode()
(impl/'prompt.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),(root/'backend/app/reporting/prompt.py').read_text().splitlines(True),fromfile='report-insights-v2.0',tofile='report-insights-v2.1.1')))
for log in Path('/tmp').glob('req104-*.log'):
 target=impl/log.name
 if not target.exists():shutil.copy2(log,target)
print(json.dumps(summary,ensure_ascii=False,indent=2))
