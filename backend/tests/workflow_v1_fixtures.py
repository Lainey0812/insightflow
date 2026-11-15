"""Controlled transport fixtures, NOT evidence of real LLM semantic quality."""
import json
from app.llm.base import LLMResponse
from intent_fixtures import intent_payload

CSV = '日期,地区,品类,销售额,成本,状态\n2026-01-02,华东,软件,100,60,已完成\n2026-02-01,华南,硬件,80,50,已完成\n2026-03-02,华东,软件,200,90,未完成\n2025-12-12,华北,软件,40,20,已完成\n'.encode()


def intent():
    return intent_payload('exploratory', 'proceed', business_goal='探索销售数据的主要分布和规律')


def draft(context):
    ids = [r['requirement_id'] for r in context['core_requirements']]
    def task(id, priority, steps):
        return {'task_id':id,'title':'地区销售汇总' if id=='A01' else '整体销售额',
            'business_question':'比较地区销售额' if id=='A01' else '整体规模是多少',
            'priority':priority,'priority_reason':'删除后缺少核心地区分布' if priority=='P0' else '补充整体基准',
            'requirement_ids':ids if priority=='P0' else [],'depends_on':[],'missing_inputs':[], 'steps':steps}
    return {'tasks':[task('A01','P0',[{'step_id':'S01','operation':'group_aggregate','params':{
        'dimensions':['field_0002'],'metrics':[{'function':'sum','field':'field_0004','alias':'sales_total'},
        {'function':'count','field':None,'alias':'records'}]}}]),
        task('A02','P1',[{'step_id':'S01','operation':'aggregate','params':{'metrics':[{'function':'sum','field':'field_0004','alias':'sales_total'}]}}])]}


class ControlledWorkflowProvider:
    def __init__(self, intents=None, planner=None, mock=False):
        self.intents=list(intents or [intent()]);self.planner=planner or draft;self.mock=mock;self.requests=[];self.intent_calls=0
    async def generate(self,request):
        self.requests.append(request)
        if request.purpose=='intent_v1':
            value=self.intents[min(self.intent_calls,len(self.intents)-1)];self.intent_calls+=1
        elif request.purpose=='analysis_planner_v1':value=self.planner(json.loads(request.instruction))
        else:raise AssertionError('Workflow must never call Report or another LLM purpose')
        if isinstance(value,Exception):raise value
        return LLMResponse(text=json.dumps(value,ensure_ascii=False),provider='controlled-transport-test',model='unit-fixture',is_mock=self.mock)


def create_real(client,content=CSV,name='workflow.csv',goal='帮我探索这份销售数据'):
    response=client.post('/api/v1/sessions',data={'goal':goal,'real_workflow':'true'},files={'file':(name,content)})
    assert response.status_code==201,response.text
    initial=response.json();assert initial['status']=='CREATED'
    client.headers['X-Session-Token']=initial['review_access_token']
    return client.get('/api/v1/sessions/'+initial['id']).json()
