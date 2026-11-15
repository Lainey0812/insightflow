"""Real V0.1 storage and loaded templates; additional versions are explicit test fixtures."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.observability.provenance import digest
from app.storage.prompt_registry import template_content
from test_prompt_registry import provider, calls, report_output
from planning_fixtures import recruiting_profile
from report_fixtures import report_case

HEADERS={'X-Admin-Token':'read'}


@pytest.fixture
def registry_app(tmp_path):
    llm,_,_=provider(tmp_path/'transport')
    app=create_app(Settings(tmp_path/'app',admin_read_token='read',admin_snapshot_token='raw'),provider=llm)
    repo=app.state.llm_captures.repository
    templates={key:repo.register(service.prompt_source.snapshot) for key,service in [
        ('intent_parser',app.state.intent_parser),('analysis_planner',app.state.analysis_planner),('insight_generator',app.state.report_service)]}
    with TestClient(app) as client:yield app,repo,templates,client


def changed(repo,original,system='changed fixture text\n'):
    copy=original.model_copy(update={'version':original.version+'-fixture-v2','system_template':system,
        'created_at':(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),'change_summary':'Explicit synthetic second version for Diff tests only.'})
    sha=digest(template_content(copy))
    return repo.register(copy.model_copy(update={'content_hash':sha,'template_snapshot_id':'pt_'+sha}))


def test_three_actual_registered_nodes_and_current_is_not_guessed(registry_app):
    app,repo,templates,client=registry_app
    response=client.get('/admin/prompts',headers=HEADERS)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    data=response.json();assert len(data['items'])==3
    for row in data['items']:
        assert row['version_count']==1 and row['runtime_registration']=='registered'
        assert row['latest_registered']['template_snapshot_id']==templates[row['node_id']].template_snapshot_id
    filtered=client.get('/admin/prompts?node=analysis_planner',headers=HEADERS).json()
    assert len(filtered['items'])==1


def test_actual_history_detail_pagination_and_preserved_old_content(registry_app):
    app,repo,templates,client=registry_app
    old=templates['intent_parser'];new=changed(repo,old)
    history=client.get('/admin/prompts/intent_parser/versions?limit=1',headers=HEADERS).json()
    assert history['total']==2 and len(history['items'])==1
    assert history['items'][0]['template_snapshot_id']==new.template_snapshot_id
    assert history['runtime_snapshot_id']==old.template_snapshot_id  # newest is not the active pin
    page2=client.get('/admin/prompts/intent_parser/versions?limit=1&offset=1',headers=HEADERS).json()
    assert page2['items'][0]['template_snapshot_id']==old.template_snapshot_id
    detail=client.get('/admin/prompts/intent_parser/versions/'+old.template_snapshot_id,headers=HEADERS).json()
    assert detail['template']['system_template']==old.system_template
    assert detail['template']['source_commit']==old.source_commit
    assert detail['variables_schema_availability']=='unavailable'
    assert repo.template(old.template_snapshot_id)==old


def test_empty_registry_and_unconfigured_runtime_have_honest_states(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token='read'))
    with TestClient(app) as client:
        rows=client.get('/admin/prompts',headers=HEADERS).json()['items']
        assert all(r['version_count']==0 and r['latest_registered'] is None and r['runtime_registration']=='unknown' for r in rows)
        assert client.get('/admin/prompts/intent_parser/versions',headers=HEADERS).json()['items']==[]
        assert client.get('/admin/prompts/unknown/versions',headers=HEADERS).status_code==404


def test_diff_line_reconstruction_matches_both_saved_texts(registry_app):
    _,repo,templates,client=registry_app
    old=templates['intent_parser'];new=changed(repo,old,'first\nchanged\nlast without newline')
    response=client.get('/admin/prompts/compare',params={'left':old.template_snapshot_id,'right':new.template_snapshot_id},headers=HEADERS)
    assert response.status_code==200
    data=response.json();system=next(s for s in data['sections'] if s['key']=='system')
    assert system['changed'] and not data['content_hash_equal']
    assert ''.join(line['left'] or '' for line in system['lines'])==old.system_template
    assert ''.join(line['right'] or '' for line in system['lines'])==new.system_template
    user=next(s for s in data['sections'] if s['key']=='user');assert user['changed'] is False


def test_cross_node_same_id_and_unknown_diff_rejected(registry_app):
    _,_,templates,client=registry_app
    left=templates['intent_parser'].template_snapshot_id;right=templates['analysis_planner'].template_snapshot_id
    assert client.get('/admin/prompts/compare',params={'left':left,'right':right},headers=HEADERS).status_code==422
    assert client.get('/admin/prompts/compare',params={'left':left,'right':left},headers=HEADERS).status_code==422
    assert client.get('/admin/prompts/compare',params={'left':left,'right':'missing'},headers=HEADERS).status_code==404
    assert client.get('/admin/prompts/insight_generator/versions/'+left,headers=HEADERS).status_code==404


def test_dynamic_requests_do_not_create_template_versions_and_calls_paginate(registry_app):
    app,repo,templates,client=registry_app
    for i in range(3):asyncio.run(app.state.intent_parser.parse('比较城市岗位数量，PRIVATE-'+str(i),recruiting_profile()))
    assert client.get('/admin/prompts/intent_parser/versions',headers=HEADERS).json()['total']==1
    identity=templates['intent_parser'].template_snapshot_id
    page=client.get(f'/admin/prompts/intent_parser/versions/{identity}/calls?limit=1&offset=1',headers=HEADERS).json()
    assert page['total']==3 and len(page['items'])==1
    item=page['items'][0]
    assert item['model']=='qwen3.8-flash' and not item['trace_available'] and item['call']['run_id'] is None
    assert 'PRIVATE' not in json.dumps(page)


def test_default_summary_never_reads_raw_and_raw_stays_separately_authorized(registry_app,monkeypatch):
    app,repo,_,client=registry_app
    asyncio.run(app.state.intent_parser.parse('比较城市岗位数量，PRIVATE_QUERY',recruiting_profile()))
    record=calls(repo)[0];original=repo.payload
    def forbidden(*args):raise AssertionError('metadata must not read raw request')
    monkeypatch.setattr(repo,'payload',forbidden)
    summary=client.get('/admin/llm-calls/'+record.call_id+'/summary',headers=HEADERS)
    assert summary.status_code==200 and 'PRIVATE_QUERY' not in summary.text
    assert summary.json()['redaction']['messages']=='hidden'
    monkeypatch.setattr(repo,'payload',original)
    path='/admin/llm-calls/'+record.call_id+'/request'
    assert client.get(path,headers=HEADERS).status_code==403
    raw=client.get(path,headers={**HEADERS,'X-Admin-Snapshot-Token':'raw'})
    assert raw.status_code==200 and 'PRIVATE_QUERY' in raw.text


@pytest.mark.parametrize('path',['/admin/prompts','/admin/prompts/intent_parser/versions','/admin/prompts/compare?left=x&right=y','/admin/llm-calls/x/summary'])
def test_read_endpoints_require_backend_authorization(registry_app,path):
    client=registry_app[3]
    assert client.get(path).status_code==403


def test_run_reference_is_only_linked_when_run_and_span_exist(tmp_path):
    from test_prompt_registry import trace_fixture
    from app.services.prompt_registry_query import PromptRegistryQuery
    from app.services.analysis_report import AnalysisReportService
    from app.planning.capabilities import CapabilityRegistry
    llm,repo,_=provider(tmp_path,[report_output]);traces,context=trace_fixture(tmp_path)
    asyncio.run(AnalysisReportService(llm,CapabilityRegistry()).generate(*report_case(),trace=context))
    record=calls(repo)[0]
    query=PromptRegistryQuery(repo,traces=traces.repository)
    assert query.call_summary(record.call_id)['trace_available']
    page=query.calls('insight_generator',record.template_snapshot_id)
    assert page['items'][0]['trace_available']
    assert not PromptRegistryQuery(repo).call_summary(record.call_id)['trace_available']


def test_new_read_pages_do_not_change_existing_loaded_template_content(registry_app):
    app,_,templates,client=registry_app
    for node,service in [('intent_parser',app.state.intent_parser),('analysis_planner',app.state.analysis_planner),('insight_generator',app.state.report_service)]:
        client.get('/admin/prompts',headers=HEADERS)
        assert service.prompt_source.build().content_hash==templates[node].content_hash
        paths=templates[node].source_files
        assert 'app/api/admin.py' not in paths and 'app/services/prompt_registry_query.py' not in paths


def test_historical_missing_content_does_not_fallback_to_current(registry_app):
    _,_,_,client=registry_app
    assert client.get('/admin/prompts/intent_parser/versions/not-preserved',headers=HEADERS).status_code==404
    assert client.get('/admin/llm-calls/not-preserved/summary',headers=HEADERS).status_code==404
