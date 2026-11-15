"""Structural repairs do not authorize unsafe facts or cross-scope combinations."""
import copy
import json

import pytest
from app.domain.errors import AppError
from app.reporting.fact_validation import materialize, materialize_candidates
from app.reporting.prompt import request_schema
from app.reporting.presentation import build_presentation
from test_insight_composition import artifacts, draft


def test_missing_declared_primary_is_bound_with_audit_and_original_is_unchanged():
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_lead')
    secondary = next(e for e in evidence if e.evidence_type == 'ranking' and e.result_field == primary.result_field)
    candidate = draft(primary.evidence_id, [secondary.evidence_id], 'difference')
    before = candidate.model_dump_json()
    repairs = []
    accepted, rejected = materialize_candidates(candidate, evidence, tasks, tables, repairs=repairs)
    assert not rejected and primary.evidence_id in accepted[0].evidence_refs
    assert repairs[0]['rule'] == 'BIND_DECLARED_PRIMARY'
    assert candidate.model_dump_json() == before


@pytest.mark.parametrize('fault', ['unknown', 'scope', 'metric', 'duplicate', 'unsafe_prose'])
def test_binding_repair_does_not_override_evidence_or_text_failures(fault):
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_lead')
    secondary = next(e for e in evidence if e.evidence_type == 'ranking' and e.result_field == primary.result_field)
    selected = [secondary.evidence_id]
    if fault == 'unknown':
        selected = ['nonexistent']
    elif fault in {'scope', 'metric'}:
        secondary = copy.deepcopy(secondary)
        secondary.evidence_id = 'DIFFERENT'
        if fault == 'scope':
            secondary.scope = '另一个时间范围'
        else:
            secondary.result_field = 'profit'
        evidence.append(secondary)
        selected = [secondary.evidence_id]
    elif fault == 'duplicate':
        selected *= 2
    candidate = draft(primary.evidence_id, selected, 'difference',
        '已经证实营销导致增长。' if fault == 'unsafe_prose' else '这组差异值得核查。')
    with pytest.raises(AppError):
        materialize_candidates(candidate, evidence, tasks, tables, repairs=[])


def test_exact_negative_boundary_is_allowed_but_following_assertion_is_not():
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_lead')
    boundary = '当前数据不足以判断导致该差异的具体原因或团队效率高低。'
    assert materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', boundary), evidence, tasks, tables)
    with pytest.raises(AppError):
        materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', boundary + '但已证实利润更高。'), evidence, tasks, tables)


@pytest.mark.parametrize('text', [
    '当前数据不足以判断造成该差异的具体原因或团队效率高低。',
    '现有结果无法判断导致这种差异的业务原因。',
    '当前数据不能判断造成差异的原因。',
])
def test_closed_negative_grammar_does_not_mask_affirmative_tail(text):
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_lead')
    assert materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', text), evidence, tasks, tables)
    for tail in ['但营销导致增长。', '所以利润高于其他地区。', '实际差值为999。']:
        with pytest.raises(AppError):
            materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', text + tail), evidence, tasks, tables)


def test_threshold_and_unbound_quality_numbers_still_fail():
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_ratio')
    for text in ['比例差异较大。', '上传范围存在1条缺失。']:
        with pytest.raises(AppError):
            materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', text), evidence, tasks, tables)


def test_dynamic_schema_exposes_verified_limits_and_core_count_without_changing_public_shape():
    evidence, _, _ = artifacts()
    limits = ['上传范围内，响应分钟有 1 条缺失；指标有效记录以执行口径为准。']
    schema = request_schema(evidence, limits, [{'task_id': 'A01'}, {'task_id': 'A02'}])
    assert schema['properties']['insights']['minItems'] == 2
    assert schema['$defs']['DraftInsight']['properties']['limitations']['items']['enum'] == limits
    assert set(schema['$defs']['DraftInsight']['properties']) == {'primary_evidence_id', 'evidence_refs', 'finding_type', 'implication', 'recommendation', 'limitations'}


def test_saved_v111_keeps_authoritative_findings_after_runtime_upgrade():
    from pathlib import Path
    from app.domain.analysis_report import AnalysisReport
    root = Path(__file__).resolve().parents[2]
    original = (root/'docs/evaluations/mvp-product-v1-2026-11-04/runs/baseline01/S01/analysis-report.json').read_text()
    report = AnalysisReport.model_validate_json(original)
    assert {m['insight_generation_version'] for m in report.execution_metadata.values()} == {'evidence-composition-v1.1.1'}
    view = build_presentation(report)
    assert [f.title for f in view.findings] == [i.finding for i in report.insights]
    assert view.evidence == []
    assert json.loads(original) == report.model_dump(mode='json')


def test_actual_ascending_sales_result_is_not_reversed_by_chart_recommendation():
    from pathlib import Path
    from app.domain.analysis_plan import ValidatedAnalysisPlan
    from app.domain.dataset_profile import DatasetProfile
    from app.domain.execution import ExecutionResultV1
    from app.domain.intent import ParsedIntent
    from app.reporting.contracts import prepare
    from app.reporting.evidence import EvidenceBuilder
    from app.reporting.visualization import VisualizationBuilder
    from app.planning.capabilities import CapabilityRegistry
    root = Path(__file__).resolve().parents[2]
    folder = root / 'docs/evaluations/mvp-reliability-holdout2-2026-11-04/runs/repair02/V01'
    state = json.loads((folder/'prepared-session.json').read_text())
    validated = ValidatedAnalysisPlan.model_validate(state['review_plan']['validated_plan'])
    intent = validated.intent_snapshot
    execution = ExecutionResultV1.model_validate_json((folder/'execution-complete.json').read_text())
    profile = DatasetProfile.model_validate_json((folder/'profile.json').read_text())
    _, descriptions = prepare(intent, validated, execution, profile, CapabilityRegistry())
    evidence = EvidenceBuilder().build(execution, profile, descriptions)
    charts = VisualizationBuilder().build(execution, descriptions, evidence, {t.task_id:t for t in validated.plan.tasks}, intent)
    assert charts and all(c.order == 'original' for c in charts)
    metric = next(c.field for c in execution.tasks[0].result.columns if c.role == 'metric')
    values = [r[metric] for r in execution.tasks[0].result.rows]
    assert values == sorted(values)


@pytest.mark.parametrize('text', [
    '平均单笔销售额受产品结构和促销策略影响较大。',
    '高频品类可能具有更强的用户粘性。',
])
def test_observed_exploratory_business_assertions_are_not_licensed_by_cautious_prefix(text):
    evidence, tasks, tables = artifacts()
    primary = next(e for e in evidence if e.value.get('comparison_kind') == 'relative_lead')
    with pytest.raises(AppError) as failure:
        materialize(draft(primary.evidence_id, [primary.evidence_id], 'difference', text), evidence, tasks, tables)
    assert 'UNSUPPORTED_EXPLANATION' in failure.value.error.details['matches']
