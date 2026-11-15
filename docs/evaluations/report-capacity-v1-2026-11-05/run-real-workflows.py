from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,json
ROOT=Path(__file__).resolve().parents[3]
folder=ROOT/'docs/evaluations/mvp-product-v1-2026-11-04/runs/capacity01';folder.mkdir(parents=True,exist_ok=True)
def run(case):
 with (folder/(case+'-process.log')).open('x') as log:
  subprocess.run([str(ROOT/'.venv/bin/python'),'backend/scripts/run_mvp_acceptance.py','--case',case,'--run','capacity01'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 print((folder/case/'result.json').read_text(),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['S01','S03']))
