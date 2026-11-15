import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime, time

from app.domain.dataset_profile import (
    SAMPLE_LIMIT, DatasetProfile, DatasetProvenance, FieldProfile, FieldSample, LogicalType,
    PhysicalType, ProfileOptions, QualityIssue,
)
from .versioning import dataset_version
from .parsers import Cell, ParserLimits, ParsedTable, parse_table
from .type_inference import combine_logical, combine_physical, is_missing, logical_type, physical_type, value_key


def field_id(position: int) -> str:
    return f"field_{position:04d}"


def sample(value: Cell) -> FieldSample:
    kind = physical_type(value)
    if isinstance(value, (date, datetime, time)):
        value = value.isoformat()
    truncated = isinstance(value, str) and len(value) > 120
    return FieldSample(value=value[:120] if truncated else value, physical_type=kind, truncated=truncated)


def describe_columns(table: ParsedTable) -> tuple[list[FieldProfile], list[QualityIssue]]:
    fields, issues = [], list(table.issues)
    names = defaultdict(list)
    column_values = defaultdict(list)
    blank_names, non_text_headers = [], []
    for index, header in enumerate(table.headers):
        position = index + 1
        fid = field_id(position)
        name = None if is_missing(header) else str(header)
        if name is None:
            blank_names.append(fid)
        else:
            names[name].append(fid)
            if not isinstance(header, str):
                non_text_headers.append(fid)
        values = [row[index] for row in table.rows]
        present = [value for value in values if not is_missing(value)]
        physical = Counter(physical_type(value) for value in present)
        logical = Counter(logical_type(value) for value in present)
        seen, samples = set(), []
        for value in present:
            key = value_key(value)
            if key not in seen and len(samples) < SAMPLE_LIMIT:
                samples.append(sample(value))
            seen.add(key)
        missing = len(values) - len(present)
        ptype, ltype = combine_physical(set(physical)), combine_logical(set(logical))
        fields.append(FieldProfile(field_id=fid, position=position, original_name=name,
            display_name=name if name is not None else f"未命名列 {position}", physical_type=ptype,
            logical_type=ltype, missing_count=missing, missing_rate=missing / len(values),
            non_missing_count=len(present), unique_count=len(seen), physical_type_counts=dict(physical),
            logical_type_counts=dict(logical), samples=samples))
        if not present:
            issues.append(QualityIssue(code="EMPTY_COLUMNS", message="该列所有数据行均缺失。",
                                       affected_count=1, field_ids=[fid]))
        for kind, code, message in [(ptype, "MIXED_PHYSICAL_TYPES", "该列包含不兼容的实际存储类型。"),
                                     (ltype, "MIXED_LOGICAL_TYPES", "该列按确定性规则识别出多种不兼容的值类型。")]:
            if kind in {PhysicalType.MIXED, LogicalType.MIXED}:
                issues.append(QualityIssue(code=code, message=message, affected_count=len(present), field_ids=[fid]))
        # Exact column comparison is separate from duplicate labels and never removes a column.
        column_values[tuple(value_key(value) for value in values)].append(fid)
    for fids in names.values():
        if len(fids) > 1:
            issues.append(QualityIssue(code="DUPLICATE_COLUMN_NAMES", message="列名重复；使用位置字段 ID 区分，不重命名原始列。",
                                       affected_count=len(fids) - 1, field_ids=fids))
    for fids in column_values.values():
        if len(fids) > 1:
            issues.append(QualityIssue(code="IDENTICAL_COLUMNS", message="这些列的值及存储类型逐行完全相同，疑似重复列；未删除。",
                                       affected_count=len(fids) - 1, field_ids=fids))
    for fids, code, message in [(blank_names, "BLANK_COLUMN_NAMES", "部分列名为空；显示名称为占位文字，字段 ID 不受影响。"),
                                 (non_text_headers, "NON_TEXT_HEADERS", "部分表头不是文本；仅将显示名称转换为文本。")]:
        if fids:
            issues.append(QualityIssue(code=code, message=message, affected_count=len(fids), field_ids=fids))
    return fields, issues


def build_profile(content: bytes, extension: str, dataset_id: str, file_name: str,
                  options: ProfileOptions | None = None, limits: ParserLimits = ParserLimits()) -> DatasetProfile:
    table = parse_table(content, extension, options or ProfileOptions(), limits)
    content_hash = hashlib.sha256(content).hexdigest()
    # Options describe parsing, not execution time or filename. Reprofiling yields the same version.
    version = dataset_version(content_hash, table.file_format, table.options)
    fields, issues = describe_columns(table)
    seen, duplicate_rows, empty_rows, repeated_headers = set(), [], [], []
    header_key = tuple(value_key(value) for value in table.headers)
    for index, row in enumerate(table.rows, start=table.options.header_row + 1):
        key = tuple(value_key(value) for value in row)
        if key in seen:
            duplicate_rows.append(index)
        seen.add(key)
        if all(is_missing(value) for value in row):
            empty_rows.append(index)
        if key == header_key:
            repeated_headers.append(index)
    for rows, code, message in [
        (duplicate_rows, "DUPLICATE_ROWS", "按解析后单元格值及类型检测到重复行；计数不含首次出现，未去重。"),
        (empty_rows, "EMPTY_ROWS", "包含全空数据行；计入总行数和缺失统计，未删除。"),
        (repeated_headers, "REPEATED_HEADER_ROWS", "数据区出现与表头完全相同的行，疑似重复表头；仍按数据行统计。"),
    ]:
        if rows:
            issues.append(QualityIssue(code=code, message=message, affected_count=len(rows), example_row_numbers=rows[:SAMPLE_LIMIT]))
    missing = sum(f.missing_count for f in fields)
    total = len(table.rows) * len(fields)
    return DatasetProfile(dataset_id=dataset_id, dataset_version=version, content_sha256=content_hash,
        file_name=file_name, file_format=table.file_format, sheet_name=table.sheet_name,
        available_sheets=table.available_sheets, options=table.options,
        row_count=len(table.rows), column_count=len(fields), total_cell_count=total,
        missing_cell_count=missing, missing_cell_rate=missing / total,
        duplicate_row_count=len(duplicate_rows), duplicate_row_rate=len(duplicate_rows) / len(table.rows),
        fields=fields, quality_issues=issues, provenance=DatasetProvenance(dataset=dataset_id,
            dataset_version=version, notice="从实际上传文件确定性计算；未清洗、未调用 LLM。"))
