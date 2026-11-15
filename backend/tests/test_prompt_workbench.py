"""Prompt debugging is a separate captured call, never a business Workflow."""
import asyncio
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.domain.errors import AppError
from app.main import create_app
from app.services.prompt_workbench import DebugRequest, PromptWorkbench
from app.services.intent_parser import IntentParserService
from app.observability.provenance import digest
from app.storage.prompt_registry import template_content, PromptRegistryRepository
from test_prompt_registry import provider, calls


def setup(tmp_path, outputs=None):
    llm,repo,bodies=provider(tmp_path,outputs)
    original=repo.register(IntentParserService(llm).prompt_source.snapshot)
    return llm,repo,bodies,original


def body(template, **kw):
    return DebugRequest(node_id='intent_parser',snapshot_ids=[template.template_snapshot_id],
        case_name='synthetic minimal test',instruction='{"user_query":"按城市计数"}',
        response_schema={'type':'object','properties':{},'additionalProperties':False},**kw)


def test_draft_capture_persistence_and_runtime_unchanged(tmp_path):
    llm,repo,bodies,old=setup(tmp_path)
    service=PromptWorkbench(repo,llm)
    result=asyncio.run(service.run(body(old,draft_system='Return only supported structured intent.')))
    actual=calls(repo)[0]
    assert actual.run_id is None and actual.span_id is None
    assert actual.template_snapshot_id!=old.template_snapshot_id
    assert bodies[0]['messages'][0]['content']=='Return only supported structured intent.'
    assert repo.template(old.template_snapshot_id)==old
    draft=repo.template(actual.template_snapshot_id)
    assert draft.provenance=='admin_debug_draft'
    assert result['results'][0]['status']=='succeeded'
    assert repo.payload(actual.request_snapshot_id)['messages']==bodies[0]['messages']
    restarted=PromptWorkbench(PromptRegistryRepository(tmp_path/'registry'),llm)
    page=restarted.cases('intent_parser',draft.template_snapshot_id)
    assert page['total']==1 and page['items'][0]['sides'][0]['calls'][0]['call_id']==actual.call_id
    with repo.connect() as c:
        with pytest.raises(sqlite3.IntegrityError):c.execute('DELETE FROM prompt_debug_cases')


def test_diff_same_input_separate_call_ids_and_failure_keeps_other_result(tmp_path):
    llm,repo,bodies,old=setup(tmp_path,[503,{'ok':True}])
    other=old.model_copy(update={'version':old.version+'-test','system_template':'Other system'})
    sha=digest(template_content(other));other=repo.register(other.model_copy(update={'template_snapshot_id':'pt_'+sha,'content_hash':sha}))
    request=body(old).model_copy(update={'snapshot_ids':[old.template_snapshot_id,other.template_snapshot_id]})
    result=asyncio.run(PromptWorkbench(repo,llm).run(request))
    assert result['results'][0]['error_code']
    assert result['results'][1]['status']=='succeeded'
    assert bodies[0]['messages'][1]==bodies[1]['messages'][1]
    assert bodies[0]['response_format']==bodies[1]['response_format']
    assert len({c.call_id for c in calls(repo)})==2
    assert all(c.retry_index==0 for c in calls(repo))


def test_ownership_duplicate_and_schema_reject_before_http(tmp_path):
    llm,repo,bodies,old=setup(tmp_path)
    service=PromptWorkbench(repo,llm)
    for update in [{'node_id':'analysis_planner'}, {'snapshot_ids':[old.template_snapshot_id]*2}, {'response_schema':{'type':'array'}}]:
        with pytest.raises(AppError):asyncio.run(service.run(body(old).model_copy(update=update)))
    assert not bodies
    assert service.cases('intent_parser',old.template_snapshot_id)['total']==0


def test_debug_api_requires_write_and_snapshot_permissions(tmp_path):
    llm,_,bodies,_=setup(tmp_path/'provider')
    app=create_app(Settings(tmp_path/'app',admin_read_token='read',admin_snapshot_token='raw',admin_annotation_token='write'),provider=llm)
    with TestClient(app) as client:
        template=app.state.intent_parser.prompt_source.snapshot
        request=body(template).model_dump()
        assert client.post('/admin/prompt-debug',json=request).status_code==403
        assert client.post('/admin/prompt-debug',json=request,headers={'X-Admin-Token':'read'}).status_code==403
        assert client.post('/admin/prompt-debug',json=request,headers={'X-Admin-Token':'read','X-Admin-Annotation-Token':'write'}).status_code==403
        response=client.post('/admin/prompt-debug',json=request,headers={'X-Admin-Token':'read','X-Admin-Annotation-Token':'write','X-Admin-Snapshot-Token':'raw'})
        assert response.status_code==200,response.text
        assert len(bodies)==1
        assert not app.state.repository.list()


@pytest.mark.parametrize('node,attribute',[
    ('intent_parser','intent_parser'),('analysis_planner','analysis_planner'),('insight_generator','report_service')])
def test_all_three_nodes_use_their_own_actual_registered_template(tmp_path,node,attribute):
    llm,_,bodies,_=setup(tmp_path/'provider',[{'ok':True}])
    app=create_app(Settings(tmp_path/'app',admin_read_token='read',admin_snapshot_token='raw',admin_annotation_token='write'),provider=llm)
    with TestClient(app) as client:
        template=getattr(app.state,attribute).prompt_source.snapshot
        request=body(template).model_copy(update={'node_id':node}).model_dump()
        response=client.post('/admin/prompt-debug',json=request,headers={'X-Admin-Token':'read','X-Admin-Annotation-Token':'write','X-Admin-Snapshot-Token':'raw'})
        assert response.status_code==200,response.text
        assert bodies[0]['messages'][0]['content']==template.system_template
        record=response.json()['results'][0]['calls'][0]
        assert record['node_id']==node and record['template_snapshot_id']==template.template_snapshot_id
