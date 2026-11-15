import io
from datetime import date, datetime, time, timedelta

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from pydantic import ValidationError

from app.domain.dataset_profile import DatasetProfile, ProfileOptions
from app.domain.errors import AppError
from app.profiling.parsers import ParserLimits
from app.profiling.profiler import build_profile


def xlsx_bytes(rows, extra_sheets=(), customize=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    for row in rows:
        sheet.append(row)
    for name, values in extra_sheets:
        other = workbook.create_sheet(name)
        for row in values:
            other.append(row)
    if customize:
        customize(sheet)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def profile(content, extension=".csv", options=None, **kwargs):
    return build_profile(content, extension, "test-dataset", "data" + extension, options, **kwargs)


def codes(result):
    return {issue.code for issue in result.quality_issues}


def test_csv_real_statistics_and_types():
    result = profile(b"name,amount,date,enabled,empty\nAlice,10,2026-01-01,true,\nBob,20.5,2026-01-02,false,\nAlice,10,2026-01-01,true,\n, ,not-date,false,\n")
    assert (result.row_count, result.column_count, result.total_cell_count) == (4, 5, 20)
    assert result.missing_cell_count == 6
    assert result.missing_cell_rate == .3
    assert result.duplicate_row_count == 1 and result.duplicate_row_rate == .25
    name, amount, dates, enabled, empty = result.fields
    assert (name.missing_count, name.unique_count) == (1, 2)
    assert (amount.physical_type, amount.logical_type) == ("string", "number")
    assert amount.missing_rate == .25 and amount.unique_count == 2
    assert [s.value for s in amount.samples] == ["10", "20.5"]
    assert amount.logical_type_counts == {"integer": 2, "number": 1}
    assert dates.logical_type == "mixed"
    assert enabled.logical_type == "boolean"
    assert (empty.physical_type, empty.logical_type, empty.unique_count, empty.samples) == ("null", "empty", 0, [])
    assert {"DUPLICATE_ROWS", "MIXED_LOGICAL_TYPES", "EMPTY_COLUMNS"} <= codes(result)
    assert result.provenance.source == "uploaded"
    assert DatasetProfile.model_validate_json(result.model_dump_json()) == result


def test_xlsx_native_types_duplicate_and_blank_headers():
    content = xlsx_bytes([
        ["重复", "重复", None, "flag", "when", "mixed"],
        [1, 1, "NA", True, date(2026, 1, 1), 1],
        [2, 2, None, False, date(2026, 1, 2), "bad"],
    ])
    result = profile(content, ".xlsx")
    assert result.sheet_name == "数据" and result.available_sheets == ["数据"]
    assert result.options.sheet_name == "数据"
    assert [f.field_id for f in result.fields] == [f"field_{i:04d}" for i in range(1, 7)]
    assert [f.original_name for f in result.fields[:3]] == ["重复", "重复", None]
    assert result.fields[0].logical_type == "integer"
    assert result.fields[3].physical_type == "boolean"
    assert result.fields[4].physical_type == "datetime"
    assert result.fields[5].physical_type == "mixed"
    assert result.fields[5].logical_type == "mixed"
    assert {"DUPLICATE_COLUMN_NAMES", "BLANK_COLUMN_NAMES", "IDENTICAL_COLUMNS",
            "MIXED_PHYSICAL_TYPES", "MIXED_LOGICAL_TYPES"} <= codes(result)
    assert result.fields[2].samples[0].value == "NA"


def test_duplicate_csv_headers_are_not_mangled():
    result = profile(b"a,a,, a \n1,2,3,4\n1,2,3,4\n")
    assert [f.original_name for f in result.fields] == ["a", "a", None, " a "]
    assert len({f.field_id for f in result.fields}) == 4
    assert result.duplicate_row_count == 1


@pytest.mark.parametrize("content,code", [
    (b"", "EMPTY_FILE"), (b" \n\t", "EMPTY_DATASET"), (b"a,b\n", "NO_DATA_ROWS"),
    (b",\n1,2", "EMPTY_HEADER"), (b"\na,b\n1,2", "EMPTY_HEADER"),
    (b"a,b\n1\n", "CSV_ROW_WIDTH_MISMATCH"), (b"a,b\n1,2,3", "CSV_ROW_WIDTH_MISMATCH"),
    (b'a,b\n"unclosed,1', "INVALID_CSV"), (b"a\n\x00", "INVALID_CSV"),
    (b"name\n\xff", "CSV_ENCODING_ERROR"),
])
def test_invalid_csv(content, code):
    with pytest.raises(AppError) as error:
        profile(content)
    assert error.value.error.code == code
    assert error.value.status == 422


@pytest.mark.parametrize("rows,code", [([], "EMPTY_DATASET"), ([["a"]], "NO_DATA_ROWS")])
def test_empty_xlsx(rows, code):
    with pytest.raises(AppError) as error:
        profile(xlsx_bytes(rows), ".xlsx")
    assert error.value.error.code == code


def test_corrupt_and_wrong_extension():
    with pytest.raises(AppError) as error:
        profile(b"not a zip", ".xlsx")
    assert error.value.error.code == "INVALID_XLSX"
    with pytest.raises(AppError) as error:
        profile(b"a\n1", ".xls")
    assert error.value.error.code == "UNSUPPORTED_FILE"


def test_multiple_sheets_require_explicit_selection_and_distinct_version():
    content = xlsx_bytes([["value"], [1], [2]], [("第二表", [["value"], [9]])])
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx")
    assert error.value.error.code == "SHEET_SELECTION_REQUIRED"
    assert "第二表" in error.value.error.message
    first = profile(content, ".xlsx", ProfileOptions(sheet_name="数据"))
    second = profile(content, ".xlsx", ProfileOptions(sheet_name="第二表"))
    assert first.row_count == 2 and second.row_count == 1
    assert first.content_sha256 == second.content_sha256
    assert first.dataset_version != second.dataset_version
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx", ProfileOptions(sheet_name="missing"))
    assert error.value.error.code == "SHEET_NOT_FOUND"


def test_determinism_versions_and_field_identity():
    data = b"a,a\n1,2\n"
    first = profile(data)
    assert first.model_dump_json() == profile(data).model_dump_json()
    other = profile(b"a,a\n2,3\n")
    assert first.dataset_version != other.dataset_version
    assert [f.field_id for f in first.fields] == [f.field_id for f in other.fields]
    csv_other_delimiter = profile(b"a;b\n1;2", options=ProfileOptions(delimiter=";"))
    csv_one_column = profile(b"a;b\n1;2")
    assert csv_other_delimiter.column_count == 2 and csv_one_column.column_count == 1
    assert csv_other_delimiter.dataset_version != csv_one_column.dataset_version
    excel = xlsx_bytes([["a"], [1]])
    assert profile(excel, ".xlsx") == profile(excel, ".xlsx", ProfileOptions(sheet_name="数据"))


def test_encoding_bom_quoted_fields_and_newlines():
    result = profile('\ufeff名称,说明\n甲,"一,二"\n乙,"多\n行"'.encode())
    assert result.row_count == 2
    assert result.fields[0].original_name == "名称"
    assert result.fields[1].samples[1].value == "多\n行"
    chinese = profile("姓名;金额\n张三;12".encode("gb18030"), options=ProfileOptions(encoding="gb18030", delimiter=";"))
    assert chinese.fields[0].samples[0].value == "张三"


def test_missing_definition_preserves_na_tokens_and_blank_rows():
    result = profile(b"value\nNA\nNULL\nnull\nNaN\nN/A\n \n\n")
    assert result.row_count == 7
    assert result.fields[0].missing_count == 2
    assert result.fields[0].unique_count == 5
    assert result.fields[0].logical_type == "text"
    issue = next(i for i in result.quality_issues if i.code == "EMPTY_ROWS")
    assert issue.affected_count == 2 and issue.example_row_numbers == [7, 8]
    assert result.duplicate_row_count == 0  # Whitespace and null remain distinct stored values.


@pytest.mark.parametrize("values,logical", [
    (["001", "002"], "text"), (["1", "-2", "+3"], "integer"),
    (["1", "2.5", "1e3"], "number"), (["true", "FALSE"], "boolean"),
    (["2026-01-01", "2026-01-02"], "date"),
    (["2026-01-01T12:30:00Z", "2026-01-01 14:30"], "datetime"),
    (["12:30:00", "23:01"], "time"),
    (["01/02/2026", "10%", "¥10", "2026-02-30"], "text"),
    (["1", "unknown"], "mixed"),
])
def test_conservative_logical_rules(values, logical):
    result = profile(("value\n" + "\n".join(values)).encode())
    assert result.fields[0].physical_type == "string"
    assert result.fields[0].logical_type == logical


def test_native_boolean_numeric_and_text_are_not_coalesced():
    result = profile(xlsx_bytes([["value"], [True], [1], ["1"]]), ".xlsx")
    field = result.fields[0]
    assert field.unique_count == 3 and result.duplicate_row_count == 0
    assert [type(s.value) for s in field.samples] == [bool, int, str]


def test_native_numeric_dates_and_time_samples_are_json_serializable():
    content = xlsx_bytes([["amount", "date", "time"], [1, datetime(2026, 1, 1, 12), time(12, 30)],
                          [2.5, datetime(2026, 1, 2, 13), time(13, 30)]])
    result = profile(content, ".xlsx")
    assert result.fields[0].physical_type == "float" and result.fields[0].logical_type == "number"
    assert result.fields[1].samples[0].value == "2026-01-01T12:00:00"
    assert result.fields[2].physical_type == "time"
    DatasetProfile.model_validate_json(result.model_dump_json())


def test_formula_errors_and_non_text_headers_are_not_silently_cleaned():
    result = profile(xlsx_bytes([[1, "result"], ["=1+1", "#DIV/0!"], [5, 3]]), ".xlsx")
    assert {"FORMULA_CELLS", "EXCEL_ERROR_CELLS", "NON_TEXT_HEADERS"} <= codes(result)
    assert result.fields[0].samples[0].value == "=1+1"
    assert result.fields[1].samples[0].value == "#DIV/0!"
    assert result.missing_cell_count == 0


def test_merged_cells_are_an_explicit_structure_error():
    content = xlsx_bytes([["a", "b"], [1, 2]], customize=lambda sheet: sheet.merge_cells("A1:B1"))
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx")
    assert error.value.error.code == "MERGED_CELLS_UNSUPPORTED"


def test_array_formula_preserves_actual_text():
    def formula(sheet):
        sheet["A2"] = ArrayFormula(ref="A2:A3", text="=ROW(A2:A3)")
    result = profile(xlsx_bytes([["value"], [None], [3]], customize=formula), ".xlsx")
    assert result.fields[0].samples[0].value == "=ROW(A2:A3)"
    assert "FORMULA_CELLS" in codes(result)


def test_unsupported_excel_values_return_clear_errors():
    content = xlsx_bytes([["duration"], [timedelta(hours=27)]])
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx")
    assert error.value.error.code == "UNSUPPORTED_CELL_TYPE"
    def formula(sheet):
        sheet["A2"] = DataTableFormula(ref="A2:A3")
    with pytest.raises(AppError) as error:
        profile(xlsx_bytes([["value"], [None], [3]], customize=formula), ".xlsx")
    assert error.value.error.code == "UNSUPPORTED_FORMULA"


def test_interior_empty_rows_and_trailing_formatted_range():
    def style(sheet):
        sheet["D10"].number_format = "0.00"
    result = profile(xlsx_bytes([["a", "b"], [1, 2], [None, None], [3, 4]], customize=style), ".xlsx")
    assert (result.row_count, result.column_count, result.missing_cell_count) == (3, 2, 2)
    assert {"EMPTY_ROWS", "TRAILING_EMPTY_RANGE"} <= codes(result)


def test_repeated_headers_and_bounded_samples():
    result = profile(b"a,b\n1,2\na,b\n3,4\n5,6\n7,8\n9,10\n11,12")
    assert "REPEATED_HEADER_ROWS" in codes(result)
    assert result.row_count == 7
    assert [s.value for s in result.fields[0].samples] == ["1", "a", "3", "5", "7"]
    long = profile(("text\n" + "x" * 200).encode()).fields[0].samples[0]
    assert long.truncated and len(long.value) == 120


@pytest.mark.parametrize("limits", [ParserLimits(max_rows=1), ParserLimits(max_columns=1), ParserLimits(max_cells=3)])
def test_dataset_size_limits(limits):
    with pytest.raises(AppError) as error:
        profile(b"a,b\n1,2\n3,4", limits=limits)
    assert error.value.error.code == "DATASET_LIMIT_EXCEEDED"


def test_xlsx_archive_limit_and_option_errors():
    content = xlsx_bytes([["a"], [1]])
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx", limits=ParserLimits(max_uncompressed_bytes=10))
    assert error.value.error.code == "XLSX_ARCHIVE_LIMIT"
    with pytest.raises(AppError) as error:
        profile(content, ".xlsx", options=ProfileOptions(delimiter=";"))
    assert error.value.error.code == "XLSX_CSV_OPTIONS"
    with pytest.raises(AppError) as error:
        profile(b"a\n1", options=ProfileOptions(sheet_name="数据"))
    assert error.value.error.code == "CSV_SHEET_NOT_SUPPORTED"


@pytest.mark.parametrize("change", [
    lambda d: d.update(row_count=99),
    lambda d: d.update(missing_cell_count=99),
    lambda d: d.update(duplicate_row_count=99),
    lambda d: d["fields"][0].update(unique_count=99),
    lambda d: d["fields"][0].update(missing_rate=.9),
    lambda d: d["fields"][0].update(field_id="field_0002"),
    lambda d: d["fields"][0].update(physical_type_counts={"string": 99}),
    lambda d: d["fields"][0].update(physical_type="float"),
    lambda d: d["fields"][0].update(logical_type="boolean"),
    lambda d: d["provenance"].update(source="mock"),
    lambda d: d["provenance"].update(dataset_version="a" * 64),
])
def test_contract_rejects_inconsistent_statistics(change):
    data = profile(b"a,b\n1,2\n3,4").model_dump()
    change(data)
    with pytest.raises(ValidationError):
        DatasetProfile.model_validate(data)
