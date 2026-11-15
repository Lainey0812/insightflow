import asyncio
import copy
import json

import pytest

from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.llm.factory import create_provider
from app.llm.compatible_provider import CompatibleLLMProvider, UnconfiguredLLMProvider
from app.planning.capabilities import CapabilityRegistry
from app.services.analysis_planner import AnalysisPlannerService
from intent_fixtures import intent_payload
from planning_fixtures import PlannerProvider, recruiting_profile, step, task


def intent(query="比较城市岗位数量"):
    return ParsedIntent.model_validate(intent_payload(business_goal=query))


def generate(provider=None, goal=None, profile=None, timeout=30):
    service = AnalysisPlannerService(provider or PlannerProvider(), CapabilityRegistry(), timeout)
    return asyncio.run(service.plan(goal or intent(), profile or recruiting_profile()))


def test_simple_question_single_task_and_controlled_priority_consistency():
    # Controlled output only: actual business-value consistency is evaluated separately with --live.
    provider = PlannerProvider()
    outputs = [generate(provider) for _ in range(3)]
    assert all(len(x.plan.tasks) == 1 and x.plan.tasks[0].priority == "P0" for x in outputs)
    assert len({json.dumps(x.plan.tasks[0].model_dump(), sort_keys=True) for x in outputs}) == 1
    assert outputs[0].llm.is_mock and outputs[0].provenance.source == "mock"
    assert outputs[0].coverage_status == "complete"
    assert len({x.plan.plan_id for x in outputs}) == 3
    assert all(x.approval_required for x in outputs)


def test_context_uses_real_profile_and_registry_no_samples_or_raw_rows():
    provider = PlannerProvider()
    profile = recruiting_profile()
    generate(provider, profile=profile)
    request = provider.requests[0]
    data = json.loads(request.instruction)
    assert request.purpose == "analysis_planner_v1" and request.response_schema
    assert data["profile"]["dataset_version"] == profile.dataset_version
    assert data["profile"]["fields"][2]["logical_type"] == "integer"
    assert data["capabilities"]["derive_functions"] == ["extract_year", "extract_month"]
    assert "20-30K" not in request.instruction and "Python" not in request.instruction
    assert "samples" not in data["profile"] and "rows" not in data["profile"]
    assert "删除" in request.system_prompt


def test_explicit_decision_is_separate_core_requirement_not_assumed_covered():
    goal = intent()
    goal.analysis_goal.decision_goal = "确定优先投递城市"
    output = generate(goal=goal)
    assert len(output.plan.core_requirements) == 2
    assert output.coverage_status == "partial"
    assert output.unmet_core_requirements[0].requirement_id == "C02"


def test_unsupported_p0_and_missing_field_pass_to_validator_not_silently_removed():
    for candidate, reason in [
        (task([step("derive", {"function": "extract_skills", "field": "field_0005", "alias": "skills"})]), "UNSUPPORTED_OPERATION"),
        (task([step(params={"dimensions": ["field_9999"], "metrics": [{"function": "count", "alias": "n"}]})]), "MISSING_FIELD"),
        (task([step("aggregate", {"metrics": [{"function": "avg", "field": "field_0002", "alias": "salary"}]})]), "TYPE_MISMATCH"),
    ]:
        provider = PlannerProvider({"tasks": [candidate]})
        output = generate(provider)
        assert len(provider.requests) == 1  # F0 is a legitimate retained validation result, no feasibility repair by LLM
        assert output.plan.tasks[0].model_dump() == candidate
        assert output.validation_results[0].reason_code == reason
        assert output.coverage_status == "blocked" and not output.executable_task_ids


@pytest.mark.parametrize("bad", ["not JSON", "```json\n{}\n```", "[]", '{"tasks":[],"tasks":[]}',
    {"tasks": [], "coverage_status": "complete"}, {"tasks": [], "unmet_core_requirements": []},
    {"tasks": [task([step("python", {"code": "x"})])]},
    {"tasks": [task([step("sort", {"field": "field_0001", "direction": "up"})])]},
])
def test_invalid_schema_retry_once_then_fail(bad):
    provider = PlannerProvider(bad)
    with pytest.raises(AppError) as exc:
        generate(provider)
    expected = "PLANNER_INVALID_JSON" if isinstance(bad, str) and bad != "[]" else "PLANNER_SCHEMA_INVALID"
    assert exc.value.error.code == expected and len(provider.requests) == 2


def test_retry_invalid_then_valid_and_retries_do_not_echo_untrusted_output():
    provider = PlannerProvider('malformed secret diagnostic', {"tasks": [task()]})
    assert generate(provider).coverage_status == "complete"
    assert len(provider.requests) == 2
    assert "secret diagnostic" not in provider.requests[1].instruction


def test_clarify_never_calls_planner():
    provider = PlannerProvider()
    with pytest.raises(AppError) as exc:
        generate(provider, ParsedIntent.model_validate(intent_payload("undetermined", "clarify")))
    assert exc.value.error.code == "INTENT_CLARIFICATION_REQUIRED" and not provider.requests


@pytest.mark.parametrize("code,status,calls", [("LLM_NOT_CONFIGURED", 503, 1), ("LLM_TIMEOUT", 504, 1),
    ("LLM_HTTP_ERROR", 502, 1), ("LLM_INVALID_OUTPUT", 502, 2), ("LLM_INCOMPLETE_OUTPUT", 502, 2)])
def test_model_failures_are_clear_not_mock_success(code, status, calls):
    provider = PlannerProvider(AppError(code, "模型服务失败", status))
    with pytest.raises(AppError) as exc:
        generate(provider)
    assert exc.value.error.code == code and len(provider.requests) == calls


def test_unconfigured_no_mock_and_unexpected_error_sanitized():
    for provider, code in [(UnconfiguredLLMProvider(), "LLM_NOT_CONFIGURED"),
        (PlannerProvider(RuntimeError("sensitive provider detail")), "PLANNER_LLM_CALL_FAILED")]:
        with pytest.raises(AppError) as exc:
            generate(provider)
        assert exc.value.error.code == code
        assert "sensitive" not in exc.value.error.message


def test_timeout_cancels_provider():
    class Slow:
        cancelled = False
        async def generate(self, request):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
    provider = Slow()
    with pytest.raises(AppError) as exc:
        generate(provider, timeout=.01)
    assert exc.value.error.code == "LLM_TIMEOUT" and provider.cancelled


def test_schema_is_strict_but_uses_real_parameter_schemas():
    schema = CapabilityRegistry().request_schema()
    branches = schema["$defs"]["AnalysisStep"]["anyOf"]
    assert {b["properties"]["operation"]["enum"][0] for b in branches} == set(CapabilityRegistry().operations)
    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values(): inspect(child)
        elif isinstance(node, list):
            for child in node: inspect(child)
    inspect(schema)


def test_v1_node_is_orchestrator_callable_and_preserves_errors():
    from app.nodes.planner_v1 import AnalysisPlannerNode, PlannerV1Input
    from app.domain.node_contracts import NodeInput
    for provider, status in [(PlannerProvider(), "success"), (UnconfiguredLLMProvider(), "error")]:
        node = AnalysisPlannerNode(AnalysisPlannerService(provider, CapabilityRegistry()))
        output = asyncio.run(node.run(NodeInput(session_id="s", payload=PlannerV1Input(intent=intent(), profile=recruiting_profile()))))
        assert output.status == status
        if status == "success":
            assert output.data.validation_results and output.provenance.source == "mock"
        else:
            assert output.error.code == "LLM_NOT_CONFIGURED" and output.error.node_name == "analysis_planner_v1"


def test_real_compatible_transport_schema_and_validator_integration():
    import httpx
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"tasks": [task()]})}}]})
    provider = CompatibleLLMProvider("https://llm.example/v1", "test-model", transport=httpx.MockTransport(handler))
    output = generate(provider)
    assert output.validation_results[0].feasibility == "F2"
    assert not output.llm.is_mock and output.provenance.source == "llm"
    assert captured[0]["response_format"]["json_schema"]["name"] == "analysis_planner_v1"
    assert captured[0]["response_format"]["json_schema"]["strict"]


def test_missing_core_data_without_inventing_field_id_retained():
    candidate = task([])
    candidate["missing_inputs"] = ["用于薪资比较的数值字段"]
    output = generate(PlannerProvider({"tasks": [candidate]}), goal=intent("比较城市薪资"))
    assert output.plan.tasks[0].steps == []
    assert output.validation_results[0].reason_code == "MISSING_FIELD"
    assert output.coverage_status == "blocked"


def test_generic_sales_profile_plan_and_deterministic_engine_kernel_results():
    from app.profiling.profiler import build_profile
    from test_planning_operations import run
    raw = b"region,revenue,order_date\neast,100,2026-01-01\nwest,50,2026-01-02\neast,200,2026-02-01\n"
    profile = build_profile(raw, ".csv", "sales", "sales.csv")
    steps = [step("group_aggregate", {"dimensions": ["field_0001"], "metrics": [{"function": "sum", "field": "field_0002", "alias": "revenue"}]}),
             step("sort", {"field": "revenue", "direction": "desc"}, "S02")]
    candidate = task(steps)
    candidate.update(title="地区销售额", business_question="各地区销售额差异？", priority_reason="删除后无法回答地区销售额比较。")
    output = generate(PlannerProvider({"tasks": [candidate]}), goal=intent("比较各地区销售额"), profile=profile)
    assert output.validation_results[0].feasibility == "F2"
    assert output.plan.dataset_version == profile.dataset_version
    assert run(steps, raw).to_dict("records") == [{"field_0001": "east", "revenue": 300}, {"field_0001": "west", "revenue": 50}]


def test_unresolved_intent_constraints_and_risks_are_retained_not_claimed_resolved():
    raw = intent_payload(business_goal="按城市分析岗位")
    raw["constraints"]["time_range"] = {"raw_text": "今年", "validation_status": "unverified"}
    raw["uncertainties"] = [{"id": "time_scope", "description": "时间范围需要确认。", "impact": "影响样本范围。",
                            "action": "defer", "resolve_at": "plan_approval"}]
    output = generate(goal=ParsedIntent.model_validate(raw))
    assert output.intent_snapshot.constraints.time_range.validation_status == "unverified"
    assert output.intent_snapshot.uncertainties[0].resolve_at == "plan_approval"
    assert output.approval_required
