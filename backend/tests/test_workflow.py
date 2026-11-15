import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.api.errors import AppError
from app.core.config import Settings
from app.domain.enums import SessionStatus as S
from app.main import create_app
from app.services.plan_review import ApprovalRequest
from conftest import submit, version_body
from intent_fixtures import StubProvider


def test_mock_workflow_approval_and_report(client):
    state = submit(client)
    sid = state["id"]
    assert state["status"] == "AWAITING_APPROVAL"
    assert state["execution_result"] is None
    assert {run["node_name"] for run in state["node_runs"]} == {
        "intent_parser", "data_profiler", "analysis_planner"
    }
    assert client.get(f"/api/v1/sessions/{sid}/report").status_code == 409
    assert client.post(f"/api/v1/sessions/{sid}/execute", json=version_body(state)).status_code == 409
    approved = client.post(f"/api/v1/sessions/{sid}/approvals", json=version_body(state)).json()
    assert approved["status"] == "APPROVED"
    done_response = client.post(f"/api/v1/sessions/{sid}/execute", json=version_body(approved))
    assert done_response.status_code == 200, done_response.text
    done = done_response.json()
    assert done["status"] == "COMPLETED"
    execution = done["execution_result"]
    assert execution["provenance"]["source"] == "mock"
    assert execution["results"][0]["values"] == [263000.0]
    assert sum(execution["results"][1]["values"]) == execution["results"][0]["values"][0]
    report = client.get(f"/api/v1/sessions/{sid}/report").json()
    assert report["provenance"]["plan_version"] == 1
    assert report["sections"][1]["chart_option"]["series"][0]["data"] == execution["results"][1]["values"]
    preview = client.get(f"/api/v1/sessions/{sid}/report/preview")
    download = client.get(f"/api/v1/sessions/{sid}/report/download")
    assert preview.text == download.text
    assert "Mock 示例，非上传文件分析结果" in preview.text
    assert "<svg" in preview.text and "<table" in preview.text
    assert "attachment" in download.headers["content-disposition"]
    # Duplicate attempts never execute a second engine run.
    assert client.post(f"/api/v1/sessions/{sid}/execute", json=version_body(done)).status_code == 409


def test_hitl_persists_across_app_restart(tmp_path):
    settings = Settings(tmp_path)
    with TestClient(create_app(settings, provider=StubProvider())) as first:
        state = submit(first)
    with TestClient(create_app(settings)) as second:
        restored = second.get(f'/api/v1/sessions/{state["id"]}').json()
        assert restored == state
        assert second.get("/api/v1/sessions").json()[0]["id"] == state["id"]
        assert second.post(f'/api/v1/sessions/{state["id"]}/approvals', json=version_body(restored)).status_code == 200


def test_profile_context_precedes_intent_and_both_precede_planner(client, app, monkeypatch):
    events = []

    async def intent(payload):
        assert "profile_finished" in events
        assert payload.profile.row_count == 1
        events.append("intent_started")
        result = await original_intent(payload)
        events.append("intent_finished")
        return result

    async def profile(payload):
        events.append("profile_started")
        result = await original_profile(payload)
        events.append("profile_finished")
        return result

    original = app.state.workflow.planner.process
    original_profile = app.state.workflow.data_profiler.process
    original_intent = app.state.workflow.intent_parser.process
    async def planner(payload):
        assert "intent_finished" in events and "profile_finished" in events
        events.append("planner_started")
        return await original(payload)

    monkeypatch.setattr(app.state.workflow.intent_parser, "process", intent)
    monkeypatch.setattr(app.state.workflow.data_profiler, "process", profile)
    monkeypatch.setattr(app.state.workflow.planner, "process", planner)
    assert submit(client)["status"] == "AWAITING_APPROVAL"
    assert events[-1] == "planner_started"


def test_node_failure_stops_planning(client, app, monkeypatch):
    async def broken(_):
        raise ValueError("secret internal exception")
    monkeypatch.setattr(app.state.workflow.data_profiler, "process", broken)
    state = submit(client)
    assert state["status"] == "FAILED"
    assert state["error"]["node_name"] == "data_profiler"
    assert "secret" not in json.dumps(state)
    assert "analysis_planner" not in [run["node_name"] for run in state["node_runs"]]


@pytest.mark.parametrize("name,content,status,code", [
    ("test.exe", b"x", 422, "UNSUPPORTED_FILE"),
    ("test.csv", b"", 422, "EMPTY_FILE"),
    ("test.xlsx", b"x" * (10 * 1024 * 1024 + 1), 413, "FILE_TOO_LARGE"),
])
def test_upload_validation(client, app, name, content, status, code):
    response = client.post("/api/v1/sessions", data={"goal": "test"}, files={"file": (name, content)})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert not list((app.state.repository.database.path.parent / "uploads").iterdir())


def test_empty_goal_clarifies_without_inventing_intent_from_mode_hint(client, provider):
    response = client.post("/api/v1/sessions", data={"mode": "exploratory"}, files={"file": ("test.csv", b"x\n1")})
    assert response.status_code == 201
    assert response.json()["intent"]["analysis_mode"] == "undetermined"
    assert response.json()["status"] == "WAITING_FOR_CLARIFICATION"
    assert provider.requests == []


def test_concurrent_execution_claims_only_once(client, app):
    state = submit(client)
    state = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=version_body(state)).json()
    request = ApprovalRequest(**version_body(state))

    def run():
        try:
            return asyncio.run(app.state.workflow.execute(state["id"], request)).status
        except AppError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results.count(S.COMPLETED) == 1
    assert results.count("conflict") == 1
    assert len([r for r in app.state.repository.get(state["id"]).node_runs if r.node_name == "analysis_engine"]) == 1
