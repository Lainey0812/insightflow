from pathlib import Path
import concurrent.futures,json,subprocess,time
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');out=root/'docs/evaluations/mvp-product-v1-2026-11-04';cases=json.loads((out/'frozen/cases.json').read_text())
def run(case):
 name=case['case_id'];log=out/'runs/baseline01'/(name+'-process.log')
 with log.open('x') as f:r=subprocess.run([str(root/'.venv/bin/python'),'backend/scripts/run_mvp_acceptance.py','--case',name,'--run','baseline01'],cwd=root,stdout=f,stderr=subprocess.STDOUT)
 p=out/'runs/baseline01'/name/'result.json'
 result=json.loads(p.read_text()) if p.exists() else {'case_id':name,'status':'process_error','exit_code':r.returncode}
 print(json.dumps(result,ensure_ascii=False),flush=True)
for split in ['core','holdout']:
 print('START '+split,flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[c for c in cases if c['split']==split and c['case_id']!='S01']))
 print('END '+split,flush=True)
