import asyncio
import copy
import json

import pytest

from app.domain.analysis_report import InsightDraft
from app.domain.errors import AppError
from app.llm.compatible_provider import UnconfiguredLLMProvider
from app.planning.capabilities import CapabilityRegistry
from app.reporting.export import render_report_v1
from app.services.analysis_report import AnalysisReportService
from planning_fixtures import step, task
from report_fixtures import ReportProvider, report_case


def generate(case=None, provider=None, timeout=30):
    provider = provider or ReportProvider()
    return asyncio.run(AnalysisReportService(provider, CapabilityRegistry(), timeout).generate(*(case or report_case())))


def draft(primary="E0002", refs=None, kind="highlight", implication=None, recommendation=None):
    item = {"primary_evidence_id":primary,"evidence_refs":refs or [primary],"finding_type":kind,
            "recommendation_id":"none","limitation_refs":[]}
    # Explicit old prose is an invalid V2 response; it is never translated.
    if implication is not None: item['implication'] = implication
    if recommendation is not None: item['recommendation'] = recommendation
    return {"insights":[item]}


def test_complete_report_uses_evidence_and_retains_true_data():
    provider = ReportProvider()
    case = report_case()
    original = case[2].model_dump()
    report = generate(case, provider)
    assert report.report_status == report.goal_coverage == "complete"
    assert report.result_data["R001"].rows == original["tasks"][0]["result"]["rows"]
    assert case[2].model_dump() == original
    assert report.insights and report.charts
    assert report.insights[0].fact != report.insights[0].finding
    refs = {e.evidence_id for e in report.evidence}
    assert all(set(i.evidence_refs) <= refs for i in report.insights)
    assert report.fact_validation == "structured_facts_verified_interpretations_unverified"
    assert report.llm.is_mock and report.execution_source == "imported"
    assert report.provenance.source == "mock"
    assert report.execution_metadata["A01"]["sample_definition"]
    payload = json.loads(provider.requests[0].instruction)
    assert "result_data" not in payload and "20-30K" not in provider.requests[0].instruction


def test_partial_success_keeps_only_successful_task_contents_and_coverage():
    unsupported = task([step("derive", {"function":"extract_skills","field":"field_0005","alias":"skills"})], tid="A02")
    report = generate(report_case([task(), unsupported]))
    assert report.report_status == report.goal_coverage == "partial"
    assert {e.task_id for e in report.evidence} == {"A01"}
    assert {c.task_id for c in report.charts} == {"A01"}
    assert report.uncompleted_tasks[0].task_id == "A02"
    assert "缺口" not in report.summary.headline or "部分" in report.summary.headline


def test_no_core_answer_never_claims_goal_complete():
    report = generate(report_case([task(), task(tid="A02",priority="P1")], failures=["A01"]))
    assert report.report_status == "partial" and report.goal_coverage == "blocked"
    assert "尚不能回答" in report.summary.headline
    assert all(e.task_id == "A02" for e in report.evidence)


def test_no_valid_evidence_returns_unavailable_and_never_calls_llm():
    for case in [report_case(failures=["A01"]),
                 report_case([task([step("aggregate",{"metrics":[{"function":"avg","field":"field_0003","alias":"average"}]})])], null_metrics=True)]:
        provider = ReportProvider()
        report = generate(case, provider)
        assert report.report_status == "unavailable" and report.goal_coverage == "blocked"
        assert not report.charts and not report.insights and not provider.requests and report.llm is None


def test_generation_status_and_goal_coverage_are_independent():
    case = report_case()
    from app.domain.intent import UnverifiedConstraint
    case[0].constraints.time_range = UnverifiedConstraint(raw_text="今年", validation_status="unverified")
    report = generate(case)
    assert report.report_status == "complete" and report.goal_coverage == "partial"
    assert any("需求约束" in x for x in report.limitations)


@pytest.mark.parametrize("output,code", [
    (draft(primary="E9999"), "REPORT_INVALID_EVIDENCE_REFERENCE"),
    (draft(refs=["E0002","E0002","E9999"]), "REPORT_INVALID_EVIDENCE_REFERENCE"),
    (draft(kind="trend"), "REPORT_INVALID_EVIDENCE_TYPE"),
    (draft(implication="当前有42条记录。"), "REPORT_LLM_INVALID_OUTPUT"),
    (draft(implication="占百分之五十。"), "REPORT_LLM_INVALID_OUTPUT"),
    (draft(implication="排名第一。"), "REPORT_LLM_INVALID_OUTPUT"),
    (draft(implication="需求导致岗位集中。"), "REPORT_LLM_INVALID_OUTPUT"),
    (draft(recommendation="保证能够获得机会。"), "REPORT_LLM_INVALID_OUTPUT"),
    ("invalid JSON", "REPORT_LLM_INVALID_OUTPUT"),
    ('{"insights":[],"insights":[]}', "REPORT_LLM_INVALID_OUTPUT"),
    ({"insights":[],"headline":"目标完成"}, "REPORT_LLM_INVALID_OUTPUT"),
    ({"insights":[{**draft()["insights"][0], "fact":"上海有42条"}]}, "REPORT_LLM_INVALID_OUTPUT"),
])
def test_model_cannot_introduce_unverified_facts_or_claims(output, code):
    with pytest.raises(AppError) as exc: generate(provider=ReportProvider(output))
    assert exc.value.error.code == code


def test_cautious_denial_of_causality_is_allowed():
    report = generate(provider=ReportProvider(draft()))
    assert "未验证" in report.insights[0].implication
    assert report.insights


@pytest.mark.parametrize("mutation,code", [("mock","MOCK_EXECUTION_NOT_REPORTABLE"),("version","REPORT_INPUT_MISMATCH"),
    ("approval","REPORT_INPUT_MISMATCH"),("fields","REPORT_INPUT_MISMATCH"),("count","REPORT_INPUT_MISMATCH"),
    ("type","REPORT_INPUT_INVALID"),("validation","REPORT_INPUT_MISMATCH"),("missing_task","REPORT_INPUT_MISMATCH")])
def test_input_bindings_and_schema_cannot_be_bypassed(mutation, code):
    case = report_case()
    if mutation == "mock": case[2].source = "mock"
    if mutation == "version": case[2].dataset_version = "0"*64
    if mutation == "approval": case[2].approved_plan_version = 2
    if mutation == "fields":
        table = case[2].tasks[0].result
        table.columns[0].field = "invented"
        for row in table.rows: row["invented"] = row.pop("field_0001")
    if mutation == "count": case[2].tasks[0].result.rows[0]["job_count"] = 99
    if mutation == "type": case[2].tasks[0].result.rows[0]["job_count"] = "2"
    if mutation == "validation": case[1].validation_results[0].executable = False
    if mutation == "missing_task": case[2].tasks.clear(); case[2].execution_status = "failed"
    provider = ReportProvider()
    with pytest.raises(AppError) as exc: generate(case, provider)
    assert exc.value.error.code == code and not provider.requests


def test_model_errors_clear_timeout_and_no_mock_fallback():
    with pytest.raises(AppError) as exc: generate(provider=UnconfiguredLLMProvider())
    assert exc.value.error.code == "LLM_NOT_CONFIGURED"
    with pytest.raises(AppError) as exc: generate(provider=ReportProvider(error=RuntimeError("secret")))
    assert exc.value.error.code == "REPORT_LLM_CALL_FAILED" and "secret" not in exc.value.error.message
    class Slow:
        async def generate(self, request): await asyncio.sleep(1)
    with pytest.raises(AppError) as exc: generate(provider=Slow(), timeout=.01)
    assert exc.value.error.code == "LLM_TIMEOUT"


def test_optional_offline_html_is_escaped_and_traceable():
    raw = b"city\n<script>alert('x')</script>\nnormal\n"
    report = generate(report_case([task()], raw))
    exported = render_report_v1(report)
    assert "<script>" not in exported and "&lt;script&gt;" in exported
    assert "证据与统计口径" in exported and report.execution_id in exported
    assert "E0002" in exported and "离线版本保留完整返回表格" in exported


def test_insight_schema_strict_for_structured_output():
    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values(): inspect(child)
        elif isinstance(node,list):
            for child in node: inspect(child)
    inspect(InsightDraft.model_json_schema())


def test_cross_task_evidence_and_omitted_core_findings_are_rejected():
    case = report_case([task(), task(tid="A02",priority="P1")])
    baseline = generate(case)
    primary = next(e.evidence_id for e in baseline.evidence if e.task_id == "A01" and e.evidence_type == "ranking")
    other = next(e.evidence_id for e in baseline.evidence if e.task_id == "A02" and e.evidence_type == "ranking")
    with pytest.raises(AppError) as exc:
        generate(case, ReportProvider(draft(primary, [primary,other])))
    assert exc.value.error.code == "REPORT_INVALID_EVIDENCE_REFERENCE"
    with pytest.raises(AppError) as exc:
        generate(case, ReportProvider(draft(other)))
    assert exc.value.error.code == "REPORT_CORE_FINDINGS_MISSING"


def test_exact_repeated_reference_is_audited_without_adding_or_changing_facts():
    import copy
    output=draft(refs=["E0002","E0002"]);before=copy.deepcopy(output)
    report=generate(provider=ReportProvider(output))
    assert report.insights[0].evidence_refs==["E0002"]
    metadata=next(iter(report.execution_metadata.values()))
    assert metadata['candidate_repairs'][0]['original_refs']==["E0002","E0002"]
    assert metadata['candidate_repairs'][0]['normalized_refs']==["E0002"]
    assert metadata['candidate_repairs'][0]['validated'] is True
    assert output==before
