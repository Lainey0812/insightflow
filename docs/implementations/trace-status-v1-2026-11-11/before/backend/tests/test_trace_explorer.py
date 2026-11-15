"""Compatibility, database-side filtering and browser access tests; no mock UI data."""
from contextlib import closing
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.domain.tracing import TraceRun,TraceSpan,RunManifest
from test_report_workflow import Provider

TOKEN='isolated-test-credential-not-production'

def prepare(tmp_path):
    app=create_app(Settings(tmp_path,admin_read_token=TOKEN),Provider())
    # Repository-level filter fixtures, never inserted into a user's runtime DB.
    for index,(status,node,version) in enumerate([('complete','evidence_builder','vA'),('partial','fact_validator','vB'),('failed','fact_validator','vA')]):
        when=f'2026-10-{20+index}T08:00:00+00:00'
        repo=app.state.traces.repository
        repo.create(TraceRun(run_id=f'run_{index}',session_id='session',execution_id=f'exec_{index}',attempt=1,
            owner_instance='test',status=status,queued_at=when,manifest=RunManifest(versions={'prompt_version':version})))
        repo.save_span(TraceSpan(span_id=f'span_{index}',run_id=f'run_{index}',name=node,status='complete',started_at=when))
    return app


def test_database_filters_compose_with_count_and_pagination(tmp_path):
    app=prepare(tmp_path)
    with TestClient(app) as client:
        client.headers['X-Admin-Token']=TOKEN
        response=client.get('/admin/runs?node=fact_validator&version=vA&limit=1&offset=0')
        assert response.status_code==200
        assert response.json()['total']==1 and response.json()['items'][0]['run_id']=='run_2'
        assert client.get('/admin/runs?node=fact_validator&limit=1').json()['total']==2
        assert client.get('/admin/runs?node=fact_validator&limit=1&offset=1').json()['items'][0]['run_id']=='run_1'
        assert client.get('/admin/runs?status=partial').json()['items'][0]['status']=='partial'
        assert client.get('/admin/runs?version=not-present').json()['total']==0
        params={'from_time':'2026-10-21T16:00:00+08:00','to_time':'2026-10-22T08:00:00Z'}
        assert client.get('/admin/runs',params=params).json()['total']==2
        assert client.get('/admin/runs',params={'from_time':'2026-10-23T00:00:00Z'}).json()['total']==0
        assert response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('query',[{'from_time':'2026-10-20'}, {'from_time':'invalid'},
    {'from_time':'2026-10-23T00:00:00Z','to_time':'2026-10-21T00:00:00Z'}, {'node':'x'*129}])
def test_invalid_filters_are_not_silently_dropped(tmp_path,query):
    with TestClient(prepare(tmp_path)) as client:
        assert client.get('/admin/runs',params=query,headers={'X-Admin-Token':TOKEN}).status_code==422


def test_browser_exchange_refresh_compatibility_and_logout(tmp_path):
    with TestClient(prepare(tmp_path)) as client:
        assert client.get('/api/v1/admin/runs').status_code==403
        assert client.post('/api/v1/admin/access',headers={'X-Admin-Token':'wrong'}).status_code==403
        response=client.post('/api/v1/admin/access',headers={'X-Admin-Token':TOKEN})
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and TOKEN not in cookie
        assert TOKEN not in response.text and response.json()['access']=='read_only'
        assert client.get('/api/v1/admin/runs').status_code==200
        assert client.get('/admin/runs/run_1').json()['run']['status']=='partial'
        assert client.get('/admin/runs',headers={'X-Admin-Token':'wrong'}).status_code==403
        assert client.post('/admin/access').status_code==403  # cookie cannot renew access without credential
        assert client.delete('/admin/access').status_code==403
        assert client.delete('/api/v1/admin/access',headers={'X-Admin-Request':'1'}).status_code==204
        assert client.get('/api/v1/admin/runs').status_code==403
        assert client.get('/admin/runs',headers={'X-Admin-Token':TOKEN}).status_code==200


def test_tampered_expired_rotated_cookies_and_missing_server_configuration(tmp_path,monkeypatch):
    app=prepare(tmp_path)
    with TestClient(app) as client:
        response=client.post('/admin/access',headers={'X-Admin-Token':TOKEN})
        value=response.cookies.get('insightflow_admin_read')
        client.cookies.clear();client.cookies.set('insightflow_admin_read',value+'bad')
        assert client.get('/admin/runs').status_code==403
        client.cookies.clear();client.cookies.set('insightflow_admin_read',value)
        import time
        original=time.time
        monkeypatch.setattr('app.api.admin.time.time',lambda:original()+8*60*60+10)
        assert client.get('/admin/runs').status_code==403
        monkeypatch.undo()
    with TestClient(create_app(Settings(tmp_path,admin_read_token='rotated'),Provider())) as other:
        other.cookies.set('insightflow_admin_read',value)
        assert other.get('/admin/runs').status_code==403
    with TestClient(create_app(Settings(tmp_path),Provider())) as disabled:
        disabled.cookies.set('insightflow_admin_read',value)
        assert disabled.get('/admin/runs').status_code==503
        assert disabled.post('/admin/access',headers={'X-Admin-Token':TOKEN}).status_code==503


def test_secure_cookie_on_https(tmp_path):
    with TestClient(prepare(tmp_path),base_url='https://admin.example.test') as client:
        response=client.post('/admin/access',headers={'X-Admin-Token':TOKEN})
        from http.cookies import SimpleCookie
        cookie=SimpleCookie();cookie.load(response.headers['set-cookie'])
        assert cookie['insightflow_admin_read']['secure'] is True
        assert client.get('/admin/runs').status_code==200
