import copy

import pytest

from app.domain.errors import AppError
from app.planning.capabilities import CapabilityRegistry
from app.planning.validator import PlanValidator
from planning_fixtures import plan, recruiting_profile, step, task


def validate(tasks=None, data=None, profile=None):
    profile = profile or recruiting_profile()
    return PlanValidator(CapabilityRegistry()).validate(data or plan(tasks, profile), profile)


def result(steps):
    return validate([task(steps)]).validation_results[0]


def test_simple_group_count_p0_f2():
    output = validate()
    assert output.coverage_status == "complete" and output.fully_executable
    assert output.validation_results[0].feasibility == "F2"
    assert output.plan.tasks[0].priority == "P0"
    assert output.executable_task_ids == ["A01"] and output.approval_required


def test_filter_group_sort_top_n():
    steps = [step("filter", {"conditions": [{"field": "field_0003", "operator": "gte", "value": 25}]}),
             step(sid="S02"), step("sort", {"field": "job_count", "direction": "desc"}, "S03"),
             step("top_n", {"field": "job_count", "direction": "desc", "n": 1}, "S04")]
    assert result(steps).feasibility == "F2"


@pytest.mark.parametrize("function", ["sum", "avg", "median", "min", "max", "count", "distinct_count"])
def test_numeric_aggregations(function):
    assert result([step("aggregate", {"metrics": [{"function": function, "field": "field_0003", "alias": "value"}]})]).feasibility == "F2"


def test_salary_range_mean_rejected_and_core_retained():
    bad = task([step("aggregate", {"metrics": [{"function": "avg", "field": "field_0002", "alias": "salary"}]})])
    output = validate([bad])
    assert output.validation_results[0].reason_code == "TYPE_MISMATCH"
    assert not output.validation_results[0].executable
    assert output.plan.tasks[0].model_dump() == bad
    assert output.coverage_status == "blocked" and not output.fully_executable
    assert output.unmet_core_requirements[0].task_ids == ["A01"]


@pytest.mark.parametrize("function", ["extract_year", "extract_month"])
def test_real_transform_in_chain_is_f1(function):
    output = result([step("derive", {"function": function, "field": "field_0004", "alias": "period"}),
        step("group_aggregate", {"dimensions": ["period"], "metrics": [{"function": "count", "alias": "jobs"}]}, "S02")])
    assert output.feasibility == "F1" and output.executable
    assert output.reason_code == "REQUIRES_TRANSFORMATION"


@pytest.mark.parametrize("operation,params,code", [
    ("derive", {"function": "extract_skills", "field": "field_0005", "alias": "skills"}, "UNSUPPORTED_OPERATION"),
    ("python", {"code": "print(1)"}, "UNSUPPORTED_OPERATION"),
    ("sort", {"field": "field_9999", "direction": "asc"}, "MISSING_FIELD"),
    ("sort", {"field": "job_count", "direction": "desc"}, "MISSING_FIELD"),
    ("derive", {"function": "extract_year", "field": "field_0002", "alias": "year"}, "TYPE_MISMATCH"),
    ("aggregate", {"metrics": [{"function": "sum", "field": "field_0005", "alias": "total"}]}, "TYPE_MISMATCH"),
    ("filter", {"conditions": [{"field": "field_0003", "operator": "eq", "value": "25"}]}, "TYPE_MISMATCH"),
    ("filter", {"conditions": [{"field": "field_0004", "operator": "gte", "value": "2026-02-30"}]}, "TYPE_MISMATCH"),
    ("aggregate", {"metrics": [{"function": "sum", "alias": "bad"}]}, "INVALID_SCHEMA"),
    ("top_n", {"field": "field_0003", "direction": "desc", "n": True}, "INVALID_SCHEMA"),
    ("sort", {"field": "field_0003", "direction": "desc", "code": "x"}, "INVALID_SCHEMA"),
])
def test_invalid_operations_never_executable(operation, params, code):
    output = result([step(operation, params)])
    assert output.feasibility == "F0" and not output.executable
    assert output.reason_code == code


def test_future_alias_and_removed_field():
    future = result([step("sort", {"field": "job_count", "direction": "desc"}), step(sid="S02")])
    assert future.reason_code == "INVALID_OPERATION_ORDER"
    removed = result([step(), step("sort", {"field": "field_0003", "direction": "desc"}, "S02")])
    assert removed.reason_code == "INVALID_FIELD_REFERENCE"


@pytest.mark.parametrize("params", [
    {"dimensions": ["field_0001", "field_0001"], "metrics": [{"function": "count", "alias": "n"}]},
    {"dimensions": ["field_0001"], "metrics": [{"function": "count", "alias": "n"}, {"function": "count", "alias": "n"}]},
    {"dimensions": ["field_0001"], "metrics": [{"function": "count", "alias": "field_0003"}]},
])
def test_alias_and_dimension_collisions(params):
    assert result([step(params=params)]).feasibility == "F0"


def test_cross_task_dependencies_rejected():
    t = task()
    t["depends_on"] = ["A00"]
    assert validate([t]).validation_results[0].reason_code == "UNSUPPORTED_DEPENDENCY"


def test_coverage_uses_core_not_f0_count():
    unsupported = [step("derive", {"function": "extract_skills", "field": "field_0005", "alias": "skills"})]
    optional_bad = validate([task(), task(unsupported, "A02", "P2")])
    assert optional_bad.coverage_status == "complete" and not optional_bad.fully_executable
    assert not optional_bad.unmet_core_requirements
    partial = validate([task(), task(unsupported, "A02")])
    assert partial.coverage_status == "partial"
    assert partial.unmet_core_requirements[0].task_ids == ["A02"]
    no_core = validate([task(unsupported), task(tid="A02", priority="P1")])
    assert no_core.coverage_status == "blocked"  # optional output cannot answer the core
    assert no_core.executable_task_ids == ["A02"]
    assert validate([task(priority="P1")]).coverage_status == "blocked"
    assert validate([]).coverage_status == "blocked"


def test_multiple_core_requirements_conservative_coverage():
    data = plan()
    data["core_requirements"].append({"requirement_id": "C02", "description": "薪资区间比较"})
    output = validate(data=data)
    assert output.coverage_status == "partial"
    assert output.unmet_core_requirements[0].requirement_id == "C02"


def test_dataset_version_mismatch_and_unknown_goal():
    data = plan()
    data["dataset_version"] = "0" * 64
    assert validate(data=data).validation_results[0].reason_code == "DATASET_VERSION_MISMATCH"
    data = plan()
    data["tasks"][0]["requirement_ids"] = ["made_up"]
    assert validate(data=data).validation_results[0].reason_code == "UNKNOWN_REQUIREMENT"


@pytest.mark.parametrize("mutation", ["duplicate_task", "duplicate_step", "priority", "extra", "version", "missing"])
def test_plan_schema_rejected(mutation):
    data = plan()
    if mutation == "duplicate_task": data["tasks"].append(copy.deepcopy(data["tasks"][0]))
    if mutation == "duplicate_step": data["tasks"][0]["steps"] *= 2
    if mutation == "priority": data["tasks"][0]["priority"] = "high"
    if mutation == "extra": data["unmet_core_requirements"] = []
    if mutation == "version": data["plan_version"] = True
    if mutation == "missing": del data["tasks"][0]["title"]
    with pytest.raises(AppError) as exc:
        validate(data=data)
    assert exc.value.error.code == "PLAN_SCHEMA_INVALID"


def test_validation_deterministic_unchanged_original():
    data = plan()
    before = copy.deepcopy(data)
    outputs = [validate(data=data).model_dump() for _ in range(5)]
    assert all(value == outputs[0] for value in outputs)
    assert data == before


def test_mixed_and_empty_numeric_fields_rejected():
    from app.profiling.profiler import build_profile
    for raw in [b"value\n10\nbad\n", b"value,other\n,x\n,y\n"]:
        profile = build_profile(raw, ".csv", "mixed", "mixed.csv")
        t = task([step("aggregate", {"metrics": [{"function": "avg", "field": "field_0001", "alias": "value"}]})])
        assert validate([t], profile=profile).validation_results[0].feasibility == "F0"


def test_all_p0_f0_including_unknown_requirement_are_reported():
    for requirement_ids in [[], ["fake"]]:
        bad = task(tid="A02")
        bad["requirement_ids"] = requirement_ids
        output = validate([task(), bad])
        assert output.coverage_status == "partial"
        assert output.unmet_core_requirements[0].task_ids == ["A02"]
        assert output.validation_results[1].reason_code == "UNKNOWN_REQUIREMENT"


def test_unrelated_discarded_transform_does_not_invent_f1_need():
    output = result([step("derive", {"function": "extract_year", "field": "field_0004", "alias": "year"}),
        step("aggregate", {"metrics": [{"function": "count", "alias": "n"}]}, "S02")])
    assert output.feasibility == "F2"


def test_filter_on_derived_field_remains_f1_after_aggregation():
    output = result([step("derive", {"function": "extract_year", "field": "field_0004", "alias": "year"}),
        step("filter", {"conditions": [{"field": "year", "operator": "eq", "value": 2026}]}, "S02"),
        step("aggregate", {"metrics": [{"function": "count", "alias": "n"}]}, "S03")])
    assert output.feasibility == "F1"


def test_count_accepts_empty_column_and_validator_never_calls_handlers():
    from dataclasses import replace
    from app.profiling.profiler import build_profile
    profile = build_profile(b"blank,name\n,a\n,b\n", ".csv", "test", "test.csv")
    candidate = plan([task([step("aggregate", {"metrics": [{"function": "count", "field": "field_0001", "alias": "n"}]})])], profile)
    registry = CapabilityRegistry()
    def forbidden(*args):
        raise AssertionError("Validator must not execute any kernel")
    registry.operations = {name: replace(spec, handler=forbidden) for name, spec in registry.operations.items()}
    assert PlanValidator(registry).validate(candidate, profile).validation_results[0].feasibility == "F2"


def test_nonfinite_json_cannot_hide_in_unsupported_operation_params():
    data = plan([task([step("unsupported", {"value": float("nan")})])])
    with pytest.raises(AppError) as exc:
        validate(data=data)
    assert exc.value.error.code == "PLAN_SCHEMA_INVALID"


def test_display_name_never_accepted_as_field_id():
    output = result([step(params={"dimensions": ["城市"], "metrics": [{"function": "count", "alias": "n"}]})])
    assert output.reason_code == "MISSING_FIELD" and not output.executable


def test_task_aliases_are_local_and_cannot_cross_task_boundaries():
    output = validate([task(), task([step("sort", {"field": "job_count", "direction": "desc"})], tid="A02", priority="P1")])
    assert output.validation_results[1].reason_code == "MISSING_FIELD"
