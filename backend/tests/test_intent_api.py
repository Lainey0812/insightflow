from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from intent_fixtures import StubProvider, intent_payload


def dataset(client):
    response = client.post("/api/v1/datasets", files={"file": ("jobs.csv", "城市,薪资\n上海,20-30K".encode())})
    assert response.status_code == 201
    profile = response.json()
    return {"dataset_id": profile["dataset_id"], "dataset_version": profile["dataset_version"]}


def test_direct_api_resolves_context_from_saved_version_and_preserves_query(client, provider):
    ref = dataset(client)
    query = "  分析各城市岗位数量\n"
    response = client.post("/api/v1/intents/parse", json={"user_query": query, "dataset_ref": ref})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user_query"] == query and data["dataset_ref"] == ref
    assert data["analysis_mode"] == "goal_driven" and data["next_action"] == "proceed"
    assert data["llm"]["is_mock"] is True
    assert len(provider.requests) == 1
    assert client.get("/api/v1/sessions").json() == []
    rejected = client.post("/api/v1/intents/parse", json={"user_query": query, "dataset_context": {"columns": []}})
    assert rejected.status_code == 422
    assert len(provider.requests) == 1


def test_missing_context_empty_query_and_unknown_version(client, provider):
    missing = client.post("/api/v1/intents/parse", json={"user_query": "分析招聘数据"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "DATASET_CONTEXT_REQUIRED"
    ref = dataset(client)
    empty = client.post("/api/v1/intents/parse", json={"user_query": "", "dataset_ref": ref})
    assert empty.status_code == 200 and empty.json()["next_action"] == "clarify"
    assert empty.json()["parse_origin"] == "input_guard"
    assert not provider.requests
    ref["dataset_version"] = "a" * 64
    assert client.post("/api/v1/intents/parse", json={"user_query": "分析数据", "dataset_ref": ref}).status_code == 404


def test_invalid_output_and_provider_error_propagate_as_errors(client, provider):
    ref = dataset(client)
    provider.payload = {"analysis_mode": "invented"}
    response = client.post("/api/v1/intents/parse", json={"user_query": "分析数据", "dataset_ref": ref})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "INTENT_SCHEMA_INVALID"
    provider.error = RuntimeError("secret-provider-error")
    response = client.post("/api/v1/intents/parse", json={"user_query": "分析数据", "dataset_ref": ref})
    assert response.status_code == 502 and "secret" not in response.text


def test_unconfigured_real_application_reports_explicit_error(tmp_path):
    with TestClient(create_app(Settings(tmp_path))) as client:
        ref = dataset(client)
        response = client.post("/api/v1/intents/parse", json={"user_query": "分析数据", "dataset_ref": ref})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


def test_clarification_pauses_and_resumes_without_reprofiling_and_persists_history(tmp_path):
    settings = Settings(tmp_path)
    provider = StubProvider(intent_payload("goal_driven", "clarify", "比较指定城市薪资", "招聘岗位"))
    with TestClient(create_app(settings, provider=provider)) as client:
        query = "  比较指定城市的薪资  "
        response = client.post("/api/v1/sessions", data={"goal": query}, files={"file": ("jobs.csv", "城市,薪资\n上海,20-30K".encode())})
        assert response.status_code == 201, response.text
        state = response.json()
        assert state["status"] == "WAITING_FOR_CLARIFICATION" and not state["plans"]
        assert state["user_goal"] == query and state["intent"]["user_query"] == query
        assert "analysis_planner" not in [r["node_name"] for r in state["node_runs"]]
        sid, revision = state["id"], state["revision"]
        stale = client.post(f"/api/v1/sessions/{sid}/clarifications", json={"answer": "上海", "expected_revision": revision - 1})
        assert stale.status_code == 409 and len(provider.requests) == 1
    provider.payload = intent_payload("goal_driven", "proceed", "比较城市薪资", "招聘岗位")
    provider.payload["constraints"]["filters"] = [{"raw_text": "上海、北京", "validation_status": "unverified"}]
    with TestClient(create_app(settings, provider=provider)) as restarted:
        restored = restarted.get(f"/api/v1/sessions/{sid}").json()
        assert restored["status"] == "WAITING_FOR_CLARIFICATION"
        next_response = restarted.post(f"/api/v1/sessions/{sid}/clarifications", json={"answer": "上海、北京", "expected_revision": revision})
        assert next_response.status_code == 200, next_response.text
        current = next_response.json()
        assert current["status"] == "AWAITING_APPROVAL"
        assert current["user_goal"] == query
        assert current["clarification_answers"] == ["上海、北京"]
        assert len(current["intent_history"]) == 2
        assert current["intent_history"][0]["next_action"] == "clarify"
        assert current["intent_history"][1]["next_action"] == "proceed"
        assert sum(r["node_name"] == "data_profiler" for r in current["node_runs"]) == 1
        assert len(provider.requests) == 2
        assert restarted.post(f"/api/v1/sessions/{sid}/clarifications", json={"answer": "上海", "expected_revision": current["revision"]}).status_code == 409


def test_llm_failure_stops_workflow_and_keeps_actual_profile(client, provider):
    provider.error = RuntimeError("secret")
    response = client.post("/api/v1/sessions", data={"goal": "分析岗位数量"}, files={"file": ("jobs.csv", b"city\nShanghai")})
    state = response.json()
    assert state["status"] == "FAILED" and state["intent"] is None and not state["plans"]
    assert state["profile"]["provenance"]["source"] == "uploaded"
    assert state["error"]["code"] == "LLM_CALL_FAILED"
    assert "secret" not in response.text
