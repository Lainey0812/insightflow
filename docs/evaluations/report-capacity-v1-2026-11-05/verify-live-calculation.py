"""Independent Pandas read-only baseline, without calling Engine or writing Trace."""
from pathlib import Path
import sys,sqlite3,json,hashlib
import pandas as pd
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'backend/scripts'))
from run_mvp_acceptance import reference_chain,equivalent
DATA=ROOT.parent/'var';SID='d855167be480454689e4c425f9e8a797';EID='exec_f86303595be2401d9b7541f9fbe0c8af'
c=sqlite3.connect('file:'+str(DATA/'insightflow.sqlite3')+'?mode=ro',uri=True)
state=json.loads(c.execute('SELECT state FROM sessions WHERE id=?',(SID,)).fetchone()[0])
execution=json.loads(c.execute('SELECT result FROM executions WHERE id=?',(EID,)).fetchone()[0])
file=state['file'];path=DATA/'uploads'/(file['id']+file['extension']);content=path.read_bytes()
profile=state['profile'];assert hashlib.sha256(content).hexdigest()==file['content_sha256']==profile['content_sha256']
frame=pd.read_csv(path,encoding=profile['options']['encoding'],header=profile['options']['header_row']-1)
frame.columns=[f['field_id'] for f in profile['fields']]
checks=[]
for task in state['review_plan']['validated_plan']['plan']['tasks']:
    expected,_=reference_chain(frame,task)
    actual=next(t['result']['rows'] for t in execution['tasks'] if t['task_id']==task['task_id'])
    checks.append({'task_id':task['task_id'],'matches_independent_pandas':equivalent(expected,actual),
                   'expected_row_count':len(expected),'actual_row_count':len(actual)})
result={'execution_id':EID,'source_integrity_verified':True,'source_row_count':len(frame),'tasks':checks,
        'all_match':all(t['matches_independent_pandas'] for t in checks),'engine_reexecuted':False}
with (Path(__file__).parent/'live-calculation-check.json').open('x') as h:json.dump(result,h,ensure_ascii=False,indent=2)
print(json.dumps(result))
