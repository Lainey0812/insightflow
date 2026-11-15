"""Final-code confirmation, separate from the first 32-case regression."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,subprocess
root=Path(__file__).resolve().parents[3]
jobs=[('mvp-product-v1-2026-11-04','T04'),('mvp-reliability-holdout-2026-11-04','U02'),('report-draft-v2-2026-11-05/independent','W03'),('report-draft-v2-2026-11-05/independent','W04')]
def run(job):
    path,cid=job;suite=root/'docs/evaluations'/path;folder=suite/'runs/approvalv22-final';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(cid+'-process.log')).open('x') as log:
        subprocess.run([str(root/'.venv/bin/python'),'backend/scripts/run_mvp_acceptance.py','--case',cid,'--run','approvalv22-final','--suite-root',str(suite)],cwd=root,stdout=log,stderr=subprocess.STDOUT)
    print((folder/cid/'result.json').read_text(),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,jobs))
