"""Read back real synthetic browser cases; do not modify business records."""
from pathlib import Path
import sqlite3,json,hashlib
root=Path(__file__).parent
business=Path('/Users/lainey/Desktop/vibe-coding/var/insightflow.sqlite3')
results=[];run_ids=[]
with sqlite3.connect(f'file:{business}?mode=ro',uri=True) as conn:
    for sid,text in conn.execute("SELECT id,state FROM sessions WHERE json_extract(state,'$.file.name')=?",('insightflow-basis-verification.csv',)):
        state=json.loads(text);run_ids.append(state['root_run_id'])
        bases=[json.loads(row[0]) for row in conn.execute('SELECT record FROM plan_analysis_bases WHERE session_id=? ORDER BY plan_version',(sid,))]
        approvals=[json.loads(row[0]) for row in conn.execute('SELECT record FROM approval_analysis_bases WHERE session_id=? ORDER BY plan_version',(sid,))]
        executions=[json.loads(row[0]) for row in conn.execute('SELECT result FROM executions WHERE session_id=? AND result IS NOT NULL',(sid,))]
        reports=[json.loads(row[0]) for row in conn.execute("SELECT report FROM analysis_reports WHERE json_extract(audit,'$.session_id')=?",(sid,))]
        value={'session_id':sid,'workflow_id':state['workflow_id'],'root_run_id':state['root_run_id'],'query':state['user_goal'],
            'status':state['status'],'plan_version':state['current_plan_version'],'intent':state.get('intent'),
            'planner_result':state.get('planner_result'),'basis_versions':bases,'approval_basis_snapshots':approvals,
            'executions':executions,'reports':reports}
        if executions:
            assert state['current_plan_version']==2 and state['status']=='COMPLETED'
            assert bases[-1]==approvals[-1] and bases[-1]['row_grain']=='entity'
            assert executions[0]['plan_version']==2 and executions[0]['execution_status']=='success'
            task=executions[0]['tasks'][0];approved_basis=task['execution_metadata']['analysis_basis']
            assert approved_basis['digest']==bases[-1]['digest']
            result={row['field_0002']:next(v for key,v in row.items() if key!='field_0002') for row in task['result']['rows']}
            assert result=={'咨询':2,'投诉':2},result
            assert reports[0]['execution_metadata'][task['task_id']]['execution_metadata']['analysis_basis']==approved_basis
            value['verified_result']=result;value['binding_verified']=True
        else:
            value['known_bad_case']='Existing constraint grammar did not map an explicit count-basis or optional-boundary phrase; approval remained blocked.'
        results.append(value)
    original='d855167be480454689e4c425f9e8a797'
    before=sqlite3.connect('file:/Users/lainey/Desktop/vibe-coding/var/backups/analysis-basis-v1-2026-11-08/business.sqlite3?mode=ro',uri=True)
    checks={}
    for table,column,where,params in [('sessions','state','id=?',(original,)),('plan_versions','record','session_id=?',(original,)),('plan_approvals','record','session_id=?',(original,)),('executions','result','session_id=?',(original,)),('analysis_reports','report','id=?',('report_f66380c68d99402d8a4363dd24bcc4f6',))]:
        sql=f'SELECT {column} FROM {table} WHERE {where} ORDER BY rowid'
        checks[table]=before.execute(sql,params).fetchall()==conn.execute(sql,params).fetchall()
    assert all(checks.values()),checks
    before.close()
(root/'real-ui-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
(root/'original-records-unchanged.json').write_text(json.dumps(checks,indent=2))
with sqlite3.connect('file:/Users/lainey/Desktop/vibe-coding/var/prompt_registry/registry.sqlite3?mode=ro',uri=True) as conn:
    calls=[json.loads(row[0]) for row in conn.execute('SELECT record FROM llm_calls') if json.loads(row[0]).get('run_id') in run_ids]
(root/'real-llm-call-refs.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2))
print(json.dumps({'cases':len(results),'completed':sum(bool(case.get('binding_verified')) for case in results),'blocked':sum(not case['executions'] for case in results),'actual_model_calls':len(calls),'original_records_unchanged':checks},ensure_ascii=False))
