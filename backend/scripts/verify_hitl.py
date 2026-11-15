"""Public API acceptance with real sales.csv and simulated user confirmation.

Run from backend: ../.venv/bin/python scripts/verify_hitl.py
No direct approval construction, production database mutation, LLM or Mock calls.
The confirmation request is an automated test, never represented as a real human approval.
"""
import io
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings

class NoLLM:
    async def generate(self,request):
        raise AssertionError('Acceptance must not call an LLM or a Mock provider')

def verify():
    root=Path(__file__).resolve().parents[2]
    content=(root/'examples/sales.csv').read_bytes()
    candidate=json.loads((root/'examples/sales-review-plan.json').read_text())
    goal=candidate['intent']['analysis_goal']['business_goal']
    with TemporaryDirectory(prefix='insightflow-hitl-') as directory:
        settings=Settings(Path(directory))
        with TestClient(create_app(settings,provider=NoLLM())) as client:
            def post(path,body,status=200):
                response=client.post('/api/v1'+path,json=body)
                assert response.status_code==status,response.text
                return response.json()
            response=client.post('/api/v1/sessions',data={'manual_review':'true','goal':goal},files={'file':('sales.csv',content,'text/csv')})
            assert response.status_code==201,response.text
            state=response.json(); token=state.pop('review_access_token'); client.headers['X-Session-Token']=token
            sid=state['id']; path=f'/sessions/{sid}'
            candidate['plan'].update(state['dataset_ref'])
            state=post(path+'/plans',{'expected_revision':state['revision'],**candidate})
            initial=state['review_plan']
            assert client.get('/api/v1'+path+'/plan').json()==initial
            unapproved=post('/executions',{'session_id':sid,'plan_id':initial['plan_id'],'plan_version':1,'execution_request_id':'unapproved-attempt'},409)
            assert unapproved['error']['code']=='V1_APPROVAL_REQUIRED'
            state=post(path+'/plan-revisions',{'expected_revision':state['revision'],'plan_id':initial['plan_id'],'plan_version':1,'remove_task_ids':['A03']})
            current=state['review_plan']; assert current['plan_version']==2
            assert current['validated_plan']['coverage_status']=='complete'
            assert client.get('/api/v1'+path+'/plans/1').json()==initial
            approval_request={k:current[k] for k in ('plan_id','plan_version','dataset_id','dataset_version','validation_version')}
            approval_request.update(expected_revision=state['revision'],approval_request_id='simulated-user-confirmation',acknowledged_warnings=[])
            state=post(path+'/approvals',approval_request)
            assert post(path+'/approvals',approval_request)==state
            execution_request={'session_id':sid,'plan_id':current['plan_id'],'plan_version':2,'execution_request_id':'sales-hitl-verification'}
            old=post('/executions',execution_request|{'plan_version':1,'execution_request_id':'old-plan-attempt'},409)
            assert old['error']['code']=='PLAN_VERSION_MISMATCH'
            execution=post('/executions',execution_request)
            assert post('/executions',execution_request)==execution
            assert client.get('/api/v1'+f'/executions/{execution["execution_id"]}').json()==execution
            audits=client.get('/api/v1'+path+'/approvals').json()
            history=client.get('/api/v1'+path+'/plans').json()
            frame=pd.read_csv(io.BytesIO(content))
            expected=(frame.loc[frame['销售额']>=18000].groupby('地区',sort=False).agg(record_count=('销售额','size'),sales_total=('销售额','sum'))
                .reset_index().sort_values('sales_total',ascending=False,kind='stable').head(1).rename(columns={'地区':'field_0003'}).to_dict('records'))
            totals=[{'sales_total':int(frame['销售额'].sum()),'record_count':len(frame)}]
            assert execution['tasks'][0]['result']['rows']==expected
            assert execution['tasks'][1]['result']['rows']==totals
            assert execution['approval_id']==audits[0]['approval_id']
            assert audits[0]['execution_ids']==[execution['execution_id']]
            assert len(history)==2 and len(audits)==1
        with TestClient(create_app(settings,provider=NoLLM())) as reopened:
            reopened.headers['X-Session-Token']=token
            assert reopened.get('/api/v1'+f'/executions/{execution["execution_id"]}').json()==execution
            assert reopened.get('/api/v1'+path+'/plans').json()==history
            assert reopened.get('/api/v1'+path+'/approvals').json()==audits
            assert reopened.get('/api/v1'+path).json()['review_status']=='completed'
        report={'source_file':'examples/sales.csv','source_rows':len(frame),'source_columns':len(frame.columns),
            'approval_origin':'automated confirmation through public HITL API in isolated temporary DB; not a production human approval',
            'session_id':sid,'plan_versions':history,'approval_request':approval_request,'approvals':audits,
            'execution_request':execution_request,'execution_id':execution['execution_id'],
            'pandas_baseline':{'A01':expected,'A02':totals},
            'checks':{'unapproved_rejected':True,'old_version_rejected':True,'deletion_revalidated':True,'immutable_old_version_retained':True,
                'approval_persisted':True,'approval_id_linked':True,'duplicate_approval_replayed':True,'execution_replayed':True,
                'fresh_application_read_matches':True,'pandas_matches':True,'llm_calls':0,'mock_calls':0}}
        for filename,payload in [('hitl-verification.json',report),('hitl-execution.example.json',execution)]:
            (root/'docs'/filename).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'execution_id':execution['execution_id'],'approval_id':execution['approval_id'],'plan_version':2,'checks':report['checks']},ensure_ascii=False,indent=2))

if __name__=='__main__': verify()
