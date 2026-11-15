"""Reproducible real-file verification; test-only approval in an isolated temporary database.

Run from backend: ../.venv/bin/python scripts/verify_engine.py
No approval HTTP endpoint or live-session mutation is used. No LLM is called.
"""
import io
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.analysis_plan import AnalysisPlan
from app.domain.dataset_profile import DatasetProfile, DatasetRef
from app.domain.execution import ApprovedExecutionSnapshot, ExecutionRequest
from app.domain.intent import ParsedIntent
from app.domain.models import SessionState, now
from app.main import create_app
from app.planning.validator import PlanValidator


class NoLLM:
    async def generate(self, request):
        raise AssertionError("This verification must never call an LLM")


def verify():
    root = Path(__file__).resolve().parents[2]
    source = root / "examples" / "sales.csv"
    content = source.read_bytes()
    with TemporaryDirectory(prefix="insightflow-engine-") as directory:
        app = create_app(Settings(Path(directory)), provider=NoLLM())
        with TestClient(app) as client:
            uploaded = client.post("/api/v1/datasets", files={"file": (source.name, content, "text/csv")})
            assert uploaded.status_code == 201, uploaded.text
            profile = DatasetProfile.model_validate(uploaded.json())
            intent = ParsedIntent.model_validate({
                "analysis_mode": "goal_driven", "next_action": "proceed",
                "analysis_goal": {"analysis_object": "销售记录", "business_goal": "比较高额销售记录的地区分布，并统计总销售额", "decision_goal": None},
                "constraints": {"time_range": None, "filters": [], "metric_requirements": [], "analysis_limits": []},
                "uncertainties": [], "clarification_questions": []})
            plan = AnalysisPlan.model_validate({
                "plan_id": "sales_verified_plan", "plan_version": 1,
                "dataset_id": profile.dataset_id, "dataset_version": profile.dataset_version,
                "core_requirements": [{"requirement_id": "C01", "description": "比较销售分布与总额"}],
                "tasks": [
                    {"task_id": "A01", "title": "高额记录地区排名", "business_question": "销售额不低于18000的记录中，哪个地区金额最高？",
                     "priority": "P0", "priority_reason": "删除后无法回答地区差异问题", "requirement_ids": ["C01"], "depends_on": [], "steps": [
                         {"step_id": "S01", "operation": "filter", "params": {"conditions": [{"field": "field_0004", "operator": "gte", "value": 18000}]}},
                         {"step_id": "S02", "operation": "group_aggregate", "params": {"dimensions": ["field_0003"], "metrics": [
                             {"function": "count", "alias": "record_count"}, {"function": "sum", "field": "field_0004", "alias": "sales_total"}]}},
                         {"step_id": "S03", "operation": "sort", "params": {"field": "sales_total", "direction": "desc"}},
                         {"step_id": "S04", "operation": "top_n", "params": {"field": "sales_total", "direction": "desc", "n": 1}}]},
                    {"task_id": "A02", "title": "整体销售额", "business_question": "全部记录销售额合计是多少？",
                     "priority": "P0", "priority_reason": "删除后无法给出整体销售总额", "requirement_ids": ["C01"], "depends_on": [], "steps": [
                         {"step_id": "S01", "operation": "aggregate", "params": {"metrics": [
                             {"function": "sum", "field": "field_0004", "alias": "sales_total"}, {"function": "count", "alias": "record_count"}]}}]}
                ]})
            validated = PlanValidator(app.state.capability_registry).validate(plan, profile)
            assert validated.fully_executable
            validated.intent_snapshot = intent
            # Explicitly allowed by the integration specification: construct approval only in test DB.
            snapshot = ApprovedExecutionSnapshot(approval_id="verification_only_approval", approved_at=now(), validated_plan=validated, intent=intent)
            session = SessionState(title="真实文件执行验证", file=app.state.datasets.file(profile.dataset_id),
                user_goal=intent.analysis_goal.business_goal, analysis_mode="goal_driven", status="APPROVED",
                dataset_ref=DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version), profile=profile,
                current_plan_version=1, approved_plan_version=1, engine_approval=snapshot)
            app.state.repository.create(session)
            request = ExecutionRequest(session_id=session.id, plan_id=plan.plan_id, plan_version=1, execution_request_id="sales_real_file_verification")
            response = client.post("/api/v1/executions", json=request.model_dump())
            assert response.status_code == 200, response.text
            execution = response.json()
            frame = pd.read_csv(io.BytesIO(content))
            expected = (frame.loc[frame["销售额"] >= 18000].groupby("地区", sort=False)
                .agg(record_count=("销售额", "size"), sales_total=("销售额", "sum"))
                .reset_index().sort_values("sales_total", ascending=False, kind="stable").head(1)
                .rename(columns={"地区": "field_0003"}).to_dict("records"))
            assert execution["tasks"][0]["result"]["rows"] == expected
            assert execution["tasks"][1]["result"]["rows"] == [{"sales_total": int(frame["销售额"].sum()), "record_count": len(frame)}]
            execution_id = execution["execution_id"]
            persisted = client.get(f"/api/v1/executions/{execution_id}")
            replay = client.post("/api/v1/executions", json=request.model_dump())
            assert persisted.json() == replay.json() == execution
            assert client.get(f"/api/v1/executions/{execution_id}?view=complete").json()["result_view"] == "complete"
        # Re-open the actual SQLite database, so this verifies disk persistence as well.
        reopened = create_app(Settings(Path(directory)), provider=NoLLM())
        with TestClient(reopened) as other:
            assert other.get(f"/api/v1/executions/{execution_id}").json() == execution
        outputs = {
            "engine-execution.example.json": execution,
            "engine-verification.json": {"source_file": "examples/sales.csv", "content_sha256": profile.content_sha256,
                "source_rows": profile.row_count, "source_columns": profile.column_count,
                "approval_origin": "server-owned test fixture in isolated temporary DB; not a real HITL approval",
                "request": request.model_dump(), "validated_plan": validated.model_dump(mode="json"),
                "pandas_baseline": {"A01": expected, "A02": [{"sales_total": int(frame["销售额"].sum()), "record_count": len(frame)}]},
                "checks": {"pandas_results_match": True, "persisted_read_matches": True, "idempotent_replay_matches": True,
                    "fresh_app_read_matches": True, "llm_calls": 0}}
        }
        for name, payload in outputs.items():
            (root / "docs" / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"execution_id": execution_id, "status": execution["execution_status"], "source_rows": profile.row_count,
            "task_rows": {t["task_id"]: t["result"]["rows"] for t in execution["tasks"]}, "checks": outputs["engine-verification.json"]["checks"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    verify()
