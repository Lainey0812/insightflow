import asyncio
import copy
import json

import pytest
from pydantic import ValidationError

from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.intent.context import build_dataset_context
from app.llm.compatible_provider import UnconfiguredLLMProvider
from app.services.intent_parser import IntentParserService
from intent_fixtures import StubProvider, intent_payload
from test_data_profiler import profile


@pytest.fixture
def recruitment_profile():
    return profile("城市,岗位名称,薪资,邮箱\n上海,产品经理,20-30K,private@example.test\n北京,AI产品经理,30-40K,secret@example.test".encode())


CASES = [
    ("分析各城市岗位数量", "goal_driven", "proceed"),
    ("探索招聘数据的主要规律", "exploratory", "proceed"),
    ("帮我分析一下这份数据", "exploratory", "proceed"),
    ("帮我处理一下", "undetermined", "clarify"),
    ("比较指定城市的薪资，但没有指定城市", "goal_driven", "clarify"),
    ("分析薪资情况，但没有指定均值或中位数", "goal_driven", "proceed"),
    ("分析招聘数据", "goal_driven", "proceed"),
]


@pytest.mark.parametrize("query,mode,action", CASES)
def test_seven_acceptance_contracts_with_scripted_provider(recruitment_profile, query, mode, action):
    # These fixtures verify output processing and the acceptance contract, not live model accuracy.
    payload = intent_payload(mode, action, query if mode != "undetermined" else None, "招聘岗位")
    provider = StubProvider(payload)
    result = asyncio.run(IntentParserService(provider).parse(query, recruitment_profile))
    assert result.analysis_mode == mode and result.next_action == action
    assert result.analysis_goal.decision_goal is None
    assert result.user_query == query
    assert result.llm.is_mock is True
    assert result.provenance.source == "mock"
    assert provider.requests[0].response_schema == ParsedIntent.model_json_schema()


def test_context_maps_real_profile_fields_without_samples_or_raw_rows(recruitment_profile):
    context = build_dataset_context(recruitment_profile)
    assert [c.field_id for c in context.columns] == [f.field_id for f in recruitment_profile.fields]
    assert [c.name for c in context.columns] == [f.display_name for f in recruitment_profile.fields]
    assert [c.logical_type for c in context.columns] == [f.logical_type for f in recruitment_profile.fields]
    assert context.dataset_name == recruitment_profile.file_name
    assert context.sample_rows == []
    provider = StubProvider()
    asyncio.run(IntentParserService(provider).parse("分析数据", recruitment_profile))
    sent = json.loads(provider.requests[0].instruction)
    assert set(sent["dataset_context"]) == {"dataset_name", "row_count", "columns", "sample_rows"}
    assert "private@example.test" not in provider.requests[0].instruction
    assert "secret@example.test" not in provider.requests[0].instruction
    assert "20-30K" not in provider.requests[0].instruction
    assert "samples" not in sent["dataset_context"]["columns"][0]


def test_duplicate_names_keep_distinct_field_ids():
    context = build_dataset_context(profile(b"a,a\n1,2"))
    assert [c.name for c in context.columns] == ["a", "a"]
    assert len({c.field_id for c in context.columns}) == 2


def test_empty_input_returns_explicit_guard_clarification_without_call(recruitment_profile):
    provider = StubProvider()
    result = asyncio.run(IntentParserService(provider).parse(" \n ", recruitment_profile))
    assert result.user_query == " \n "
    assert result.parse_origin == "input_guard" and result.llm is None
    assert result.analysis_mode == "undetermined" and result.next_action == "clarify"
    assert result.uncertainties[0].action == "clarify" and result.clarification_questions
    assert provider.requests == []


def test_missing_context_is_explicit_error_not_manual_columns_request():
    provider = StubProvider()
    with pytest.raises(AppError) as error:
        asyncio.run(IntentParserService(provider).parse("分析招聘数据", None))
    assert error.value.error.code == "DATASET_CONTEXT_REQUIRED"
    assert provider.requests == []


def test_context_size_is_bounded_before_provider_call():
    large = profile(("x" * 70000 + "\n1").encode())
    with pytest.raises(AppError) as error:
        build_dataset_context(large)
    assert error.value.error.code == "DATASET_CONTEXT_TOO_LARGE"


def test_raw_constraints_decision_and_original_query_are_preserved(recruitment_profile):
    query = "  分析今年上海岗位的薪资中位数，只看前20条，帮助我确定优先投递城市。  "
    payload = intent_payload()
    payload["analysis_goal"]["decision_goal"] = "确定优先投递城市"
    constraint = lambda text: {"raw_text": text, "validation_status": "unverified"}
    payload["constraints"] = {"time_range": constraint("今年"), "filters": [constraint("上海")],
        "metric_requirements": [constraint("薪资中位数")], "analysis_limits": [constraint("只看前20条")]}
    provider = StubProvider(payload)
    result = asyncio.run(IntentParserService(provider).parse(query, recruitment_profile))
    assert result.user_query == query
    assert result.constraints.time_range.raw_text == "今年"
    assert result.constraints.filters[0].validation_status == "unverified"
    assert result.analysis_goal.decision_goal == "确定优先投递城市"
    assert json.loads(provider.requests[0].instruction)["user_query"] == query


@pytest.mark.parametrize("invented", ["constraint", "decision"])
def test_ungrounded_output_is_rejected(recruitment_profile, invented):
    payload = intent_payload()
    if invented == "decision":
        payload["analysis_goal"]["decision_goal"] = "确定优先投递城市"
    else:
        payload["constraints"]["filters"] = [{"raw_text": "上海", "validation_status": "unverified"}]
    with pytest.raises(AppError) as error:
        asyncio.run(IntentParserService(StubProvider(payload)).parse("分析招聘数据", recruitment_profile))
    assert error.value.error.code == "LLM_UNGROUNDED_OUTPUT"


@pytest.mark.parametrize("change", [
    lambda p: p.update(analysis_mode="free_agent"),
    lambda p: p.pop("constraints"),
    lambda p: p["analysis_goal"].pop("decision_goal"),
    lambda p: p.update(next_action="execute"),
    lambda p: p.update(analysis_mode="undetermined"),
    lambda p: p.update(next_action="clarify"),
    lambda p: p.update(clarification_questions=["要什么图？"]),
    lambda p: p.update(tasks=[{"operation": "compute"}]),
    lambda p: p["constraints"].update(filters=[{"raw_text": "上海", "validation_status": "executable"}]),
    lambda p: p["analysis_goal"].update(business_goal="  "),
])
def test_invalid_output_fields_and_flow_are_errors(recruitment_profile, change):
    payload = intent_payload()
    change(payload)
    with pytest.raises(AppError) as error:
        asyncio.run(IntentParserService(StubProvider(payload)).parse("分析上海数据", recruitment_profile))
    assert error.value.error.code in {"INTENT_SCHEMA_INVALID", "INTENT_SEMANTIC_INVALID"}


@pytest.mark.parametrize("text", ["not json", "```json\n{}\n```", "[]", '{"x":1,"x":2}', '{"x":NaN}'])
def test_malformed_json_is_not_repaired_or_mocked(recruitment_profile, text):
    provider = StubProvider(text)
    with pytest.raises(AppError) as error:
        asyncio.run(IntentParserService(provider).parse("分析数据", recruitment_profile))
    assert error.value.error.code == ("INTENT_SCHEMA_INVALID" if text == "[]" else "LLM_INVALID_JSON")
    assert len(provider.requests) == 2


def test_uncertainties_and_action_rules(recruitment_profile):
    payload = intent_payload()
    payload["uncertainties"] = [{"id": "salary_basis", "description": "薪资口径待确认。",
        "impact": "执行前需要统一口径。", "action": "defer", "resolve_at": "plan_approval"}]
    result = asyncio.run(IntentParserService(StubProvider(payload)).parse("分析薪资", recruitment_profile))
    assert result.next_action == "proceed"
    invalid = copy.deepcopy(payload)
    invalid["uncertainties"][0]["action"] = "clarify"
    invalid["uncertainties"][0]["resolve_at"] = "before_planning"
    with pytest.raises(ValidationError):
        ParsedIntent.model_validate(invalid)
    invalid["next_action"] = "clarify"
    invalid["clarification_questions"] = ["请确认薪资口径？"]
    assert ParsedIntent.model_validate(invalid).next_action == "clarify"
    invalid["uncertainties"].append(copy.deepcopy(invalid["uncertainties"][0]))
    with pytest.raises(ValidationError):
        ParsedIntent.model_validate(invalid)


def test_clarification_can_supply_constraint_evidence(recruitment_profile):
    payload = intent_payload()
    payload["constraints"]["filters"] = [{"raw_text": "上海、北京", "validation_status": "unverified"}]
    result = asyncio.run(IntentParserService(StubProvider(payload)).parse("比较指定城市的薪资", recruitment_profile, ["上海、北京"]))
    assert result.clarification_answers == ["上海、北京"]


def test_provider_failure_and_missing_config_are_not_success(recruitment_profile):
    for provider, code in [(StubProvider(error=RuntimeError("secret-api-key")), "LLM_CALL_FAILED"),
                           (UnconfiguredLLMProvider(), "LLM_NOT_CONFIGURED")]:
        with pytest.raises(AppError) as error:
            asyncio.run(IntentParserService(provider).parse("分析数据", recruitment_profile))
        assert error.value.error.code == code
        assert "secret" not in error.value.error.message


def test_timeout_returns_explicit_failure_and_cancels_call(recruitment_profile):
    class SlowProvider:
        cancelled = False
        async def generate(self, request):
            try:
                await asyncio.sleep(10)
            finally:
                self.cancelled = True
    provider = SlowProvider()
    with pytest.raises(AppError) as error:
        asyncio.run(IntentParserService(provider, timeout_seconds=.01).parse("分析数据", recruitment_profile))
    assert error.value.error.code == "LLM_TIMEOUT" and provider.cancelled
