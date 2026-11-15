"""Read-only comparison of actual persisted historical ReportWorkflow runs.

No POST, new runs, synthetic Trace insertion, or LLM calls. Credentials stay in the environment.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import urllib.request
import urllib.error


def main(args):
    if args.output.exists(): raise ValueError('Use a new output file; preserve prior evidence')
    token=os.environ['INSIGHTFLOW_TRACE_VERIFY_TOKEN']
    def request(path, authorized=True):
        req=urllib.request.Request(args.base_url+path,headers={'X-Admin-Token':token} if authorized else {})
        with urllib.request.urlopen(req,timeout=15) as response:
            assert response.headers['Cache-Control']=='no-store'
            return json.load(response)
    def persisted():
        with closing(sqlite3.connect('file:'+str(args.trace_db.resolve())+'?mode=ro',uri=True)) as conn:
            return {rid:hashlib.sha256(raw.encode()).hexdigest() for rid,raw in conn.execute('SELECT id,record FROM trace_runs')}
    before=persisted();examples=[]
    pairs=[('historical_complete_vs_partial','run_138b68217f9c4b9ca26cd2522b33ecf8','run_8f390ea052734511bc3b493618e5d0cc'),
           ('historical_same_execution_retry','run_2a66c1c2b62e4b3c83519c2a9d4fc82a','run_da8e8959c09f44ecbf534ee2a3113f43'),
           ('historical_failed_vs_complete','run_c9c69038b6b44b55b37edafbeb43c264','run_138b68217f9c4b9ca26cd2522b33ecf8')]
    for name,left,right in pairs:
        comparison=request('/admin/comparison?left='+left+'&right='+right)
        assert comparison['comparability']['status']=='partially_comparable'
        assert any(row['left'] and row['right'] for row in comparison['spans'])
        assert comparison['comparability']['git']['status']=='unknown'
        # Match API responses against the original JSON, allowing only explicit schema defaults.
        with closing(sqlite3.connect('file:'+str(args.trace_db.resolve())+'?mode=ro',uri=True)) as conn:
            for side,rid in [('left',left),('right',right)]:
                original=json.loads(conn.execute('SELECT record FROM trace_runs WHERE id=?',(rid,)).fetchone()[0])
                assert comparison[side]['status']==original['status']
                for key,value in original['manifest'].items():assert comparison[side]['manifest'][key]==value
        examples.append({'case':name,'comparison':comparison})
    assert before==persisted()
    try:request('/admin/comparison?left=one&right=two',False)
    except urllib.error.HTTPError as exc:assert exc.code==403
    else:raise AssertionError('Admin comparison unexpectedly public')
    payload={'scope':'Real saved ReportWorkflow qwen runs; prior upstream preparation used labelled synthetic fixtures.',
             'new_llm_calls':0,'historical_records_unchanged':True,'unauthorized_status':403,'examples':examples}
    encoded=json.dumps(payload,ensure_ascii=False,indent=2)
    assert token not in encoded
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:out.write(encoded+'\n')
    print(json.dumps({'comparisons':[(e['case'],e['comparison']['comparability']['status']) for e in examples],
                      'unchanged_database_records':len(before),'new_llm_calls':0},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--trace-db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args())
