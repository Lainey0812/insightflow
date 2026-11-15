import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.domain.intent import ParsedIntent
from app.intent.focused_evaluation import score_case, summary
from app.intent.prompt import SYSTEM_PROMPT
from tests.intent_fixtures import intent_payload

ROOT = Path(__file__).parents[2]
SUITE = json.loads((ROOT / "backend/evaluation/intent_cases_reviewed_v12.json").read_text())
HOLDOUT = json.loads((ROOT / "backend/evaluation/intent_heldout_v12.json").read_text())


def case(case_id):
    return copy.deepcopy(next(c for c in SUITE["cases"] + HOLDOUT["cases"] if c["id"] == case_id))


def output(**constraints):
    payload = intent_payload()
    for category, texts in constraints.items():
        values = [{"raw_text": text, "validation_status": "unverified"} for text in texts]
        payload["constraints"][category] = values[0] if category == "time_range" else values
    return ParsedIntent.model_validate(payload)


def test_metric_in_goal_does_not_hide_missing_or_incomplete_constraint():
    result = output(metric_requirements=["数量"])
    result.analysis_goal.business_goal = "统计各类工单数量"
    scored = score_case(case("C06"), result)
    assert scored["matched_metric_units"] == scored["correct_predictions"] == 0
    assert not scored["metric_complete"] and not scored["passed"]


def test_ordering_clause_cannot_get_precision_credit_as_metric():
    good = output(metric_requirements=["实际工时合计"], analysis_limits=["排名", "前两名"],
                  time_range=["2026年"], filters=["项目A", "已完成"])
    assert score_case(case("P04"), good)["passed"]
    bad = output(metric_requirements=["按实际工时合计排名"], analysis_limits=["前两名"])
    scored = score_case(case("P04"), bad)
    assert not scored["prediction_checks"][0]["reference_aligned"]
    assert not scored["limit_complete"] and not scored["passed"]


@pytest.mark.parametrize("case_id,metrics,limits", [
    ("N01", ["薪资中位数", "薪资均值"], []),
    ("N02", ["销售额", "均值"], []),
    ("N07", ["点击次数"], ["不要求计算成交金额"]),
    ("N10", ["平均响应分钟", "响应分钟中位数"], []),
])
def test_polarity_failures_include_prohibition_nonrequest_and_unspecified(case_id, metrics, limits):
    scored = score_case(case(case_id), output(metric_requirements=metrics, analysis_limits=limits))
    assert scored["negation_error"] and not scored["passed"]


def test_negated_scope_does_not_become_filter():
    result = output(metric_requirements=["岗位数量"], filters=["上海"], analysis_limits=["不要只看上海"])
    assert score_case(case("N08"), result)["negation_error"]


def test_unknown_or_duplicate_predictions_reduce_precision_and_never_mutate_output():
    result = output(metric_requirements=["销售额", "销售额", "不存在的指标"])
    before = result.model_dump_json()
    scored = score_case(case("S06"), result)
    stats = summary([scored])
    assert stats["metrics"]["constraint_recall"] == 1
    assert stats["metrics"]["constraint_precision"] == pytest.approx(1/3)
    assert stats["metrics"]["complete_request_pass_rate"] == 0
    assert result.model_dump_json() == before


def test_empty_failed_call_does_not_claim_negation_verified():
    result = summary([score_case(case("N02"), error={"code": "LLM_TIMEOUT"})])
    assert result["negation_unassessed_count"] == 1
    assert result["metrics"]["constraint_precision"] is None
    assert not result["engineering_targets_met"] and not result["semantic_acceptance_passed"]


def test_same_category_combined_limits_are_not_artificially_split_for_scoring():
    c = case("O02")
    result = output(metric_requirements=["岗位数量"], analysis_limits=["降序排列，只展示前三个城市"])
    scored = score_case(c, result)
    assert scored["passed"] and scored["matched_constraints"] == 3
    assert scored["correct_predictions"] == 2


def test_optional_original_wording_is_not_treated_as_spurious_count_inference():
    result = output(metric_requirements=["岗位分布"], filters=["AI产品经理"])
    assert score_case(case("R08"), result)["passed"]


def test_frozen_inputs_have_grounded_units_and_holdout_is_not_in_prompt_or_regression():
    assert len(SUITE["cases"]) == 40 and len(HOLDOUT["cases"]) == 28
    original = json.loads((ROOT / "backend/evaluation/intent_cases.json").read_text())
    assert [c["query"] for c in original["cases"]] == [c["query"] for c in SUITE["cases"]]
    assert not {c["query"] for c in SUITE["cases"]} & {c["query"] for c in HOLDOUT["cases"]}
    for suite in (SUITE, HOLDOUT):
        assert suite["human_reviewed"] is False
        for c in suite["cases"]:
            assert all(u["text"] in c["query"] for u in c["focused_units"])
    # These are historical V1.2 holdouts; V1.3 may legitimately use known regressions.
    historical_prompt = (ROOT / "docs/evaluations/intent-v1.2/prompt.txt").read_text()
    assert all(c["query"] not in historical_prompt for c in HOLDOUT["cases"])
    archive = ROOT / "docs/evaluations/intent-v1.1"
    manifest = json.loads((archive/"manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((archive/name).read_bytes()).hexdigest() == digest


def test_live_script_selects_focused_metrics_without_an_additional_llm_node(tmp_path, monkeypatch):
    import asyncio
    from app.llm.base import LLMResponse
    from scripts import evaluate_intent as cli

    class TransportFixture:
        async def generate(self, request):
            # Protocol fixture, not evidence of actual model understanding.
            return LLMResponse(text=output(metric_requirements=["销售额"]).model_dump_json(),
                               provider="transport-fixture", model="fixture", is_mock=False)

    monkeypatch.setattr(cli, "create_provider", lambda settings: TransportFixture())
    suite = copy.deepcopy(SUITE)
    suite["cases"] = [case("S06")]
    input_path, result_path = tmp_path / "suite.json", tmp_path / "result.json"
    input_path.write_text(json.dumps(suite))
    # One positive case cannot establish blocker recall or overall acceptance.
    assert asyncio.run(cli.evaluate(input_path, result_path)) == 1
    record = json.loads(result_path.read_text())
    assert record["metrics"]["constraint_precision"] == 1
    assert record["summary"]["semantic_acceptance_passed"] is False
    assert record["acceptance_passed"] is False
    assert record["prompt_sha256"] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
