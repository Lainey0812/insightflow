import pytest
from pydantic import ValidationError

from app.domain.dataset_profile import DatasetProfile, ProfileOptions
from app.domain.errors import AppError
from test_data_profiler import profile, xlsx_bytes


def test_csv_header_row_skips_variable_width_preamble_and_keeps_source_record_numbers():
    content = b'"title\ncontinued"\nnotes,not,data\na,b\n1,2\n1,2\n'
    result = profile(content, options=ProfileOptions(header_row=3))
    assert result.row_count == 2 and result.column_count == 2
    assert [f.original_name for f in result.fields] == ["a", "b"]
    assert result.missing_cell_count == 0 and result.duplicate_row_count == 1
    duplicate = next(i for i in result.quality_issues if i.code == "DUPLICATE_ROWS")
    assert duplicate.example_row_numbers == [5]  # Logical record 5, physical text line 6.
    assert result.options.header_row == 3


def test_xlsx_header_row_excludes_title_merges_and_formulas_and_preserves_row_numbers():
    def title(sheet):
        sheet.merge_cells("A1:D1")
    content = xlsx_bytes([["title"], ["=100/0"], ["a", "b"], [1, 2], [1, 2], [None, None], [3, 4]], customize=title)
    result = profile(content, ".xlsx", ProfileOptions(header_row=3))
    assert result.row_count == 4 and result.column_count == 2
    assert result.missing_cell_count == 2 and result.duplicate_row_count == 1
    issues = {i.code: i for i in result.quality_issues}
    assert issues["DUPLICATE_ROWS"].example_row_numbers == [5]
    assert issues["EMPTY_ROWS"].example_row_numbers == [6]
    assert "FORMULA_CELLS" not in issues


def test_xlsx_selected_region_formula_positions_stay_in_original_coordinates():
    result = profile(xlsx_bytes([["title"], ["value"], ["=1+1"], [2]]), ".xlsx", ProfileOptions(header_row=2))
    issue = next(i for i in result.quality_issues if i.code == "FORMULA_CELLS")
    assert issue.example_row_numbers == [3]
    assert result.fields[0].samples[0].value == "=1+1"
    DatasetProfile.model_validate_json(result.model_dump_json())


@pytest.mark.parametrize("merge", ["A1:A2", "A2:B2", "A3:B3"])
def test_merges_touching_selected_header_or_data_are_still_rejected(merge):
    content = xlsx_bytes([["title"], ["a", "b"], [1, 2]], customize=lambda s: s.merge_cells(merge))
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx", ProfileOptions(header_row=2))
    assert error.value.error.code == "MERGED_CELLS_UNSUPPORTED"


@pytest.mark.parametrize("extension,content,header_row,code", [
    (".csv", b"a\n1", 3, "HEADER_ROW_OUT_OF_RANGE"),
    (".xlsx", xlsx_bytes([["a"], [1]]), 3, "HEADER_ROW_OUT_OF_RANGE"),
    (".csv", b"title\n\n1,2", 2, "EMPTY_HEADER"),
    (".xlsx", xlsx_bytes([["title"], [None], [1]]), 2, "EMPTY_HEADER"),
    (".csv", b"title\na", 2, "NO_DATA_ROWS"),
    (".xlsx", xlsx_bytes([["title"], ["a"]]), 2, "NO_DATA_ROWS"),
])
def test_invalid_header_selection(extension, content, header_row, code):
    with pytest.raises(AppError) as error:
        profile(content, extension, ProfileOptions(header_row=header_row))
    assert error.value.error.code == code


@pytest.mark.parametrize("value", [0, -1, 100002, 1.5, "2", True])
def test_profile_options_require_bounded_integer(value):
    with pytest.raises(ValidationError):
        ProfileOptions(header_row=value)


def test_default_and_explicit_first_header_match_and_other_header_changes_version():
    content = b"id,value\na,b\n1,2"
    first = profile(content)
    assert first == profile(content, options=ProfileOptions(header_row=1))
    second = profile(content, options=ProfileOptions(header_row=2))
    assert first.dataset_version != second.dataset_version
    assert first.content_sha256 == second.content_sha256
    assert second.row_count == 1
    assert profile(content, options=ProfileOptions(header_row=2)) == second


def test_legacy_profile_without_header_option_still_loads():
    payload = profile(b"a\n1").model_dump()
    payload["options"].pop("header_row")
    payload["profiler_version"] = "1.0.0"
    loaded = DatasetProfile.model_validate(payload)
    assert loaded.options.header_row == 1
    assert loaded.profiler_version == "1.0.0"


def test_header_option_flows_through_upload_reprofile_version_read_and_workflow(client):
    content = b"title,notes\na,b\n1,2\n3,4"
    first = client.post("/api/v1/datasets", data={"header_row": "2"}, files={"file": ("data.csv", content)})
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["options"]["header_row"] == 2 and data["row_count"] == 2
    path = f'/api/v1/datasets/{data["dataset_id"]}/versions/{data["dataset_version"]}/profile'
    assert client.get(path).json() == data
    revised = client.post(f'/api/v1/datasets/{data["dataset_id"]}/profiles', json={"header_row": 1})
    assert revised.status_code == 200, revised.text
    assert revised.json()["dataset_version"] != data["dataset_version"]
    assert revised.json()["row_count"] == 3
    assert client.get(path).json() == data
    session = client.post("/api/v1/sessions", data={"goal": "test", "header_row": "2"}, files={"file": ("data.csv", content)})
    assert session.status_code == 201, session.text
    state = session.json()
    assert state["status"] == "AWAITING_APPROVAL"
    assert state["profile"]["options"]["header_row"] == 2
    assert state["profile"]["row_count"] == 2


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "100002", "no"])
@pytest.mark.parametrize("endpoint", ["/api/v1/datasets", "/api/v1/sessions"])
def test_upload_endpoints_validate_header_before_saving_files(client, app, endpoint, value):
    response = client.post(endpoint, data={"goal": "test", "header_row": value}, files={"file": ("data.csv", b"a\n1")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not list(app.state.profiler.files.directory.iterdir())
