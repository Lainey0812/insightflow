import copy

import pytest
from pydantic import ValidationError

from app.domain.execution import ExecutionResultV1
from app.domain.errors import AppError
from app.planning.capabilities import CapabilityRegistry
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.reporting.visualization import VisualizationBuilder
from planning_fixtures import step, task
from report_fixtures import report_case


def build(case):
    intent, validated, execution, profile = case
    checked, descriptions = prepare(intent, validated, execution, profile, CapabilityRegistry())
    evidence = EvidenceBuilder().build(execution, profile, descriptions)
    charts = VisualizationBuilder().build(execution, descriptions, evidence,
        {t.task_id:t for t in validated.plan.tasks}, intent)
    return evidence, charts


def test_real_evidence_ranking_extremes_shares_differences_and_trace():
    case = report_case()
    evidence, charts = build(case)
    types = {e.evidence_type for e in evidence}
    assert {"ranking", "maximum", "minimum", "difference", "proportion", "coverage"} <= types
    rank = next(e for e in evidence if e.evidence_type == "ranking")
    assert rank.value == {"category":"上海", "value":2, "rank":1}
    share = next(e for e in evidence if e.evidence_type == "proportion")
    assert share.value["denominator"] == 3 and share.value["percent"] == pytest.approx(200/3)
    for item in evidence:
        assert item.task_id == "A01" and item.scope and item.calculation
        if not item.result_field.startswith("$execution"):
            for index in item.source_row_indices:
                assert item.result_field in case[2].tasks[0].result.rows[index]
    assert charts[0].chart_type == "bar" and "pie" in charts[0].supported_chart_types
    assert "wordcloud" not in charts[0].supported_chart_types


def test_top_n_never_infers_overall_share_without_total():
    case = report_case([task([step(), step("top_n", {"field":"job_count","direction":"desc","n":1}, "S02")])])
    evidence, charts = build(case)
    assert not any(e.evidence_type == "proportion" for e in evidence)
    assert "pie" not in charts[0].supported_chart_types
    case[2].tasks[0].result.truncated = True
    case[2].tasks[0].result.total_result_rows = 2
    evidence, _ = build(case)
    assert not any(e.evidence_type == "proportion" for e in evidence)
    assert all("当前返回结果" in e.statement for e in evidence if e.evidence_type == "ranking")


def test_verified_scalar_denominator_and_scope_mismatch():
    grouped = task([step(), step("top_n", {"field":"job_count","direction":"desc","n":1}, "S02")])
    total = task([step("aggregate", {"metrics":[{"function":"count","alias":"total_count"}]})], tid="A02", priority="P1")
    case = report_case([grouped, total])
    from app.domain.execution import TotalReference
    case[2].tasks[0].result.total_refs = [TotalReference(metric_field="job_count", result_id="R002", result_field="total_count")]
    evidence, _ = build(case)
    share = next(e for e in evidence if e.evidence_type == "proportion")
    assert share.value["percent"] == pytest.approx(200/3) and share.related_result_refs == ["R002"]
    case[2].tasks[0].result.total_refs[0].result_field = "missing"
    with pytest.raises(AppError) as exc: build(case)
    assert exc.value.error.code == "REPORT_DENOMINATOR_INVALID"


def test_average_and_distinct_counts_are_not_summed_into_shares():
    for function in ["avg", "median", "distinct_count"]:
        case = report_case([task([step("group_aggregate", {"dimensions":["field_0001"],"metrics":[{"function":function,"field":"field_0003","alias":"salary"}]})])])
        evidence, charts = build(case)
        assert not any(e.evidence_type == "proportion" for e in evidence)
        assert "pie" not in charts[0].supported_chart_types


def test_time_trend_and_numeric_month_order():
    steps = [step("derive", {"function":"extract_month","field":"field_0004","alias":"month"}),
        step("group_aggregate", {"dimensions":["month"],"metrics":[{"function":"count","alias":"job_count"}]}, "S02")]
    evidence, charts = build(report_case([task(steps)]))
    change = next(e for e in evidence if e.evidence_type == "change_rate")
    assert change.value["from"] == 1 and change.value["to"] == 12
    assert charts[0].chart_type == "line" and "line" in charts[0].supported_chart_types


def test_zero_or_negative_baseline_has_no_change_rate():
    raw = b"date,value\n2026-01-01,0\n2026-02-01,10\n"
    candidate = task([step("group_aggregate", {"dimensions":["field_0001"],"metrics":[{"function":"sum","field":"field_0002","alias":"value"}]})])
    evidence, _ = build(report_case([candidate], raw))
    assert not any(e.evidence_type == "change_rate" for e in evidence)
    assert any(e.evidence_type == "difference" for e in evidence)


def test_scalar_kpi_and_metric_comparison():
    candidate = task([step("aggregate", {"metrics":[{"function":"avg","field":"field_0003","alias":"average"},{"function":"median","field":"field_0003","alias":"median"}]})])
    evidence, charts = build(report_case([candidate]))
    assert any(e.evidence_type == "comparison" for e in evidence)
    assert charts[0].chart_type == "table"
    candidate["steps"][0]["params"]["metrics"].pop()
    _, charts = build(report_case([candidate]))
    assert charts[0].chart_type == "kpi"


def test_many_categories_and_long_labels_choose_bar_not_wordcloud_or_pie():
    raw = ("category,value\n" + "\n".join(f"very-long-category-name-{index},1" for index in range(20))).encode()
    candidate = task([step("group_aggregate", {"dimensions":["field_0001"],"metrics":[{"function":"count","alias":"job_count"}]})])
    _, charts = build(report_case([candidate], raw))
    assert charts[0].chart_type == "bar" and charts[0].display_limit == 10
    assert charts[0].supported_chart_types == ["bar","table"] and "完整" in charts[0].note


def test_ties_preserve_competition_ranks_and_all_extreme_sources():
    raw = b"city\na\nb\nc\n"
    evidence, _ = build(report_case([task()], raw))
    ranks = [e.value["rank"] for e in evidence if e.evidence_type == "ranking"]
    assert ranks == [1,1,1]
    maximum = next(e for e in evidence if e.evidence_type == "maximum")
    assert maximum.value["tie_count"] == 3 and len(maximum.source_row_indices) == 3


def test_execution_contract_rejects_status_values_truncation_and_shape_conflicts():
    original = report_case()[2].model_dump()
    for mutation in ["nan", "shape", "status", "truncated", "wrong_type", "duplicate_result"]:
        data = copy.deepcopy(original)
        result = data["tasks"][0]["result"]
        if mutation == "nan": result["rows"][0]["job_count"] = float("nan")
        if mutation == "shape": result["rows"][0]["invented"] = 1
        if mutation == "status": data["execution_status"] = "partial_success"
        if mutation == "truncated": result["truncated"] = True
        if mutation == "wrong_type": result["rows"][0]["job_count"] = "2"
        if mutation == "duplicate_result": data["tasks"].append(copy.deepcopy(data["tasks"][0]))
        with pytest.raises(ValidationError): ExecutionResultV1.model_validate(data)


def test_explicit_total_does_not_turn_top_n_into_a_whole_composition_pie():
    from app.domain.execution import TotalReference
    grouped = task([step(), step("top_n", {"field":"job_count","direction":"desc","n":1}, "S02")])
    total = task([step("aggregate", {"metrics":[{"function":"count","alias":"total_count"}]})], tid="A02", priority="P1")
    case = report_case([grouped, total])
    case[2].tasks[0].result.total_refs = [TotalReference(metric_field="job_count", result_id="R002", result_field="total_count")]
    evidence, charts = build(case)
    assert any(e.evidence_type == "proportion" for e in evidence)
    assert "pie" not in charts[0].supported_chart_types


def test_negative_values_do_not_create_whole_composition_shares():
    raw = b"city,value\na,-10\nb,30\n"
    candidate = task([step("group_aggregate", {"dimensions":["field_0001"],"metrics":[{"function":"sum","field":"field_0002","alias":"value"}]})])
    evidence, charts = build(report_case([candidate], raw))
    assert not any(e.evidence_type == "proportion" for e in evidence)
    assert charts[0].chart_type == "bar" and "pie" not in charts[0].supported_chart_types


def test_denominator_with_different_filter_scope_is_rejected():
    from app.domain.execution import TotalReference
    grouped = task([step("filter", {"conditions":[{"field":"field_0001","operator":"eq","value":"上海"}]}),
        step(sid="S02")])
    total = task([step("aggregate", {"metrics":[{"function":"count","alias":"total_count"}]})], tid="A02", priority="P1")
    case = report_case([grouped,total])
    case[2].tasks[0].result.total_refs = [TotalReference(metric_field="job_count", result_id="R002", result_field="total_count")]
    with pytest.raises(AppError) as exc: build(case)
    assert exc.value.error.code == "REPORT_DENOMINATOR_INVALID"
