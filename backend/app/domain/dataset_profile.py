import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .provenance import Provenance

PROFILER_VERSION = "1.1.0"
SAMPLE_LIMIT = 5


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PhysicalType(StrEnum):
    NULL = "null"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    MIXED = "mixed"


class LogicalType(StrEnum):
    EMPTY = "empty"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    TEXT = "text"
    MIXED = "mixed"


def aggregate_physical(kinds: set[PhysicalType]) -> PhysicalType:
    if not kinds:
        return PhysicalType.NULL
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds <= {PhysicalType.INTEGER, PhysicalType.FLOAT}:
        return PhysicalType.FLOAT
    if kinds <= {PhysicalType.DATE, PhysicalType.DATETIME}:
        return PhysicalType.DATETIME
    return PhysicalType.MIXED


def aggregate_logical(kinds: set[LogicalType]) -> LogicalType:
    if not kinds:
        return LogicalType.EMPTY
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds <= {LogicalType.INTEGER, LogicalType.NUMBER}:
        return LogicalType.NUMBER
    if kinds <= {LogicalType.DATE, LogicalType.DATETIME}:
        return LogicalType.DATETIME
    return LogicalType.MIXED


class ProfileOptions(ProfileModel):
    header_row: int = Field(default=1, ge=1, le=100_001, strict=True)
    sheet_name: str | None = Field(default=None, min_length=1, max_length=31)
    encoding: Literal["utf-8-sig", "gb18030"] = "utf-8-sig"
    delimiter: Literal[",", ";", "\t", "|"] = ","


class DatasetRef(ProfileModel):
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class DatasetProvenance(Provenance):
    source: Literal["uploaded"] = "uploaded"
    dataset: str = Field(min_length=1)
    dataset_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    notice: str = "从实际上传文件确定性计算；未清洗、未调用 LLM。"


class FieldSample(ProfileModel):
    value: str | int | float | bool
    physical_type: PhysicalType
    truncated: bool = False


class FieldProfile(ProfileModel):
    field_id: str = Field(pattern=r"^field_[0-9]{4}$")
    position: int = Field(ge=1)
    original_name: str | None
    display_name: str
    physical_type: PhysicalType
    logical_type: LogicalType
    missing_count: int = Field(ge=0)
    missing_rate: float = Field(ge=0, le=1)
    non_missing_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    physical_type_counts: dict[PhysicalType, int]
    logical_type_counts: dict[LogicalType, int]
    samples: list[FieldSample] = Field(max_length=SAMPLE_LIMIT)

    @model_validator(mode="after")
    def check_statistics(self) -> "FieldProfile":
        total = self.missing_count + self.non_missing_count
        if not total or not math.isclose(self.missing_rate, self.missing_count / total, abs_tol=1e-12):
            raise ValueError("Missing rate must equal missing_count / row_count")
        if (self.unique_count > self.non_missing_count or len(self.samples) != min(SAMPLE_LIMIT, self.unique_count)
                or (self.non_missing_count > 0 and self.unique_count == 0)):
            raise ValueError("Unique and sample counts exceed non-missing values")
        for counts in (self.physical_type_counts, self.logical_type_counts):
            if any(v <= 0 for v in counts.values()) or sum(counts.values()) != self.non_missing_count:
                raise ValueError("Type counts must describe every non-missing value")
        if (any(k in {PhysicalType.NULL, PhysicalType.MIXED} for k in self.physical_type_counts)
                or any(k in {LogicalType.EMPTY, LogicalType.MIXED} for k in self.logical_type_counts)):
            raise ValueError("Type counts must contain only actual non-missing primitive types")
        if (self.physical_type != aggregate_physical(set(self.physical_type_counts))
                or self.logical_type != aggregate_logical(set(self.logical_type_counts))):
            raise ValueError("Column types must agree with the value type counts")
        if self.field_id != f"field_{self.position:04d}":
            raise ValueError("Field ID must be derived from its 1-based position")
        return self


class QualityIssue(ProfileModel):
    code: Literal["DUPLICATE_COLUMN_NAMES", "BLANK_COLUMN_NAMES", "NON_TEXT_HEADERS",
                  "DUPLICATE_ROWS", "IDENTICAL_COLUMNS", "EMPTY_ROWS", "EMPTY_COLUMNS",
                  "MIXED_PHYSICAL_TYPES", "MIXED_LOGICAL_TYPES", "REPEATED_HEADER_ROWS",
                  "FORMULA_CELLS", "EXCEL_ERROR_CELLS", "TRAILING_EMPTY_RANGE"]
    severity: Literal["warning", "info"] = "warning"
    message: str
    affected_count: int = Field(ge=1)
    field_ids: list[str] = Field(default_factory=list)
    example_row_numbers: list[int] = Field(default_factory=list, max_length=SAMPLE_LIMIT)


class DatasetProfile(DatasetRef):
    schema_version: Literal["1.0"] = "1.0"
    profiler_version: str = PROFILER_VERSION
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    file_name: str
    file_format: Literal["csv", "xlsx"]
    sheet_name: str | None
    available_sheets: list[str]
    options: ProfileOptions
    row_count: int = Field(gt=0)
    column_count: int = Field(gt=0)
    total_cell_count: int = Field(gt=0)
    missing_cell_count: int = Field(ge=0)
    missing_cell_rate: float = Field(ge=0, le=1)
    duplicate_row_count: int = Field(ge=0)
    duplicate_row_rate: float = Field(ge=0, le=1)
    fields: list[FieldProfile]
    quality_issues: list[QualityIssue]
    provenance: DatasetProvenance

    @model_validator(mode="after")
    def check_dataset(self) -> "DatasetProfile":
        if self.column_count != len(self.fields) or self.total_cell_count != self.row_count * self.column_count:
            raise ValueError("Dataset dimensions are inconsistent")
        if [f.position for f in self.fields] != list(range(1, self.column_count + 1)):
            raise ValueError("Field positions must be unique and sequential")
        if any(f.missing_count + f.non_missing_count != self.row_count for f in self.fields):
            raise ValueError("Column row counts are inconsistent")
        if self.missing_cell_count != sum(f.missing_count for f in self.fields):
            raise ValueError("Dataset missing count is inconsistent")
        if not math.isclose(self.missing_cell_rate, self.missing_cell_count / self.total_cell_count, abs_tol=1e-12):
            raise ValueError("Dataset missing rate is inconsistent")
        if self.duplicate_row_count >= self.row_count or not math.isclose(
            self.duplicate_row_rate, self.duplicate_row_count / self.row_count, abs_tol=1e-12
        ):
            raise ValueError("Duplicate count or rate is inconsistent")
        ids = {f.field_id for f in self.fields}
        if any(not set(issue.field_ids) <= ids for issue in self.quality_issues):
            raise ValueError("Quality issue references unknown fields")
        if any(any(n < self.options.header_row or n > self.row_count + self.options.header_row
                   for n in issue.example_row_numbers) for issue in self.quality_issues):
            raise ValueError("Quality issue references a row outside the selected table")
        if self.file_format == "csv" and (self.sheet_name is not None or self.available_sheets):
            raise ValueError("CSV must not have sheets")
        if self.file_format == "xlsx" and self.sheet_name not in self.available_sheets:
            raise ValueError("Selected sheet must exist")
        if self.options.sheet_name != self.sheet_name:
            raise ValueError("Options must contain the resolved sheet")
        if (self.provenance.source != "uploaded" or self.provenance.dataset != self.dataset_id
                or self.provenance.dataset_version != self.dataset_version):
            raise ValueError("Profile must reference the real dataset version")
        return self
