import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.domain.dataset_profile import ProfileOptions, QualityIssue
from app.domain.errors import AppError

Cell = str | int | float | bool | date | datetime | time | None
# Match the upload bound, rather than rejecting valid large text fields at csv's 128 KiB default.
csv.field_size_limit(10 * 1024 * 1024)


@dataclass(frozen=True)
class ParserLimits:
    max_bytes: int = 10 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 256
    max_cells: int = 2_000_000
    max_uncompressed_bytes: int = 50 * 1024 * 1024


@dataclass
class ParsedTable:
    headers: list[Cell]
    rows: list[list[Cell]]
    file_format: str
    sheet_name: str | None
    available_sheets: list[str]
    options: ProfileOptions
    issues: list[QualityIssue] = field(default_factory=list)


def invalid(code: str, message: str) -> AppError:
    return AppError(code, message, 422)


def check_dimensions(rows: int, columns: int, limits: ParserLimits) -> None:
    if columns > limits.max_columns or rows > limits.max_rows or rows * columns > limits.max_cells:
        raise invalid("DATASET_LIMIT_EXCEEDED", "表格超出画像上限：10 万行、256 列、200 万个数据单元格。")


def parse_csv(content: bytes, options: ProfileOptions, limits: ParserLimits) -> ParsedTable:
    if options.sheet_name is not None:
        raise invalid("CSV_SHEET_NOT_SUPPORTED", "CSV 不包含工作表，请不要指定 sheet_name。")
    try:
        text = content.decode(options.encoding)
    except UnicodeError:
        raise invalid("CSV_ENCODING_ERROR", "CSV 编码无法解码；默认使用 UTF-8，可显式指定 gb18030。") from None
    if "\x00" in text:
        raise invalid("INVALID_CSV", "CSV 含有空字节，可能不是有效的文本文件。")
    if not text.strip():
        raise invalid("EMPTY_DATASET", "文件不包含可读取的表格。")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=options.delimiter, strict=True)
        try:
            for _ in range(options.header_row):
                headers = next(reader)
        except StopIteration:
            raise invalid("HEADER_ROW_OUT_OF_RANGE", f"CSV 中不存在第 {options.header_row} 条表头记录。") from None
        if not headers or all(not value.strip() for value in headers):
            raise invalid("EMPTY_HEADER", "指定的表头行必须包含至少一个字段名称，不自动猜测或跳过表头。")
        width = len(headers)
        check_dimensions(0, width, limits)
        rows = []
        for row in reader:
            if not row:
                row = [None] * width  # Preserve an explicit blank record; never silently drop it.
            if len(row) != width:
                raise invalid("CSV_ROW_WIDTH_MISMATCH",
                              f"CSV 第 {reader.line_num} 行字段数为 {len(row)}，表头为 {width}；请检查分隔符和引号。")
            check_dimensions(len(rows) + 1, width, limits)
            rows.append(row)
    except csv.Error:
        raise invalid("INVALID_CSV", "CSV 结构无效、字段过长或引号不完整。") from None
    return ParsedTable(headers, rows, "csv", None, [], options)


def parse_xlsx(content: bytes, options: ProfileOptions, limits: ParserLimits) -> ParsedTable:
    if options.encoding != "utf-8-sig" or options.delimiter != ",":
        raise invalid("XLSX_CSV_OPTIONS", "XLSX 不支持 CSV 编码或分隔符选项。")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 10_000 or sum(e.file_size for e in entries) > limits.max_uncompressed_bytes:
                raise invalid("XLSX_ARCHIVE_LIMIT", "Excel 解压后的内容超出 50 MB 或条目数上限。")
            if "xl/workbook.xml" not in archive.namelist():
                raise invalid("INVALID_XLSX", "文件不是有效的 XLSX 工作簿。")
        workbook = load_workbook(io.BytesIO(content), read_only=False, data_only=False, keep_links=False)
    except AppError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError, TypeError, EOFError):
        raise invalid("INVALID_XLSX", "Excel 工作簿损坏、加密或格式不正确。") from None
    except Exception:
        # Includes malformed XML and unsupported OOXML. Parser details are not exposed.
        raise invalid("INVALID_XLSX", "无法读取 Excel 工作簿，请检查文件格式。") from None
    try:
        names = workbook.sheetnames
        if options.sheet_name is None:
            if len(names) != 1:
                raise AppError("SHEET_SELECTION_REQUIRED", "文件包含多个工作表，请使用 sheet_name 选择一个：" + "、".join(names),
                               422, details={"available_sheets": names})
            selected = names[0]
        else:
            selected = options.sheet_name
        if selected not in names:
            raise AppError("SHEET_NOT_FOUND", "指定的工作表不存在；可用工作表：" + "、".join(names),
                           422, details={"available_sheets": names})
        sheet = workbook[selected]
        if not hasattr(sheet, "iter_rows"):
            raise invalid("UNSUPPORTED_SHEET", "所选工作表不是可读取的数据表。")
        if options.header_row > sheet.max_row:
            raise invalid("HEADER_ROW_OUT_OF_RANGE", f"所选工作表不存在第 {options.header_row} 行。")
        if any(merged.max_row >= options.header_row for merged in sheet.merged_cells.ranges):
            raise invalid("MERGED_CELLS_UNSUPPORTED", "指定表头行或数据区包含合并单元格，无法确定矩形表格结构。")
        check_dimensions(max(sheet.max_row - options.header_row, 0), sheet.max_column, limits)
        matrix, formula_cells, error_cells = [], [], []
        for row in sheet.iter_rows(min_row=options.header_row):
            values = []
            for cell in row:
                value = cell.value
                if cell.data_type == "f" and not isinstance(value, str):
                    # openpyxl represents array formulas as objects; use actual formula text only.
                    value = getattr(value, "text", None)
                    if not isinstance(value, str) or not value:
                        raise invalid("UNSUPPORTED_FORMULA", "包含无法读取为公式文本的 Excel 公式类型；不使用缓存值替代。")
                if value is not None and not isinstance(value, (str, int, float, bool, date, datetime, time)):
                    raise invalid("UNSUPPORTED_CELL_TYPE", "Excel 包含暂不支持的单元格类型（例如时长）；请使用常规值或明确的文本。")
                if isinstance(value, float) and not math.isfinite(value):
                    raise invalid("NON_FINITE_VALUE", "表格包含无法表示为有限数值的单元格。")
                if cell.data_type == "f":
                    formula_cells.append((cell.row, cell.column))
                if cell.data_type == "e":
                    error_cells.append((cell.row, cell.column))
                values.append(value)
            matrix.append(values)
        original_height, original_width = len(matrix), sheet.max_column
        # Define the table by its value extent, not formatting-only worksheet dimensions.
        while matrix and all(value is None for value in matrix[-1]):
            matrix.pop()
        if not matrix:
            raise invalid("EMPTY_DATASET", "所选工作表没有数据。")
        width = max((i + 1 for row in matrix for i, value in enumerate(row) if value is not None), default=0)
        matrix = [row[:width] for row in matrix]
        issues = []
        if len(matrix) != original_height or width != original_width:
            issues.append(QualityIssue(code="TRAILING_EMPTY_RANGE", severity="info",
                message="表格边界按最后一个有值的单元格确定；尾部仅有格式的空区域不计入数据行列。",
                affected_count=original_height * original_width - len(matrix) * width))
        for cells, code, message in [
            (formula_cells, "FORMULA_CELLS", "包含公式单元格；只保留公式文本，不计算公式，也不使用可能过期的缓存值。"),
            (error_cells, "EXCEL_ERROR_CELLS", "包含 Excel 错误单元格；保留其错误文本，不自动替换为空值。"),
        ]:
            if cells:
                issues.append(QualityIssue(code=code, message=message, affected_count=len(cells),
                    field_ids=[f"field_{i:04d}" for i in sorted({c for _, c in cells})],
                    example_row_numbers=sorted({r for r, _ in cells})[:5]))
        return ParsedTable(matrix[0], matrix[1:], "xlsx", selected, names,
                           options.model_copy(update={"sheet_name": selected}), issues)
    finally:
        workbook.close()


def parse_table(content: bytes, extension: str, options: ProfileOptions,
                limits: ParserLimits = ParserLimits()) -> ParsedTable:
    if extension not in {".csv", ".xlsx"}:
        raise invalid("UNSUPPORTED_FILE", "数据画像仅支持 CSV 或 XLSX 文件。")
    if not content:
        raise invalid("EMPTY_FILE", "上传文件不能为空。")
    if len(content) > limits.max_bytes:
        raise AppError("FILE_TOO_LARGE", "文件不能超过 10 MB。", 413)
    table = parse_csv(content, options, limits) if extension == ".csv" else parse_xlsx(content, options, limits)
    if not table.headers or all(value is None or (isinstance(value, str) and not value.strip()) for value in table.headers):
        raise invalid("EMPTY_HEADER", "指定的表头行必须包含至少一个字段名称，不自动猜测或跳过表头。")
    if not table.rows:
        raise invalid("NO_DATA_ROWS", "表格只有表头，没有数据行。")
    return table
