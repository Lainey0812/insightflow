from pathlib import Path
import sys,json,copy,httpx
root=Path('/Users/lainey/Desktop/vibe-coding/insightflow');sys.path.insert(0,str(root/'backend/tests'))
from hitl_fixtures import candidate,approval,revision,execution,GOAL
out=root/'docs/implementations/hitl-review-v3-2026-11-08/live-api.json'
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30) as c:
 def checked(r):
  assert r.is_success,r.text
  return r.json()
 state=checked(c.post('/api/v1/sessions',data={'goal':GOAL,'manual_review':'true'},files={'file':('hitl-v3-local-test.csv',(root/'examples/sales.csv').read_bytes(),'text/csv')}))
 c.headers['X-Session-Token']=state.pop('review_access_token')
 state=checked(c.post(f'/api/v1/sessions/{state["id"]}/plans',json={'expected_revision':state['revision'],**candidate(state)}));sid=state['id']
 before=state
 approved=checked(c.post(f'/api/v1/sessions/{sid}/approvals',json=approval(state,request_id='v3-local-before-edit')))
 t=next(t for t in state['review_plan']['validated_plan']['plan']['tasks'] if t['task_id']=='A03');s=t['steps'][0];params=copy.deepcopy(s['params']);params['metrics'][0]['function']='avg'
 state=checked(c.post(f'/api/v1/sessions/{sid}/plan-revisions',json={**revision(approved,[]),'task_edits':[{'task_id':'A03','step_params':{s['step_id']:params}}]}))
 after_edit=state
 assert state['current_plan_version']==2 and state['engine_approval'] is None
 old_execution=c.post('/api/v1/executions',json=execution(approved))
 assert old_execution.status_code==409,old_execution.text
 state=checked(c.post(f'/api/v1/sessions/{sid}/plan-revisions',json=revision(state,['A03'])))
 assert state['current_plan_version']==3 and not state['engine_approval']
 versions=checked(c.get(f'/api/v1/sessions/{sid}/plans'));assert len(versions)==3 and versions[0]==before['review_plan']
 overview=checked(c.get(f'/api/v1/sessions/{sid}/review'))
 out.write_text(json.dumps({'method':'Real local CSV + human-constructed plan via existing public API; no model calls',
  'session_id':sid,'before':before,'after_approval':approved,'after_edit':after_edit,'after_delete':state,'review':overview,
  'old_execution_rejected':old_execution.json(),'versions_unchanged':versions[0]==before['review_plan']},ensure_ascii=False,indent=2))
 print(json.dumps({'session_id':sid,'versions':len(versions),'old_execution_status':old_execution.status_code,'latest_version':state['current_plan_version'],'artifact':str(out)},ensure_ascii=False))
