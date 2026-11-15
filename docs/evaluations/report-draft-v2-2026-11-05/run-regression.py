from pathlib import Path
import concurrent.futures,json,subprocess
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');suites=[root/'docs/evaluations/mvp-product-v1-2026-11-04',root/'docs/evaluations/mvp-reliability-holdout-2026-11-04',root/'docs/evaluations/mvp-reliability-holdout2-2026-11-04']
suites.append(root/'docs/evaluations/report-draft-v2-2026-11-05/independent')
for suite in suites:
 cases=json.loads((suite/'frozen/cases.json').read_text())
 def run(case):
  folder=suite/'runs/draftv2-01';folder.mkdir(parents=True,exist_ok=True)
  name=case['case_id'];cmd=[str(root/'.venv/bin/python'),'backend/scripts/run_mvp_acceptance.py','--case',name,'--run','draftv2-01','--suite-root',str(suite)]
  with (folder/(name+'-process.log')).open('x') as h:r=subprocess.run(cmd,cwd=root,stdout=h,stderr=subprocess.STDOUT)
  p=folder/name/'result.json';result=json.loads(p.read_text()) if p.exists() else {'case_id':name,'status':'process_error','exit_code':r.returncode}
  print(json.dumps(result,ensure_ascii=False),flush=True)
 print('START '+suite.name,flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,cases))
 print('END '+suite.name,flush=True)
