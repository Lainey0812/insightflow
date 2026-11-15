"""Regression for result-equality hiding a wrong redundant predicate."""
import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/mvp_plan_scope_audit.py'
SPEC = importlib.util.spec_from_file_location('scope_audit', SCRIPT)
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


def task(value='丙', operator='ne'):
    return {'steps': [
        {'operation': 'filter', 'params': {'conditions': [
            {'field': 'status', 'operator': 'eq', 'value': '已完成'},
            {'field': 'project', 'operator': operator, 'value': value}]}},
        {'operation': 'aggregate', 'params': {'metrics': [{'function': 'sum', 'field': 'hours', 'alias': 'total'}]}}
    ]}


CASE = {'filters': [['状态', 'eq', '已完成'], ['项目', 'ne', '丙']]}
NAMES = {'状态': 'status', '项目': 'project'}


def test_wrong_literal_is_not_proved_even_when_it_would_not_change_the_result():
    result = scope.audit_scope(CASE, task('丙项目'), NAMES)
    assert not result['passed']
    assert {i['code'] for i in result['issues']} == {'REQUIRED_PREDICATE_NOT_PROVED', 'UNREQUESTED_OR_WRONG_FILTER'}


@pytest.mark.parametrize('value,operator', [('丙', 'ne'), (['丙'], 'not_in')])
def test_explicit_semantically_equivalent_exclusion(value, operator):
    assert scope.audit_scope(CASE, task(value, operator), NAMES)['passed']


def test_extra_excluded_value_and_wrong_scalar_type_do_not_pass():
    assert not scope.audit_scope(CASE, task(['丙', '乙'], 'not_in'), NAMES)['passed']
    assert scope.predicate_key('x', 'eq', 1) != scope.predicate_key('x', 'eq', '1')


def test_unrequested_filter_is_not_approved_by_full_row_coincidence():
    assert not scope.audit_scope({'filters': []}, task(), NAMES)['passed']


def test_unsupported_year_boundary_stays_unproved():
    candidate = {'steps': [
        {'operation': 'filter', 'params': {'conditions': [{'field': 'date', 'operator': 'gte', 'value': '2026-01-01'}]}},
        {'operation': 'aggregate', 'params': {'metrics': []}}
    ]}
    assert not scope.audit_scope({'filters': [['日期', 'year', 2026]]}, candidate, {'日期': 'date'})['passed']
