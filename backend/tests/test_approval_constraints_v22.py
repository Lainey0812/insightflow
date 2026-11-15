"""Read-only saved-run replay and adversarial approval boundary regression."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.intent import UnverifiedConstraint
from app.domain.errors import AppError
from app.review.constraint_audit import ConstraintAuditor
from app.review.bindings import record_count
from app.review import output_boundaries
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from report_fixtures import ReportProvider, report_case

ROOT=Path(__file__).resolve().parents[2]
PATHS={
 'T04':'docs/evaluations/mvp-product-v1-2026-11-04/runs/draftv2-01/T04',
 'U02':'docs/evaluations/mvp-reliability-holdout-2026-11-04/runs/draftv2-01/U02',
 'W03':'docs/evaluations/report-draft-v2-2026-11-05/independent/runs/draftv2-01/W03',
 'W04':'docs/evaluations/report-draft-v2-2026-11-05/independent/runs/draftv2-01/W04'}


def saved(case):
    state=json.loads((ROOT/PATHS[case]/'prepared-session.json').read_text())
    return ValidatedAnalysisPlan.model_validate(state['review_plan']['validated_plan']),DatasetProfile.model_validate(state['profile'])


def constraint(text):return UnverifiedConstraint(raw_text=text, validation_status='unverified')


@pytest.mark.parametrize('case',PATHS)
def test_actual_four_blocked_plans_now_have_complete_proofs_without_rewriting_intent(case):
    checked,profile=saved(case);before=checked.model_dump_json()
    audit=ConstraintAuditor(profile).audit(checked)
    assert audit.all_verified,[(v.raw_text,v.message) for v in audit.items if v.status!='verified']
    assert checked.model_dump_json()==before and audit.audit_version=='2.3'
    assert all(v.matches for v in audit.items)


@pytest.mark.parametrize('fault',['wrong_filter','wrong_order','nonnull_count','distinct_count','extra_filter','extra_dimension','quantity_column'])
def test_repaired_task_count_does_not_allow_different_computation(fault):
    checked,profile=saved('W04');task=checked.plan.tasks[0]
    agg=next(s for s in task.steps if s.operation=='group_aggregate')
    if fault=='wrong_filter':task.steps[0].params['conditions'][0]['value']='待处理'
    elif fault=='wrong_order':task.steps[-1].params['direction']='asc'
    elif fault=='nonnull_count':agg.params['metrics'][0]['field']=profile.fields[2].field_id
    elif fault=='distinct_count':agg.params['metrics'][0].update(function='distinct_count',field=profile.fields[0].field_id)
    elif fault=='extra_dimension':agg.params['dimensions'].append(profile.fields[3].field_id)
    elif fault=='quantity_column':profile.fields[2].display_name=profile.fields[2].original_name='任务数量'
    else:task.steps[0].params['conditions'].append({'field':profile.fields[0].field_id,'operator':'eq','value':'星桥'})
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_omitted_sort_basis_requires_unique_matching_metric():
    checked,profile=saved('W03');agg=next(s for s in checked.plan.tasks[0].steps if s.operation=='group_aggregate')
    agg.params['metrics'].append({**agg.params['metrics'][0],'alias':'another_mean'})
    assert not ConstraintAuditor(profile).audit(checked).all_verified


@pytest.mark.parametrize('field',['task_id','field_type'])
def test_full_categorical_value_is_not_satisfied_by_ambiguous_field_or_truncated_sample(field):
    checked,profile=saved('W04');status=next(f for f in profile.fields if f.display_name=='状态')
    if field=='task_id':
        other=profile.fields[-1];other.logical_type=type(other.logical_type)('text');other.samples=copy.deepcopy(status.samples)
    else:
        for s in status.samples:s.truncated=True
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_task_entity_context_does_not_implicitly_authorize_unrelated_entity_count():
    _,profile=saved('W04')
    assert not record_count('任务数量',profile)
    assert record_count('任务数量',profile,'已完成任务的项目分布')
    assert not record_count('订单数量',profile,'已完成任务的项目分布')


@pytest.mark.parametrize('text',['不要推断客户忠诚度','不要分析所有东西','不要求分析利润','未指定利润','不要推断团队差异的未知原因'])
def test_unknown_optional_or_unspecified_boundary_is_not_silently_authorized(text):
    checked,profile=saved('W03');checked.intent_snapshot.constraints.analysis_limits.append(constraint(text))
    assert not ConstraintAuditor(profile).audit(checked).all_verified


@pytest.mark.parametrize('fault',['alias','field','derive','old_renderer'])
def test_report_boundary_proof_requires_no_prohibited_calculation_and_supported_renderer(fault,monkeypatch):
    checked,profile=saved('T04');task=checked.plan.tasks[0]
    agg=next(s for s in task.steps if s.operation=='group_aggregate')
    if fault=='alias':agg.params['metrics'][0]['alias']='profit_total'
    elif fault=='field':
        profile.fields[-1].display_name='利润';agg.params['metrics'][0]['field']=profile.fields[-1].field_id
    elif fault=='derive':
        task.steps.insert(0,task.steps[0].model_copy(update={'operation':'derive','params':{'function':'profit','alias':'p'}}))
    else:monkeypatch.setattr('app.reporting.prompt.GENERATION_VERSION','legacy-free-text')
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_reporting_runtime_checks_policy_again_without_llm_fallback():
    inputs=report_case();inputs[0].constraints.analysis_limits=[constraint('不要推断人员绩效')]
    with pytest.raises(AppError) as error:output_boundaries.enforce(inputs[0],'legacy-free-text')
    assert error.value.error.code=='REPORT_BOUNDARY_UNSUPPORTED'


def test_actual_report_uses_controlled_titles_and_no_extra_analysis_directions():
    inputs=report_case();inputs[0].constraints.analysis_limits=[constraint('不要推断人员绩效')]
    inputs[1].intent_snapshot=inputs[0]
    inputs[1].plan.tasks[0].title='不应作为事实展示的任意任务标题'
    provider=ReportProvider()
    report=asyncio.run(AnalysisReportService(provider,CapabilityRegistry()).generate(*inputs))
    assert report.summary.headline=='已验证统计结果'
    assert all(c.title.startswith('已验证统计结果') for c in report.charts)
    payload=json.loads(provider.requests[0].instruction)
    assert all(o['kind'] in {'review_source_rows','check_missingness'} for o in payload['recommendation_options'])
    assert all(v['output_boundaries']==['no_performance_inference'] for v in report.execution_metadata.values())


def test_standalone_report_cannot_bypass_profit_boundary_even_without_approval():
    from planning_fixtures import task, step
    inputs=report_case([task([step('group_aggregate', {'dimensions':['field_0001'], 'metrics':[{'function':'count','alias':'profit_total'}]})])])
    inputs[0].constraints.analysis_limits=[constraint('不要分析利润')]
    provider=ReportProvider()
    with pytest.raises(AppError) as error:
        asyncio.run(AnalysisReportService(provider,CapabilityRegistry()).generate(*inputs))
    assert error.value.error.code=='REPORT_BOUNDARY_VIOLATION'
    assert not provider.requests
