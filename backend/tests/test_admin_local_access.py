"""Local test access is explicit, loopback-only, and does not replace default auth."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import create_admin_router
from app.api.errors import install_error_handlers
from app.core.config import Settings
from app.main import create_app


def test_local_testing_reads_real_registry_without_credentials(tmp_path):
    app = create_app(Settings(tmp_path, admin_local_test_mode=True))
    with TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 45000)) as client:
        response = client.get('/api/v1/admin/prompts', headers={'Origin': 'http://127.0.0.1:5174'})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-insightflow-admin-access'] == 'local_test'
        assert len(response.json()['items']) == 3
        assert all(row['version_count'] == 0 for row in response.json()['items'])
        assert client.get('/api/v1/admin/runs').status_code == 200
        assert client.get('/api/v1/admin/prompts/intent_parser/versions').json()['items'] == []
        access = client.post('/api/v1/admin/access')
        assert access.json() == {'access': 'local_test', 'expires_in_seconds': 0}
        assert 'set-cookie' not in access.headers
        client.cookies.clear()
        assert client.get('/api/v1/admin/prompts').status_code == 200


@pytest.mark.parametrize('base_url,peer,headers', [
    ('http://127.0.0.1', '192.0.2.5', {}),
    ('http://admin.example', '127.0.0.1', {}),
    ('http://127.0.0.1', '127.0.0.1', {'Origin': 'https://evil.example'}),
    ('http://127.0.0.1', '127.0.0.1', {'Origin': 'null'}),
    ('http://127.0.0.1', '127.0.0.1', {'Origin': 'http://localhost.evil.example'}),
    ('http://127.0.0.1', '127.0.0.1', {'Origin': 'http://user:pass@localhost'}),
    ('http://127.0.0.1', '127.0.0.1', {'Sec-Fetch-Site': 'cross-site'}),
    ('http://127.0.0.1', '192.0.2.5', {'X-Forwarded-For': '127.0.0.1'}),
])
def test_local_mode_rejects_remote_and_cross_site_reads(tmp_path, base_url, peer, headers):
    app = create_app(Settings(tmp_path, admin_local_test_mode=True, admin_read_token='read'))
    with TestClient(app, base_url=base_url, client=(peer, 45000)) as client:
        for path in ['/api/v1/admin/prompts', '/admin/llm-calls/missing/request']:
            response = client.get(path, headers={**headers, 'X-Admin-Token': 'read'})
            assert response.status_code == 403
            assert response.json()['error']['code'] == 'ADMIN_LOCAL_ONLY'
        assert client.post('/admin/access', headers=headers).status_code == 403


@pytest.mark.parametrize('host,peer', [('localhost','127.0.0.1'), ('[::1]','::1')])
def test_localhost_and_ipv6_loopback_supported(tmp_path, host, peer):
    app = create_app(Settings(tmp_path, admin_local_test_mode=True))
    with TestClient(app, base_url='http://' + host, client=(peer, 45000)) as client:
        assert client.get('/admin/prompts', headers={'Origin': 'http://' + host + ':5174'}).status_code == 200


def test_raw_request_is_local_only_and_default_auth_restores():
    registry = SimpleNamespace(
        call=lambda _: SimpleNamespace(request_snapshot_id='request_1'),
        payload=lambda _: {'messages': [{'role': 'user', 'content': 'Synthetic test fixture'}]},
    )
    def make(local):
        app = FastAPI()
        app.include_router(create_admin_router(None, None, 'read', SimpleNamespace(repository=registry), local_test_mode=local))
        install_error_handlers(app)
        return app
    with TestClient(make(True), base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        assert client.get('/admin/llm-calls/call_1/request').json()['payload']['messages'][0]['content'] == 'Synthetic test fixture'
    with TestClient(make(False), base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        assert client.get('/admin/llm-calls/call_1/request').status_code == 403
        assert client.get('/admin/llm-calls/call_1/request', headers={'X-Admin-Token': 'read'}).status_code == 403


def test_local_mode_opt_in_config_and_existing_default(tmp_path, monkeypatch):
    monkeypatch.delenv('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE', raising=False)
    assert Settings.from_env().admin_local_test_mode is False
    monkeypatch.setenv('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE', 'true')
    assert Settings.from_env().admin_local_test_mode is True
    monkeypatch.setenv('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE', 'false')
    assert Settings.from_env().admin_local_test_mode is False
    monkeypatch.setenv('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE', 'typo')
    with pytest.raises(ValueError): Settings.from_env()
    with TestClient(create_app(Settings(tmp_path)), base_url='http://127.0.0.1', client=('127.0.0.1', 45000)) as client:
        assert client.get('/admin/prompts').status_code == 503
