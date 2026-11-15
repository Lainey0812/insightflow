"""Selection-only reports: structural/operand guarantees, no free-text bypass."""
import copy
import json
import asyncio

import pytest
from pydantic import ValidationError
from app.domain.analysis_report import AnalysisReport
from app.domain.errors import AppError
from app.reporting.draft_v2 import InsightSelection, selection_schema
from app.reporting.recommendations import build_catalog, NO_RECOMMENDATION
from app.reporting.materialize_v2 import materialize_selection
from app.reporting.contracts import prepare
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from report_fixtures import report_case, ReportProvider
from test_insight_composition import artifacts


def context():
    inputs = report_case()
    evidence, tasks, tables = artifacts(inputs)
    profile = inputs[3]
    options = build_catalog(evidence, tasks, profile, inputs[0])
    limits = {'L1': '结论仅适用于上传样本。'}
    return evidence, tasks, tables, profile, options, limits


def choice(evidence, **changes):
    primary = next(e for e in evidence if e.evidence_type == 'ranking')
    return {'primary_evidence_id': primary.evidence_id, 'evidence_refs': [primary.evidence_id],
            'finding_type': 'highlight', 'recommendation_id': 'none', 'limitation_refs': ['L1'], **changes}


def render(data, ctx):
    return materialize_selection(InsightSelection.model_validate({'insights': [data]}), *ctx)


@pytest.mark.parametrize('field', ['implication', 'recommendation', 'limitations', 'fact', 'python', 'sql'])
def test_legacy_or_extra_free_text_is_never_accepted(field):
    ctx = context(); data = choice(ctx[0]); data[field] = '营销导致增长，用户粘性更强。'
    with pytest.raises(ValidationError):
        InsightSelection.model_validate({'insights': [data]})


def test_fact_composition_preserved_and_no_recommendation_is_explicit():
    ctx = context(); selected, rejected = render(choice(ctx[0]), ctx)
    assert not rejected and selected[0].finding
    assert selected[0].recommendation == NO_RECOMMENDATION
    assert selected[0].evidence_refs


@pytest.mark.parametrize('fault', ['missing_primary', 'unknown_evidence', 'wrong_type', 'unknown_recommendation', 'unknown_limit', 'duplicate_limit'])
def test_invalid_selection_has_stable_failure_and_no_fallback(fault):
    ctx = context(); data = choice(ctx[0])
    if fault == 'missing_primary':
        data['primary_evidence_id'] = next(e.evidence_id for e in ctx[0] if e.evidence_id not in data['evidence_refs'])
    elif fault == 'unknown_evidence':
        data['evidence_refs'] = ['MISSING']
    elif fault == 'wrong_type':
        data['finding_type'] = 'trend'
    elif fault == 'unknown_recommendation':
        data['recommendation_id'] = 'MISSING'
    elif fault == 'unknown_limit':
        data['limitation_refs'] = ['MISSING']
    else:
        data['limitation_refs'] *= 2
    with pytest.raises(AppError):
        render(data, ctx)


def test_recommendation_is_bound_to_actual_group_and_source_fields():
    ctx = context(); data = choice(ctx[0]); primary = next(e for e in ctx[0] if e.evidence_id == data['primary_evidence_id'])
    option = next(o for o in ctx[4].values() if (o['task_id'], o['data_ref'], o['result_field']) == (primary.task_id, primary.data_ref, primary.result_field))
    data['recommendation_id'] = option['option_id']
    selected, _ = render(data, ctx)
    assert '尚未执行' in selected[0].recommendation
    for fid in option['field_ids']:
        assert next(f.display_name for f in ctx[3].fields if f.field_id == fid) in selected[0].recommendation
    option['description'] = '销售额最高100万，营销导致增长。'
    assert render(data, ctx)[0][0].recommendation == selected[0].recommendation
    option['data_ref'] = 'OTHER'
    with pytest.raises(AppError):
        render(data, ctx)


def test_unknown_or_wrong_field_types_cannot_be_materialized():
    ctx = context(); data = choice(ctx[0]); primary = next(e for e in ctx[0] if e.evidence_id == data['primary_evidence_id'])
    option = next(o for o in ctx[4].values() if o['task_id'] == primary.task_id and o['result_field'] == primary.result_field)
    data['recommendation_id'] = option['option_id']
    option['field_ids'] = ['field_DOES_NOT_EXIST']
    with pytest.raises(AppError): render(data, ctx)


def test_actual_operands_are_revalidated_not_just_ids():
    ctx = context(); data = choice(ctx[0]); e = next(e for e in ctx[0] if e.evidence_id == data['primary_evidence_id'])
    e.value['value'] = 999999
    with pytest.raises(AppError): render(data, ctx)


def test_public_report_shape_unchanged_and_service_does_not_fallback_to_v1():
    inputs = report_case()
    report = asyncio.run(AnalysisReportService(ReportProvider(), CapabilityRegistry()).generate(*inputs))
    assert report.insights and all(m['draft_schema_version'] == 'insight-selection-v2' for m in report.execution_metadata.values())
    assert AnalysisReport.model_validate(report.model_dump())
    legacy = {'insights': [{'primary_evidence_id': 'E1', 'evidence_refs': ['E1'], 'finding_type': 'highlight',
              'implication': '旧格式', 'recommendation': '旧格式', 'limitations': []}]}
    with pytest.raises(AppError) as failure:
        asyncio.run(AnalysisReportService(ReportProvider(legacy), CapabilityRegistry()).generate(*inputs))
    assert failure.value.error.code == 'REPORT_LLM_INVALID_OUTPUT'


def test_partial_candidate_rejection_is_disclosed_and_error_is_serializable():
    ctx = context(); good = choice(ctx[0]); bad = {**good, 'recommendation_id': 'unknown'}
    draft = InsightSelection.model_validate({'insights': [good, bad]})
    accepted, rejected = materialize_selection(draft, *ctx)
    assert len(accepted) == len(rejected) == 1
    json.dumps(rejected)
    with pytest.raises(AppError) as failure:
        materialize_selection(InsightSelection.model_validate({'insights': [bad]}), *ctx)
    # Failure metadata must be persistable, not a recursive error object.
    json.dumps(failure.value.error.model_dump())


def test_cross_task_and_cross_metric_are_not_legal_same_metric_comparisons():
    ctx = context(); good = choice(ctx[0]); primary = next(e for e in ctx[0] if e.evidence_id == good['primary_evidence_id'])
    for mutation in ('task_id', 'data_ref', 'result_field', 'scope'):
        other = copy.deepcopy(primary); other.evidence_id = 'OTHER'; setattr(other, mutation, 'unrelated')
        local = ([*ctx[0], other], *ctx[1:])
        with pytest.raises(AppError): render({**good, 'evidence_refs': [primary.evidence_id, 'OTHER']}, local)


def test_service_preserves_partial_state_without_substituting_rejected_selection():
    class PartialProvider(ReportProvider):
        async def generate(self, request):
            response = await super().generate(request)
            value = json.loads(response.text)
            value['insights'].append({**value['insights'][0], 'recommendation_id': 'unknown'})
            return response.model_copy(update={'text': json.dumps(value)})
    report = asyncio.run(AnalysisReportService(PartialProvider(), CapabilityRegistry()).generate(*report_case()))
    assert report.report_status == 'partial' and len(report.insights) == 1
    assert any('候选洞察未通过校验' in s for s in report.limitations)


def test_history_v123_uses_saved_insights_without_reinterpreting_content():
    from app.reporting.presentation import build_presentation
    inputs = report_case()
    report = asyncio.run(AnalysisReportService(ReportProvider(), CapabilityRegistry()).generate(*inputs))
    for metadata in report.execution_metadata.values():
        metadata['insight_generation_version'] = 'evidence-composition-v1.2.3'
    saved = report.model_dump_json()
    view = build_presentation(report, inputs[3])
    assert [f.title for f in view.findings] == [i.finding for i in report.insights]
    assert report.model_dump_json() == saved


def test_catalogue_respects_explicit_prohibition_without_inventing_fields():
    from app.domain.intent import UnverifiedConstraint
    inputs = report_case()
    evidence, tasks, tables = artifacts(inputs)
    excluded = inputs[3].fields[-1]
    inputs[0].constraints.analysis_limits = [UnverifiedConstraint(raw_text='不要分析' + excluded.display_name, validation_status='unverified')]
    options = build_catalog(evidence, tasks, inputs[3], inputs[0])
    assert all(excluded.field_id not in item['field_ids'] for item in options.values())
    assert all(set(item['field_ids']) <= {f.field_id for f in inputs[3].fields} for item in options.values())


def test_unknown_analysis_boundary_does_not_authorize_unrelated_extra_fields():
    from app.domain.intent import UnverifiedConstraint
    from app.reporting.recommendations import source_fields
    inputs = report_case(); evidence, tasks, _ = artifacts(inputs)
    inputs[0].constraints.analysis_limits = [UnverifiedConstraint(raw_text='不要推断员工积极性', validation_status='unverified')]
    options = build_catalog(evidence, tasks, inputs[3], inputs[0])
    assert all(set(item['field_ids']) <= source_fields(tasks[item['task_id']]) for item in options.values())
