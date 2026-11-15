"""Controlled model response snapshots: synthetic HTTP transports only, never a real provider."""
import asyncio
from contextlib import closing
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.llm.capture import CallRecorder
from app.llm.compatible_provider import CompatibleLLMProvider
from app.main import create_app
from app.storage.prompt_registry import PromptRegistryRepository
from test_prompt_registry import calls
from intent_fixtures import intent_payload
from planning_fixtures import recruiting_profile

HEADERS = {'X-Admin-Token': 'read'}
RAW = {**HEADERS, 'X-Admin-Snapshot-Token': 'raw'}


def app_with(tmp_path, handler):
    repo = PromptRegistryRepository(tmp_path / 'transport')
    llm = CompatibleLLMProvider('https://local-test.invalid/v1', 'qwen3.8-flash', transport=httpx.MockTransport(handler),
                                capture=CallRecorder(repo))
    app = create_app(Settings(tmp_path / 'app', admin_read_token='read', admin_snapshot_token='raw'), provider=llm)
    return app, app.state.llm_captures.repository


def reply(content, finish='stop'):
    return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]})


def parse(app, query='比较城市岗位数量，PRIVATE_QUERY'):
    try:
        return asyncio.run(app.state.intent_parser.parse(query, recruiting_profile()))
    except AppError as error:
        return error


def test_successful_content_is_retained_and_separately_authorized(tmp_path):
    text = json.dumps(intent_payload(business_goal='比较城市岗位数量 PRIVATE_ANSWER'), ensure_ascii=False)
    app, repo = app_with(tmp_path, lambda request: reply(text))
    with TestClient(app) as client:
        parse(app)
        call = calls(repo)[0]
        summary = client.get(f'/admin/llm-calls/{call.call_id}/summary', headers=HEADERS)
        assert summary.json()['response_availability'] == 'retained' and summary.json()['response_kind'] == 'content'
        assert 'PRIVATE_ANSWER' not in summary.text
        path = f'/admin/llm-calls/{call.call_id}/response'
        assert client.get(path, headers=HEADERS).status_code == 403
        assert client.get(path).status_code == 403
        response = client.get(path, headers=RAW)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        data = response.json()
        assert data['kind'] == 'content' and data['content'] == text and data['truncated'] is False
        assert data['call_status'] == 'succeeded' and data['content_sha256'] == call.response_hash


def test_non_compliant_model_output_is_visible_even_though_business_parse_fails(tmp_path):
    app, repo = app_with(tmp_path, lambda request: reply('这不是 JSON PRIVATE_BAD'))
    with TestClient(app) as client:
        assert isinstance(parse(app), AppError)
        records = calls(repo)
        assert records and all(r.status == 'succeeded' for r in records)
        data = client.get(f'/admin/llm-calls/{records[0].call_id}/response', headers=RAW).json()
        assert data['kind'] == 'content' and 'PRIVATE_BAD' in data['content']


@pytest.mark.parametrize('response,code,needle', [
    (httpx.Response(500, json={'error': 'supplier detail PRIVATE_HTTP'}), 'LLM_HTTP_ERROR', 'PRIVATE_HTTP'),
    (reply('{"partial PRIVATE_CUT', finish='length'), 'LLM_INCOMPLETE_OUTPUT', 'PRIVATE_CUT'),
    (httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'refusal': 'PRIVATE_REFUSAL', 'content': None}}]}), 'LLM_REFUSED', 'PRIVATE_REFUSAL'),
])
def test_provider_failures_keep_raw_body(tmp_path, response, code, needle):
    app, repo = app_with(tmp_path, lambda request: response)
    with TestClient(app) as client:
        error = parse(app)
        assert isinstance(error, AppError) and needle not in json.dumps(error.error.model_dump(), ensure_ascii=False)
        call = calls(repo)[0]
        assert call.status == 'failed' and call.error_code == code and call.response_hash is None
        data = client.get(f'/admin/llm-calls/{call.call_id}/response', headers=RAW).json()
        assert data['kind'] == 'raw_body' and needle in data['content'] and data['error_code'] == code


def test_raw_body_is_capped(tmp_path):
    app, repo = app_with(tmp_path, lambda request: httpx.Response(500, text='x' * 200_000))
    with TestClient(app) as client:
        parse(app)
        data = client.get(f'/admin/llm-calls/{calls(repo)[0].call_id}/response', headers=RAW).json()
        assert data['truncated'] is True and len(data['content']) == 64 * 1024


def test_timeout_has_no_response_and_is_reported_unavailable(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout('slow', request=request)
    app, repo = app_with(tmp_path, handler)
    with TestClient(app) as client:
        parse(app)
        call = calls(repo)[0]
        assert call.error_code == 'LLM_TIMEOUT'
        assert client.get(f'/admin/llm-calls/{call.call_id}/summary', headers=HEADERS).json()['response_availability'] == 'unavailable'
        response = client.get(f'/admin/llm-calls/{call.call_id}/response', headers=RAW)
        assert response.status_code == 410 and response.json()['error']['code'] == 'LLM_RESPONSE_UNAVAILABLE'


def test_stored_response_is_immutable_and_tampering_is_detected(tmp_path):
    text = json.dumps(intent_payload(business_goal='比较城市岗位数量'), ensure_ascii=False)
    app, repo = app_with(tmp_path, lambda request: reply(text))
    with TestClient(app) as client:
        parse(app)
        call_id = calls(repo)[0].call_id
        with closing(repo.connect()) as conn, conn:
            with pytest.raises(Exception):
                conn.execute('UPDATE llm_response_payloads SET content=? WHERE call_id=?', ('forged', call_id))
        with closing(repo.connect()) as conn, conn:
            row = dict(conn.execute('SELECT * FROM llm_response_payloads WHERE call_id=?', (call_id,)).fetchone())
            conn.execute('DELETE FROM llm_response_payloads WHERE call_id=?', (call_id,))
            conn.execute('INSERT INTO llm_response_payloads VALUES (?,?,?,?,?,?)',
                         (call_id, row['kind'], 'forged', row['content_sha256'], row['truncated'], row['expires_at']))
        response = client.get(f'/admin/llm-calls/{call_id}/response', headers=RAW)
        assert response.status_code == 503 and response.json()['error']['code'] == 'LLM_RESPONSE_INTEGRITY_ERROR'


def test_existing_v1_registry_is_migrated_in_place(tmp_path):
    from pathlib import Path
    import sqlite3
    directory = tmp_path / 'registry'
    directory.mkdir()
    sql = Path(__file__).parents[1].joinpath('app/storage/migrations/prompt_registry_001.sql').read_text()
    with closing(sqlite3.connect(directory / 'registry.sqlite3')) as conn, conn:
        conn.executescript(sql)
    repo = PromptRegistryRepository(directory)
    with closing(repo.connect()) as conn:
        assert [r[0] for r in conn.execute('SELECT version FROM registry_migrations ORDER BY version')] == [1, 2]
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='llm_response_payloads'").fetchone()
