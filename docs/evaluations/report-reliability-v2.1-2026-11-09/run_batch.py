import concurrent.futures,subprocess,json,hashlib
from pathlib import Path
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');suite=root/'docs/evaluations/report-reliability-v2.1-2026-11-09'
plan=json.loads((suite/'run-plan.json').read_text())
assert hashlib.sha256((root/plan['runner']).read_bytes()).hexdigest()==plan['runner_sha256']
def execute(case):
 log=suite/(case+'-process.log')
 with log.open('x') as output:
  proc=subprocess.run([str(root/'.venv/bin/python'),plan['runner'],'--case',case,'--run',plan['run_name'],'--suite-root',str(suite)],cwd=root,stdout=output,stderr=subprocess.STDOUT)
 result=suite/'runs'/plan['run_name']/case/'result.json'
 data=json.loads(result.read_text()) if result.exists() else {'status':'process_failed','errors':['NO_RESULT'],'returncode':proc.returncode}
 print(json.dumps({'case_id':case,**{k:data[k] for k in ['status','errors','elapsed_seconds','report_status','llm_call_count'] if k in data}},ensure_ascii=False),flush=True)
 return {'case_id':case,'returncode':proc.returncode,'result_path':str(result.relative_to(suite)),'result':data}
with concurrent.futures.ThreadPoolExecutor(max_workers=plan['max_concurrent_cases']) as pool:
 rows=list(pool.map(execute,plan['cases']))
with (suite/'batch-results.json').open('x') as f:json.dump(rows,f,ensure_ascii=False,indent=2)
