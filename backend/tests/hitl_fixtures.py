"""Real plans submitted through public APIs; no fabricated approval snapshots."""
import copy
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
GOAL='比较高额销售记录的地区分布，并统计总销售额'

def candidate(state):
    existing=json.loads((ROOT/'docs/engine-verification.json').read_text())['validated_plan']
    plan=copy.deepcopy(existing['plan']); plan.update(state['dataset_ref']); plan['plan_id']='sales_review_'+state['id']
    plan['core_requirements']=[{'requirement_id':'C01','description':'高额记录地区排名'},{'requirement_id':'C02','description':'整体销售总额'}]
    plan['tasks'][1]['requirement_ids']=['C02']
    extra=copy.deepcopy(plan['tasks'][1]); extra.update(task_id='A03',title='辅助销售汇总',priority='P2',priority_reason='辅助核对，可删除',requirement_ids=[])
    plan['tasks'].append(extra)
    return {'plan':plan,'intent':existing['intent_snapshot']}

def create(client):
    r=client.post('/api/v1/sessions',data={'goal':GOAL,'manual_review':'true'},files={'file':('sales.csv',(ROOT/'examples/sales.csv').read_bytes(),'text/csv')})
    assert r.status_code==201,r.text
    state=r.json(); client.headers['X-Session-Token']=state.pop('review_access_token'); return state

def save(client,state,data=None):
    r=client.post(f"/api/v1/sessions/{state['id']}/plans",json={'expected_revision':state['revision'],**(data or candidate(state))})
    assert r.status_code==200,r.text
    return r.json()

def revision(state,ids):
    return {'expected_revision':state['revision'],'plan_version':state['review_plan']['plan_version'],'plan_id':state['review_plan']['plan_id'],'remove_task_ids':ids}

def approval(state,warnings=None,request_id='user-confirmation-1'):
    record=state['review_plan']
    return {k:record[k] for k in ('plan_id','plan_version','dataset_id','dataset_version','validation_version')} | {'expected_revision':state['revision'],'approval_request_id':request_id,'acknowledged_warnings':warnings or []}

def execution(state,request_id='real-execution-1'):
    return {'session_id':state['id'],'plan_id':state['review_plan']['plan_id'],'plan_version':state['review_plan']['plan_version'],'execution_request_id':request_id}
