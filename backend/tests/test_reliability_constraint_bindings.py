"""Saved real baseline plans, fresh proof checks, and adversarial mutations.

No model responses are fabricated; these are deterministic revalidations, not
new real-model runs. Legacy baseline records remain unchanged.
"""
import json
from pathlib import Path

import pytest
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.review.constraint_audit import ConstraintAuditor

BASE = Path(__file__).resolve().parents[2] / 'docs/evaluations/mvp-product-v1-2026-11-04/runs/baseline01'


def saved(case):
    state = json.loads((BASE / case / 'persisted-final-session.json').read_text())
    checked = ValidatedAnalysisPlan.model_validate(state['review_plan']['validated_plan'])
    profile = DatasetProfile.model_validate(json.loads((BASE / case / 'profile.json').read_text()))
    return checked, profile


@pytest.mark.parametrize('case', ['S01', 'S02', 'R01', 'R03', 'R04', 'T01', 'T02', 'T03', 'P01', 'P02', 'P04'])
def test_saved_correct_plan_has_real_proofs(case):
    checked, profile = saved(case)
    audit = ConstraintAuditor(profile).audit(checked)
    assert audit.all_verified, [(i.raw_text, i.message) for i in audit.items if i.status != 'verified']
    assert audit.audit_version == '2.3'


@pytest.mark.parametrize('fault', ['sum_instead_of_count', 'nonnull_count', 'unique_count', 'wrong_dimension', 'wrong_direction', 'extra_filter'])
def test_count_proof_cannot_be_reused_for_different_computation(fault):
    checked, profile = saved('R01')
    task = checked.plan.tasks[0]
    aggregate = next(s for s in task.steps if s.operation == 'group_aggregate')
    metric = aggregate.params['metrics'][0]
    if fault == 'sum_instead_of_count':
        metric.update(function='sum', field='field_0004')
    elif fault == 'nonnull_count':
        metric['field'] = 'field_0004'
    elif fault == 'unique_count':
        metric.update(function='distinct_count', field='field_0002')
    elif fault == 'wrong_dimension':
        aggregate.params['dimensions'] = ['field_0005']
    elif fault == 'wrong_direction':
        task.steps[-1].params['direction'] = 'asc'
    else:
        from app.domain.analysis_plan import AnalysisStep
        task.steps.insert(0, AnalysisStep(step_id='extra', operation='filter', params={'conditions': [{'field': 'field_0001', 'operator': 'eq', 'value': '上海'}]}))
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_membership_requires_exact_set_not_any_overlap():
    checked, profile = saved('T03')
    condition = next(c for s in checked.plan.tasks[0].steps if s.operation == 'filter' for c in s.params['conditions'])
    condition['value'] = ['二组', '一组']
    assert ConstraintAuditor(profile).audit(checked).all_verified
    condition['value'] = ['一组', '二组', '三组']
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_no_exclusion_does_not_allow_a_positive_filter_that_excludes_beijing():
    checked, profile = saved('R04')
    from app.domain.analysis_plan import AnalysisStep
    checked.plan.tasks[0].steps.insert(0, AnalysisStep(step_id='hidden', operation='filter', params={'conditions': [{'field': 'field_0001', 'operator': 'eq', 'value': '上海'}]}))
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_month_order_must_use_the_derived_dimension_not_metric():
    checked, profile = saved('P01')
    aggregate = next(s for s in checked.plan.tasks[0].steps if s.operation == 'group_aggregate')
    checked.plan.tasks[0].steps[-1].params['field'] = aggregate.params['metrics'][0]['alias']
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_quantity_source_column_does_not_become_a_row_count_alias():
    checked, profile = saved('R01')
    extra = profile.fields[3].model_copy(update={'original_name': '岗位数量', 'display_name': '岗位数量'})
    profile.fields[3] = extra
    assert not ConstraintAuditor(profile).audit(checked).all_verified


def test_duplicate_group_name_in_goal_is_ambiguous_even_when_not_repeated_in_constraints():
    checked, profile = saved('R01')
    profile.fields[4] = profile.fields[4].model_copy(update={'original_name': '城市', 'display_name': '城市'})
    audit = ConstraintAuditor(profile).audit(checked)
    assert not audit.all_verified
    assert any(p.category == 'goal_dimensions' and p.status == 'ambiguous' for p in audit.items)


def test_supported_profit_and_causal_boundary_has_enforced_output_proof():
    checked, profile = saved('T04')
    assert ConstraintAuditor(profile).audit(checked).all_verified
