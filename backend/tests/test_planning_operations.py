import io

import pandas as pd
import pytest

from app.planning.capabilities import CapabilityRegistry
from app.planning.operations import normalize
from app.profiling.parsers import parse_table
from app.domain.dataset_profile import ProfileOptions
from planning_fixtures import CSV, recruiting_profile, step


def run(steps, raw=CSV):
    from app.profiling.profiler import build_profile
    from app.planning.capabilities import FieldState
    profile = build_profile(raw, ".csv", "test", "test.csv")
    table = parse_table(raw, ".csv", ProfileOptions())
    types = {f.field_id: f.logical_type for f in profile.fields}
    fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in profile.fields}
    frame = normalize(pd.DataFrame(table.rows, columns=list(types)), types)
    registry = CapabilityRegistry()
    reserved = set(fields)
    for s in steps:
        spec = registry.operations[s["operation"]]
        params = spec.params_model.model_validate(s["params"])
        output = registry.propagate(s["operation"], params, fields, reserved)
        frame = spec.handler(frame, params, {key: state.kind for key, state in fields.items()})
        assert list(frame.columns) == list(output)
        fields = output
        reserved.update(fields)
    return frame.reset_index(drop=True)


def test_actual_filter_group_sort_top_n_and_input_not_modified():
    original = CSV
    output = run([step("filter", {"conditions": [{"field": "field_0003", "operator": "gte", "value": 25}]}), step(),
        step("sort", {"field": "job_count", "direction": "desc"}),
        step("top_n", {"field": "job_count", "direction": "desc", "n": 1})])
    assert output.to_dict("records") == [{"field_0001": "上海", "job_count": 2}]
    assert CSV == original


@pytest.mark.parametrize("function,expected", [("count", 3), ("sum", 85), ("avg", 85 / 3), ("median", 25),
                                                ("min", 25), ("max", 35), ("distinct_count", 2)])
def test_actual_aggregate(function, expected):
    output = run([step("aggregate", {"metrics": [{"function": function, "field": "field_0003", "alias": "value"}]})])
    assert output.loc[0, "value"] == pytest.approx(expected)


@pytest.mark.parametrize("function,expected", [("extract_year", [2026, 2026, 2025]), ("extract_month", [1, 2, 12])])
def test_actual_date_transform(function, expected):
    output = run([step("derive", {"function": function, "field": "field_0004", "alias": "period"})])
    assert list(output.period) == expected


def test_actual_transformed_group():
    output = run([step("derive", {"function": "extract_year", "field": "field_0004", "alias": "year"}),
        step("group_aggregate", {"dimensions": ["year"], "metrics": [{"function": "count", "field": None, "alias": "n"}]})])
    assert output.to_dict("records") == [{"year": 2026, "n": 2}, {"year": 2025, "n": 1}]


@pytest.mark.parametrize("operator,value,expected", [("eq", 25, 2), ("ne", 25, 1), ("gt", 25, 1), ("gte", 25, 3),
    ("lt", 35, 2), ("lte", 25, 2), ("in", [25], 2), ("not_in", [25], 1), ("is_null", None, 0), ("not_null", None, 3)])
def test_filter_comparisons(operator, value, expected):
    assert len(run([step("filter", {"conditions": [{"field": "field_0003", "operator": operator, "value": value}]})])) == expected


def test_dates_and_empty_filter_results():
    output = run([step("filter", {"conditions": [{"field": "field_0004", "operator": "gte", "value": "2026-01-01"}]})])
    assert len(output) == 2
    output = run([step("filter", {"conditions": [{"field": "field_0003", "operator": "gt", "value": 100}]}),
        step("aggregate", {"metrics": [{"function": "sum", "field": "field_0003", "alias": "s"}, {"function": "count", "alias": "n"}]})])
    assert output.loc[0, "s"] is None and output.loc[0, "n"] == 0


def test_nulls_count_distinct_and_group():
    raw = b"category,value\na,10\na,\n,20\n"
    output = run([step("aggregate", {"metrics": [{"function": "count", "alias": "rows"},
        {"function": "count", "field": "field_0002", "alias": "present"},
        {"function": "distinct_count", "field": "field_0001", "alias": "unique"}]})], raw)
    assert output.to_dict("records") == [{"rows": 3, "present": 2, "unique": 1}]
    output = run([step("group_aggregate", {"dimensions": ["field_0001"], "metrics": [{"function": "sum", "field": "field_0002", "alias": "total"}]})], raw)
    assert len(output) == 2 and output.total.sum() == 30


def test_boolean_filter_and_topn_stable_ties():
    output = run([step("filter", {"conditions": [{"field": "field_0002", "operator": "eq", "value": True}]})], b"name,flag\na,true\nb,false\n")
    assert list(output.field_0001) == ["a"]
    output = run([step("top_n", {"field": "field_0003", "direction": "asc", "n": 2})])
    assert list(output.field_0001) == ["上海", "上海"]
