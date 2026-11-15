"""Isolated browser verification server: actual saved current templates, one version/node.
Uses only synthetic in-memory CSV fixtures and scripted local HTTP responses.
Never registers a fictional historical version, calls an external model, or touches user data.
Test credentials are local-only examples, not production keys. Do not deploy this script.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
DIRECTORY=Path(tempfile.mkdtemp(prefix='insightflow-registry-v1-browser-'))
os.environ['INSIGHTFLOW_DATA_DIR']=str(DIRECTORY)
os.environ['INSIGHTFLOW_LLM_MODEL']=''
os.environ['INSIGHTFLOW_LLM_BASE_URL']=''
os.environ['INSIGHTFLOW_LLM_API_KEY']=''
import httpx
import uvicorn
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.llm.compatible_provider import CompatibleLLMProvider
from intent_fixtures import intent_payload
from planning_fixtures import recruiting_profile

async def handler(request):
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
        'content':json.dumps(intent_payload(business_goal='比较城市岗位数量'),ensure_ascii=False)}}]})

provider=CompatibleLLMProvider('https://local-test.invalid/v1','qwen3.8-flash',transport=httpx.MockTransport(handler))
app=create_app(Settings(DIRECTORY,admin_read_token='local-browser-read',admin_snapshot_token='local-browser-snapshot'),provider=provider)
for service in (app.state.intent_parser,app.state.analysis_planner,app.state.report_service):
    app.state.llm_captures.repository.register(service.prompt_source.snapshot)
asyncio.run(app.state.intent_parser.parse('比较各城市岗位数量（隔离浏览器验证）',recruiting_profile()))
asyncio.run(app.state.intent_parser.parse('比较各城市岗位数量，保留全部城市（隔离浏览器验证）',recruiting_profile()))

if __name__=='__main__':
    output=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('api-examples')
    output.mkdir(exist_ok=False)
    with TestClient(app) as client:
        headers={'X-Admin-Token':'local-browser-read'}
        catalog=client.get('/admin/prompts',headers=headers).json()
        identity=next(i for i in catalog['items'] if i['node_id']=='intent_parser')['latest_registered']['template_snapshot_id']
        urls={'catalog':'/admin/prompts','history':'/admin/prompts/intent_parser/versions',
              'version':'/admin/prompts/intent_parser/versions/'+identity,
              'calls':'/admin/prompts/intent_parser/versions/'+identity+'/calls'}
        saved={}
        for key,url in urls.items():
            response=client.get(url,headers=headers);assert response.status_code==200
            saved[key]=response.json()
            (output/(key+'.json')).write_text(json.dumps({'source':'isolated_actual_backend_api','external_model_calls':0,'response':saved[key]},ensure_ascii=False,indent=2)+'\n')
        call_id=saved['calls']['items'][0]['call']['call_id']
        summary=client.get('/admin/llm-calls/'+call_id+'/summary',headers=headers)
        assert summary.status_code==200
        (output/'call-summary.json').write_text(json.dumps({'source':'isolated_actual_backend_api','response':summary.json()},ensure_ascii=False,indent=2)+'\n')
    print('Isolated browser verification API: 3 actual current templates, 2 scripted transport calls, no fictional historical versions.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8011)
