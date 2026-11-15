import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.config import Settings
from app.domain.dataset_profile import ProfileOptions
from app.domain.enums import SessionStatus as S
from app.domain.execution import ExecutionResultV1
from app.domain.intent import ParsedIntent
from app.main import create_app
from app.reporting.contracts import prepare
from engine_fixtures import approve, execute, upload
from intent_fixtures import intent_payload
from planning_fixtures import CSV, step, task


def aggregate(function="sum", alias="value", field="field_0003"):
    return step("aggregate", {"metrics": [{"function": function, "field": field, "alias": alias}]})


def chain():
    return [step("filter", {"conditions": [{"field": "field_0003", "operator": "gte", "value": 25}]}),
        step(sid="S02"), step("sort", {"field": "job_count", "direction": "desc"}, "S03"),
        step("top_n", {"field": "job_count", "direction": "desc", "n": 1}, "S04")]


def result(client, request):
    response = execute(client, request)
    assert response.status_code == 200, response.text
    return response.json()


def error(client, request, code):
    response = execute(client, request)
    assert response.status_code in {404, 409, 422}, response.text
    assert response.json()["error"]["code"] == code, response.text
    return response


def test_uploaded_chain_matches_independent_pandas(client, app, provider):
    profile = upload(client)
    state, request = approve(app, profile, [task(chain())])
    data = result(client, request)
    # Independent reference: column names from original file, no Engine kernels.
    frame = pd.read_csv(io.BytesIO(CSV))
    baseline = (frame.loc[frame["薪资"] >= 25].groupby("城市", sort=False).size()
        .rename("job_count").reset_index().sort_values("job_count", ascending=False, kind="stable").head(1))
    expected = baseline.rename(columns={"城市": "field_0001"}).to_dict("records")
    output = data["tasks"][0]
    assert output["result"]["rows"] == expected
    assert output["row_count"] == 1 and output["effective_row_count"] == 3
    assert [(s["input_row_count"], s["output_row_count"]) for s in output["execution_metadata"]["steps"]] == [(3,3), (3,2), (2,2), (2,1)]
    assert all(s["duration_ms"] >= 0 and s["status"] == "success" for s in output["execution_metadata"]["steps"])
    assert data["source"] == "engine" and data["provenance"]["source"] == "uploaded"
    assert data["dataset_version"] == profile.dataset_version
    assert provider.requests == []  # No LLM is needed for loading, validating or computing.
    assert app.state.repository.get(state.id).status == S.COMPLETED
    assert app.state.repository.get(state.id).data_source == "uploaded"
    assert app.state.executions.get(data["execution_id"]).model_dump(mode="json") == data
    prepare(state.engine_approval.intent, state.engine_approval.validated_plan,
            ExecutionResultV1.model_validate(data), profile, app.state.capability_registry)


@pytest.mark.parametrize("function", ["count", "sum", "avg", "median", "min", "max", "distinct_count"])
def test_numeric_aggregates_match_independent_pandas(client, app, function):
    source = b"city,n\na,10\nb,20\na,\nc,30\n"
    profile = upload(client, source)
    state, request = approve(app, profile, [task([aggregate(function, field="field_0002")])])
    output = result(client, request)["tasks"][0]
    series = pd.read_csv(io.BytesIO(source))["n"]
    expected = {"count": series.count, "sum": series.sum, "avg": series.mean, "median": series.median,
                "min": series.min, "max": series.max, "distinct_count": series.nunique}[function]()
    assert output["result"]["rows"] == [{"value": expected}]
    assert output["valid_sample_count"] == 3 and output["effective_row_count"] == 4
    assert output["execution_metadata"]["metric_valid_counts"] == {"value": 3}


@pytest.mark.parametrize("function,attribute", [("extract_year", "year"), ("extract_month", "month")])
def test_xlsx_selected_sheet_header_date_derive(client, app, function, attribute):
    workbook = Workbook()
    workbook.active.title = "ignored"
    workbook.active.append(["unused"])
    sheet = workbook.create_sheet("招聘")
    sheet.append(["说明", None])
    sheet.append(["日期", "金额"])
    from datetime import datetime
    sheet.append([datetime(2025,12,1), 10])
    sheet.append([datetime(2026,1,2), 20])
    sheet.append([datetime(2026,1,3), 30])
    content = io.BytesIO(); workbook.save(content)
    profile = upload(client, content.getvalue(), "dates.xlsx", sheet_name="招聘", header_row=2)
    steps = [step("derive", {"function": function, "field": "field_0001", "alias": "period"}),
        step("group_aggregate", {"dimensions": ["period"], "metrics": [{"function": "sum", "field": "field_0002", "alias": "total"}]}, "S02")]
    _, request = approve(app, profile, [task(steps)])
    data = result(client, request)
    independent = pd.read_excel(io.BytesIO(content.getvalue()), sheet_name="招聘", header=1)
    independent["period"] = getattr(pd.to_datetime(independent["日期"]).dt, attribute)
    expected = independent.groupby("period", sort=False)["金额"].sum().rename("total").reset_index().to_dict("records")
    assert data["tasks"][0]["result"]["rows"] == expected
    assert app.state.repository.get(request.session_id).engine_approval.validated_plan.validation_results[0].feasibility == "F1"


def test_exact_old_profile_options_not_latest(client, app):
    profile = upload(client, b"title,extra\ncity,n\na,10\nb,20\n", header_row=2)
    other = client.post(f"/api/v1/datasets/{profile.dataset_id}/profiles", json=ProfileOptions(header_row=1).model_dump())
    assert other.status_code == 200 and other.json()["dataset_version"] != profile.dataset_version
    _, request = approve(app, profile, [task([aggregate(field="field_0002")])])
    assert result(client, request)["tasks"][0]["result"]["rows"] == [{"value": 30}]


@pytest.mark.parametrize("mutation,code", [
    (lambda s: setattr(s, "engine_approval", None), "V1_APPROVAL_REQUIRED"),
    (lambda s: setattr(s, "status", S.AWAITING_APPROVAL), "V1_APPROVAL_REQUIRED"),
    (lambda s: setattr(s.engine_approval, "status", "revoked"), "APPROVAL_REVOKED"),
    (lambda s: setattr(s, "current_plan_version", 2), "PLAN_VERSION_MISMATCH"),
    (lambda s: setattr(s, "approved_plan_version", 2), "PLAN_VERSION_MISMATCH"),
    (lambda s: setattr(s.dataset_ref, "dataset_version", "f" * 64), "DATASET_VERSION_MISMATCH"),
    (lambda s: setattr(s.engine_approval.validated_plan, "registry_version", "old"), "PLAN_VALIDATION_STALE"),
    (lambda s: s.engine_approval.validated_plan.executable_task_ids.clear(), "PLAN_VALIDATION_STALE"),
])
def test_approval_gates(client, app, mutation, code):
    state, request = approve(app, upload(client))
    app.state.repository.mutate(state.id, mutation)
    error(client, request, code)
    assert app.state.executions.running() == []
    assert app.state.repository.get(state.id).engine_execution_ids == []


@pytest.mark.parametrize("key,value", [("plan_id", "other"), ("plan_version", 2)])
def test_request_does_not_fall_back_to_approved_version(client, app, key, value):
    _, request = approve(app, upload(client))
    setattr(request, key, value)
    error(client, request, "PLAN_VERSION_MISMATCH")


def test_blocking_uncertainties_and_constraints(client, app):
    profile = upload(client)
    for action, resolved, expected in [("clarify", False, "BLOCKING_UNCERTAINTY"), ("defer", False, "BLOCKING_UNCERTAINTY"), ("defer", True, None)]:
        payload = intent_payload(action="clarify") if action == "clarify" else intent_payload()
        if action == "defer":
            payload["uncertainties"] = [{"id": "scope", "description": "范围待确认", "impact": "影响统计范围", "action": "defer", "resolve_at": "before_execution"}]
        intent = ParsedIntent.model_validate(payload)
        _, request = approve(app, profile, intent=intent, resolved_uncertainty_ids=["scope"] if resolved else [])
        if expected: error(client, request, expected)
        else: assert result(client, request)["execution_status"] == "success"
    payload = intent_payload()
    payload["constraints"]["filters"] = [{"raw_text": "只看上海", "validation_status": "unverified"}]
    _, request = approve(app, profile, intent=ParsedIntent.model_validate(payload))
    error(client, request, "UNCONFIRMED_CONSTRAINTS")


@pytest.mark.parametrize("extra", [{"approved": True}, {"path": "/tmp/arbitrary.csv"}, {"engine_approval": {}}, {"plan": {}}])
def test_client_cannot_supply_approval_or_paths(client, app, extra):
    _, request = approve(app, upload(client))
    assert client.post("/api/v1/executions", json=request.model_dump() | extra).status_code == 422


def test_unsupported_tasks_never_execute(client, app):
    profile = upload(client)
    blocked = task([step("python", {"code": "raise Exception('never run')"})])
    _, request = approve(app, profile, [blocked])
    error(client, request, "NO_EXECUTABLE_TASKS")
    state, request = approve(app, profile, [blocked, task(tid="A02")])
    data = result(client, request)
    assert data["execution_status"] == "partial_success"
    assert data["tasks"][0]["status"] == "skipped"
    assert data["tasks"][0]["error"] == {"code": "UNSUPPORTED_OPERATION", "message": "当前系统未实现该操作。", "task_id": "A01", "step_id": "S01"}
    assert data["tasks"][1]["status"] == "success"


def test_runtime_error_isolated_and_input_views_independent(client, app, monkeypatch):
    profile = upload(client)
    operations = app.state.capability_registry.operations
    original = operations["aggregate"]
    def fail(frame, params, types):
        frame.iloc[0,0] = "changed only this copy"
        raise ValueError("private runtime details")
    monkeypatch.setitem(operations, "aggregate", replace(original, handler=fail))
    _, request = approve(app, profile, [task([aggregate()]), task(tid="A02")])
    data = result(client, request)
    assert data["execution_status"] == "partial_success"
    failed, good = data["tasks"]
    assert failed["error"]["task_id"] == "A01" and failed["error"]["step_id"] == "S01"
    assert failed["error"]["code"] == "OPERATION_DATA_ERROR"
    assert failed["execution_metadata"]["steps"][0]["status"] == "failed"
    assert "private runtime details" not in json.dumps(data)
    assert good["result"]["rows"] == [{"field_0001": "上海", "job_count": 2}, {"field_0001": "北京", "job_count": 1}]


@pytest.mark.parametrize("group", [False, True])
def test_empty_result_is_success(client, app, group):
    steps = [step("filter", {"conditions": [{"field": "field_0003", "operator": "gt", "value": 9999}]}),
        step(sid="S02") if group else step("aggregate", {"metrics": [{"function": "count", "alias": "n"}, {"function": "sum", "field": "field_0003", "alias": "total"}]}, "S02")]
    state, request = approve(app, upload(client), [task(steps)])
    data = result(client, request)
    assert data["execution_status"] == "success"
    assert data["tasks"][0]["result"]["rows"] == ([] if group else [{"n": 0, "total": None}])
    prepare(state.engine_approval.intent, state.engine_approval.validated_plan,
            ExecutionResultV1.model_validate(data), state.profile, app.state.capability_registry)


@pytest.mark.parametrize("mode,code", [("missing", "SOURCE_FILE_NOT_FOUND"), ("tampered", "DATASET_INTEGRITY_ERROR")])
def test_missing_or_modified_file_rejected(client, app, tmp_path, mode, code):
    profile = upload(client)
    state, request = approve(app, profile)
    source = tmp_path / "uploads" / (profile.dataset_id + ".csv")
    if mode == "missing": source.unlink()
    else: source.write_bytes(CSV.replace(b"25", b"99"))
    error(client, request, code)
    assert app.state.repository.get(state.id).engine_execution_ids == []


def test_plan_revalidation_prevents_tampered_approved_steps(client, app):
    state, request = approve(app, upload(client))
    def change(state):
        state.engine_approval.validated_plan.plan.tasks[0].steps[0].params["dimensions"] = ["imaginary"]
    app.state.repository.mutate(state.id, change)
    error(client, request, "PLAN_VALIDATION_STALE")


def test_idempotency_and_read_after_restart(client, app, tmp_path, monkeypatch):
    _, request = approve(app, upload(client))
    first = result(client, request)
    def no_repeat(*args): raise AssertionError("must not load or compute twice")
    monkeypatch.setattr(app.state.analysis_engine.loader, "load", no_repeat)
    assert result(client, request) == first
    assert client.get(f"/api/v1/executions/{first['execution_id']}").json() == first
    request.plan_version = 2
    error(client, request, "EXECUTION_REQUEST_CONFLICT")
    restarted = create_app(Settings(tmp_path))
    with TestClient(restarted) as other:
        assert other.get(f"/api/v1/executions/{first['execution_id']}").json() == first
        request.plan_version = 1
        assert result(other, request) == first
    assert app.state.repository.get(request.session_id).engine_execution_ids == [first["execution_id"]]


def test_concurrent_duplicate_request_claimed_once(client, app, monkeypatch):
    _, request = approve(app, upload(client))
    entered, release = Event(), Event()
    original = app.state.analysis_engine.runner.run
    count = []
    def held(*args):
        count.append(True); entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(app.state.analysis_engine.runner, "run", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(execute, client, request)
        try:
            assert entered.wait(5)
            response = error(client, request, "EXECUTION_IN_PROGRESS")
            assert response.json()["error"]["details"]["execution_id"]
            other = request.model_copy(update={"execution_request_id": "other_request"})
            error(client, other, "V1_APPROVAL_REQUIRED")
        finally: release.set()
        assert future.result().status_code == 200
    assert count == [True]


def test_profile_revision_changed_during_load_refuses_claim(client, app, monkeypatch):
    state, request = approve(app, upload(client))
    original = app.state.analysis_engine.loader.load
    def load(*args):
        loaded = original(*args)
        app.state.repository.mutate(state.id, lambda s: s.messages.clear())
        return loaded
    monkeypatch.setattr(app.state.analysis_engine.loader, "load", load)
    error(client, request, "APPROVAL_CHANGED")
    assert app.state.repository.get(state.id).engine_execution_ids == []


def test_full_results_are_not_preview_and_paginate(client, app):
    profile = upload(client, ("city,n\n" + "".join(f"city{i},{i}\n" for i in range(5103))).encode())
    _, request = approve(app, profile)
    data = result(client, request)
    output = data["tasks"][0]
    assert output["row_count"] == 5103
    assert len(output["result"]["rows"]) == 100 and output["result"]["truncated"]
    url = f"/api/v1/executions/{data['execution_id']}"
    assert client.get(url + "?view=complete").status_code == 413
    rows = []
    for offset in [0, 2000, 4000]:
        response = client.get(url + f"/results/{output['result_id']}?offset={offset}&limit=2000")
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total_result_rows"] == 5103 and page["row_offset"] == offset
        rows.extend(page["rows"])
    assert len(rows) == 5103 and rows[-1] == {"field_0001": "city5102", "job_count": 1}
    assert client.get(url + "/results/result_other").status_code == 404


def test_complete_result_can_be_passed_to_existing_report_contract(client, app):
    profile = upload(client, ("city,n\n" + "".join(f"city{i},{i}\n" for i in range(120))).encode())
    state, request = approve(app, profile)
    data = result(client, request)
    url = f"/api/v1/executions/{data['execution_id']}?view=complete"
    complete = client.get(url)
    assert complete.status_code == 200, complete.text
    full = ExecutionResultV1.model_validate(complete.json())
    assert full.result_view == "complete" and len(full.tasks[0].result.rows) == 120
    assert not full.tasks[0].result.truncated
    prepare(state.engine_approval.intent, state.engine_approval.validated_plan, full, profile, app.state.capability_registry)


def test_interrupted_execution_retains_saved_results_and_never_reruns(client, app, tmp_path):
    profile = upload(client)
    state, request = approve(app, profile, [task(), task(tid="A02")])
    engine = app.state.analysis_engine
    loaded = engine.loader.load(profile.dataset_id, profile.dataset_version)
    claim = app.state.executions.claim(request, state.revision, engine.check_approval)
    output, columns, rows, _ = engine.runner.run(state.engine_approval.validated_plan.plan.tasks[0], loaded, 256*1024, 100000)
    app.state.executions.save_task(claim["execution_id"], output, columns, rows)
    restarted = create_app(Settings(tmp_path))
    with TestClient(restarted) as other:
        data = result(other, request)
        assert data["execution_status"] == "partial_success"
        assert [t["status"] for t in data["tasks"]] == ["success", "skipped"]
        assert data["tasks"][1]["error"]["code"] == "EXECUTION_INTERRUPTED"
        assert data["tasks"][0]["result"]["rows"] == output.result.rows
        assert data["execution_id"] == claim["execution_id"]
        assert other.get(f"/api/v1/executions/{data['execution_id']}?view=complete").status_code == 200


def test_legacy_mock_paths_cannot_execute_or_reapprove_v1_snapshot(client, app):
    state, _ = approve(app, upload(client))
    response = client.post(f"/api/v1/sessions/{state.id}/execute", json={"expected_revision": state.revision, "plan_version": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "V1_EXECUTION_ENDPOINT_REQUIRED"


def test_all_failed_tasks_produce_failed_execution(client, app, monkeypatch):
    def fail(*args): raise ValueError("fault")
    operations = app.state.capability_registry.operations
    monkeypatch.setitem(operations, "aggregate", replace(operations["aggregate"], handler=fail))
    state, request = approve(app, upload(client), [task([aggregate()])])
    data = result(client, request)
    assert data["execution_status"] == "failed" and data["tasks"][0]["result"] is None
    assert data["errors"][0]["task_id"] == "A01"
    assert app.state.repository.get(state.id).status == S.FAILED
    assert result(client, request) == data


def test_partial_task_results_keep_all_rows_and_per_metric_sample_sizes(client, app):
    profile = upload(client, b"city,a,b\nx,10,1\ny,20,\nz,,\n")
    metrics = [{"function": "avg", "field": "field_0002", "alias": "a_avg"},
               {"function": "avg", "field": "field_0003", "alias": "b_avg"}]
    _, request = approve(app, profile, [task([step("aggregate", {"metrics": metrics})])])
    data = result(client, request)["tasks"][0]
    assert data["result"]["rows"] == [{"a_avg": 15.0, "b_avg": 1.0}]
    assert data["valid_sample_count"] is None
    assert data["execution_metadata"]["metric_valid_counts"] == {"a_avg": 2, "b_avg": 1}


def test_exact_integer_sum_does_not_wrap_int64(client, app):
    profile = upload(client, b"city,n\na,8000000000000000000\nb,8000000000000000000\n")
    _, request = approve(app, profile, [task([aggregate(field="field_0002")])])
    assert result(client, request)["tasks"][0]["result"]["rows"] == [{"value": 16000000000000000000}]


def test_large_text_preserved_in_full_results(client, app):
    text = "x" * 300_000
    profile = upload(client, ("city,n\n" + text + ",1\n").encode())
    _, request = approve(app, profile, [task([step("filter", {"conditions": [{"field": "field_0002", "operator": "gt", "value": 0}]})])])
    data = result(client, request)
    output = data["tasks"][0]
    assert output["row_count"] == 1 and output["result"]["rows"] == []
    assert output["result"]["truncated"]
    full = client.get(f"/api/v1/executions/{data['execution_id']}?view=complete").json()
    assert full["tasks"][0]["result"]["rows"][0]["field_0001"] == text


def test_execution_approval_snapshot_survives_later_session_edits(client, app):
    state, request = approve(app, upload(client))
    data = result(client, request)
    app.state.repository.mutate(state.id, lambda s: setattr(s, "engine_approval", None))
    saved = app.state.executions.approved_snapshot(data["execution_id"])
    assert saved == state.engine_approval
    assert result(client, request) == data


def test_workflow_node_reuses_same_service_and_error_contract(client, app):
    import asyncio
    from app.domain.node_contracts import NodeInput
    from app.nodes.engine_v1 import AnalysisEngineNode
    state, request = approve(app, upload(client))
    node = AnalysisEngineNode(app.state.analysis_engine)
    output = asyncio.run(node.run(NodeInput(session_id=state.id, run_id="run_engine", payload=request)))
    assert output.status == "success" and output.data.source == "engine"
    assert output.provenance.source == "uploaded"
    request.execution_request_id = "another_request"
    failed = asyncio.run(node.run(NodeInput(session_id=state.id, run_id="run_error", payload=request)))
    assert failed.status == "error" and failed.error.code == "V1_APPROVAL_REQUIRED"


def test_large_nullable_integer_refused_instead_of_rounded(client, app):
    profile = upload(client, b"city,n\na,8000000000000000001\nb,\n")
    steps = [step("group_aggregate", {"dimensions": ["field_0001"], "metrics": [{"function": "sum", "field": "field_0002", "alias": "total"}]})]
    _, request = approve(app, profile, [task(steps)])
    data = result(client, request)
    assert data["execution_status"] == "failed"
    assert data["tasks"][0]["error"]["code"] == "NUMERIC_PRECISION_LOSS"
    assert data["tasks"][0]["result"] is None


def test_wide_dataset_can_preserve_source_and_derived_columns(client, app):
    source = (",".join(["date"] + [f"c{i}" for i in range(255)]) + "\n" +
              ",".join(["2026-01-02"] + ["1"] * 255) + "\n").encode()
    profile = upload(client, source)
    steps = [step("derive", {"field": "field_0001", "function": "extract_year", "alias": "year"})]
    _, request = approve(app, profile, [task(steps)])
    data = result(client, request)
    assert data["execution_status"] == "success"
    assert len(data["tasks"][0]["result"]["columns"]) == 257
    assert data["tasks"][0]["result"]["rows"][0]["year"] == 2026


@pytest.mark.filterwarnings("ignore:overflow encountered in reduce:RuntimeWarning")
def test_overflow_cannot_be_hidden_by_later_filter_and_count(client, app):
    profile = upload(client, b"city,n\na,1e308\nb,1e308\n")
    steps = [aggregate(field="field_0002"),
        step("filter", {"conditions": [{"field": "value", "operator": "gt", "value": 0}]}, "S02"),
        step("aggregate", {"metrics": [{"function": "count", "alias": "n"}]}, "S03")]
    _, request = approve(app, profile, [task(steps)])
    data = result(client, request)
    assert data["execution_status"] == "failed"
    assert data["tasks"][0]["error"]["code"] == "NON_FINITE_RESULT"
    assert data["tasks"][0]["error"]["step_id"] == "S01"
    assert len(data["tasks"][0]["execution_metadata"]["steps"]) == 1


def test_legacy_review_cannot_modify_approved_v1_plan(client, app):
    state, _ = approve(app, upload(client))
    for route, extra in [("approvals", {}), ("plan-revisions", {"instruction": "增加地区对比"})]:
        response = client.post(f"/api/v1/sessions/{state.id}/{route}", json={"expected_revision": state.revision, "plan_version": 1} | extra)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "V1_REVIEW_REQUIRED"
    assert app.state.repository.get(state.id) == state
