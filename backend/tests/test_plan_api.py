import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from intent_fixtures import intent_payload
from planning_fixtures import CSV, PlannerProvider, plan, step, task


def upload(client):
    response = client.post("/api/v1/datasets", files={"file": ("jobs.csv", CSV, "text/csv")})
    assert response.status_code == 201
    profile = response.json()
    return {key: profile[key] for key in ["dataset_id", "dataset_version"]}, profile


def test_generate_and_validate_api_from_saved_dataset(tmp_path):
    provider = PlannerProvider()
    with TestClient(create_app(Settings(tmp_path), provider)) as client:
        ref, profile = upload(client)
        response = client.post("/api/v1/plans/generate", json={"intent": intent_payload(), "dataset_ref": ref})
        assert response.status_code == 200, response.text
        output = response.json()
        assert output["plan"]["dataset_version"] == ref["dataset_version"]
        assert output["validation_results"][0]["feasibility"] == "F2"
        assert output["approval_required"] and output["llm"]["is_mock"]
        response = client.post("/api/v1/plans/validate", json={"dataset_ref": ref, "plan": output["plan"]})
        assert response.status_code == 200 and response.json()["executable_task_ids"] == ["A01"]
        assert len(provider.requests) == 1  # validator never calls a model
        caps = client.get("/api/v1/capabilities").json()
        assert len(caps["operations"]) == 6
        assert all(v["supported"] and v["params_schema"] and v["output_rules"] for v in caps["operations"].values())
        assert "/api/v1/plans/generate" in client.get("/openapi.json").json()["paths"]


def test_automatic_intent_artifact_dataset_reference_full_flow(tmp_path):
    provider = PlannerProvider(intent_payload(business_goal="各城市岗位数量"), {"tasks": [task()]})
    with TestClient(create_app(Settings(tmp_path), provider)) as client:
        ref, _ = upload(client)
        parsed = client.post("/api/v1/intents/parse", json={"dataset_ref": ref, "user_query": "分析各城市岗位数量"})
        assert parsed.status_code == 200
        response = client.post("/api/v1/plans/generate", json={"intent": parsed.json()})
        assert response.status_code == 200 and response.json()["coverage_status"] == "complete"
        assert [r.purpose for r in provider.requests] == ["intent_v1", "analysis_planner_v1"]
        # Standalone plans cannot accidentally enter the legacy session execution API.
        assert client.get("/api/v1/sessions").json() == []


def test_invalid_plan_kept_but_not_executable(tmp_path):
    provider = PlannerProvider({"tasks": [task([step("aggregate", {"metrics": [{"function": "avg", "field": "field_0002", "alias": "s"}]})])]})
    with TestClient(create_app(Settings(tmp_path), provider)) as client:
        ref, _ = upload(client)
        output = client.post("/api/v1/plans/generate", json={"intent": intent_payload(), "dataset_ref": ref}).json()
        assert output["plan"]["tasks"][0]["priority"] == "P0"
        assert output["coverage_status"] == "blocked" and output["blocked_task_ids"] == ["A01"]
        assert output["unmet_core_requirements"][0]["task_ids"] == ["A01"]


def test_context_guards_schema_and_clear_model_failure(tmp_path):
    with TestClient(create_app(Settings(tmp_path))) as client:
        ref, _ = upload(client)
        assert client.post("/api/v1/plans/generate", json={"intent": intent_payload()}).status_code == 422
        assert client.post("/api/v1/plans/generate", json={"intent": intent_payload("undetermined", "clarify"), "dataset_ref": ref}).status_code == 409
        response = client.post("/api/v1/plans/generate", json={"intent": intent_payload(), "dataset_ref": ref})
        assert response.status_code == 503 and response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
        response = client.post("/api/v1/plans/validate", json={"dataset_ref": ref, "plan": {"tasks": []}})
        assert response.status_code == 422 and response.json()["error"]["code"] == "PLAN_SCHEMA_INVALID"
        unknown = {**ref, "dataset_version": "0" * 64}
        assert client.post("/api/v1/plans/generate", json={"intent": intent_payload(), "dataset_ref": unknown}).status_code == 404


def test_artifact_version_conflict_and_forged_status_rejected(tmp_path):
    provider = PlannerProvider(intent_payload())
    with TestClient(create_app(Settings(tmp_path), provider)) as client:
        ref, _ = upload(client)
        artifact = client.post("/api/v1/intents/parse", json={"user_query": "分析城市岗位", "dataset_ref": ref}).json()
        other, _ = upload(client)
        response = client.post("/api/v1/plans/generate", json={"intent": artifact, "dataset_ref": other})
        assert response.status_code == 409 and response.json()["error"]["code"] == "INTENT_DATASET_MISMATCH"
        bad = {"intent": artifact, "coverage_status": "complete"}
        assert client.post("/api/v1/plans/generate", json=bad).status_code == 422
        assert len(provider.requests) == 1
