from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import DataProfile
from app.main import create_app
from conftest import submit
from test_data_profiler import xlsx_bytes


def upload(client, content=b"id,amount\n001,10\n002,20\n002,20", name="data.csv", **options):
    return client.post("/api/v1/datasets", data=options, files={"file": (name, content)})


def test_upload_retrieve_reprofile_and_restart(tmp_path):
    settings = Settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = upload(client)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["row_count"] == 3 and data["duplicate_row_count"] == 1
        assert data["fields"][0]["samples"][0]["value"] == "001"
        path = f'/api/v1/datasets/{data["dataset_id"]}/versions/{data["dataset_version"]}/profile'
        assert client.get(path).json() == data
        rerun = client.post(f'/api/v1/datasets/{data["dataset_id"]}/profiles', json={})
        assert rerun.status_code == 200 and rerun.json() == data
        assert not client.get("/api/v1/sessions").json()  # No planner, report or LLM pipeline is invoked.
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(path).json() == data


def test_multisheet_explicit_selection_and_version_history(client):
    content = xlsx_bytes([["a"], [1]], [("第二表", [["b", "c"], [2, 3], [4, 5]])])
    missing_selection = upload(client, content, "data.xlsx")
    assert missing_selection.status_code == 422
    assert missing_selection.json()["error"]["code"] == "SHEET_SELECTION_REQUIRED"
    assert missing_selection.json()["error"]["details"]["available_sheets"] == ["数据", "第二表"]
    first = upload(client, content, "data.xlsx", sheet_name="数据").json()
    next_response = client.post(f'/api/v1/datasets/{first["dataset_id"]}/profiles', json={"sheet_name": "第二表"})
    assert next_response.status_code == 200, next_response.text
    second = next_response.json()
    assert first["dataset_id"] == second["dataset_id"]
    assert first["dataset_version"] != second["dataset_version"]
    assert (second["row_count"], second["column_count"]) == (2, 2)
    assert client.get(f'/api/v1/datasets/{first["dataset_id"]}/versions/{first["dataset_version"]}/profile').json() == first


def test_source_integrity_and_immutable_profile(client, app):
    data = upload(client, b"a\n1").json()
    path = app.state.profiler.files.directory / f'{data["dataset_id"]}.csv'
    path.write_bytes(b"a\n9")
    response = client.post(f'/api/v1/datasets/{data["dataset_id"]}/profiles', json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_INTEGRITY_ERROR"
    saved = client.get(f'/api/v1/datasets/{data["dataset_id"]}/versions/{data["dataset_version"]}/profile').json()
    assert saved["fields"][0]["samples"][0]["value"] == "1"


def test_invalid_inputs_leave_no_orphan_sources(client, app):
    for content, name, code in [(b"", "data.csv", "EMPTY_FILE"), (b"a,b\n1", "data.csv", "CSV_ROW_WIDTH_MISMATCH"),
                                (b"corrupt", "data.xlsx", "INVALID_XLSX"), (b"a\n1", "data.xls", "UNSUPPORTED_FILE")]:
        response = upload(client, content, name)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code
    assert not list(app.state.profiler.files.directory.iterdir())


def test_missing_dataset_versions_and_options_are_clear(client):
    assert client.get('/api/v1/datasets/missing/versions/missing/profile').json()["error"]["code"] == "PROFILE_NOT_FOUND"
    assert client.post('/api/v1/datasets/missing/profiles', json={}).json()["error"]["code"] == "DATASET_NOT_FOUND"
    assert upload(client, encoding="latin-1").json()["error"]["code"] == "VALIDATION_ERROR"
    assert upload(client, delimiter="invalid").json()["error"]["code"] == "VALIDATION_ERROR"


def test_workflow_uses_actual_profile_and_references_persisted_version(client):
    data = submit(client)
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["profile"]["row_count"] == 1  # Actual uploaded fixture, never the previous mock 12 rows.
    assert data["profile"]["column_count"] == 4
    assert data["profile"]["provenance"]["source"] == "uploaded"
    assert data["dataset_ref"]["dataset_id"] == data["file"]["id"]
    assert client.get(f'/api/v1/sessions/{data["id"]}/profile').json() == data["profile"]
    run = next(r for r in data["node_runs"] if r["node_name"] == "data_profiler")
    assert run["provenance"]["dataset_version"] == data["profile"]["dataset_version"]
    assert data["plans"][0]["provenance"]["source"] == "mock"


def test_failed_real_profile_never_falls_back_to_mock(client):
    response = client.post("/api/v1/sessions", data={"goal": "分析"}, files={"file": ("bad.csv", b"a,b\n1")})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "FAILED" and data["profile"] is None and not data["plans"]
    assert data["error"]["code"] == "CSV_ROW_WIDTH_MISMATCH"
    assert data["error"]["node_name"] == "data_profiler"
    assert next(r for r in data["node_runs"] if r["node_name"] == "data_profiler")["provenance"]["source"] == "uploaded"


def test_old_mock_sessions_remain_readable_but_not_real(client, app):
    data = submit(client)
    def legacy(state):
        state.profile = DataProfile(rows=12, columns=["mock"], quality_notes=[])
        state.dataset_ref = None
    app.state.repository.mutate(data["id"], legacy)
    restored = client.get(f'/api/v1/sessions/{data["id"]}').json()
    assert restored["profile"]["rows"] == 12
    assert client.get(f'/api/v1/sessions/{data["id"]}/profile').json()["error"]["code"] == "REAL_PROFILE_NOT_AVAILABLE"
