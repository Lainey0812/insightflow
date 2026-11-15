from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from app.domain.analysis_plan import Name, PlanModel

Scalar = StrictStr | StrictInt | StrictFloat | StrictBool | None


class Condition(PlanModel):
    field: Name
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null"]
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def check_value(self):
        if self.operator in {"is_null", "not_null"}:
            if self.value is not None:
                raise ValueError("Null checks require value=null")
        elif self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value or any(x is None for x in self.value):
                raise ValueError("Membership requires a nonempty list without null")
        elif self.value is None or isinstance(self.value, list):
            raise ValueError("Comparisons require a nonnull scalar")
        return self


class FilterParams(PlanModel):
    conditions: list[Condition] = Field(min_length=1, max_length=20)


class Metric(PlanModel):
    function: Literal["count", "sum", "avg", "median", "min", "max", "distinct_count"]
    field: Name | None = None
    alias: Name

    @model_validator(mode="after")
    def needs_field(self):
        if self.function != "count" and self.field is None:
            raise ValueError("Only count may omit field (row count)")
        return self


class AggregateParams(PlanModel):
    metrics: list[Metric] = Field(min_length=1, max_length=20)


class GroupParams(AggregateParams):
    dimensions: list[Name] = Field(min_length=1, max_length=10)


class SortParams(PlanModel):
    field: Name
    direction: Literal["asc", "desc"]


class TopNParams(SortParams):
    n: Annotated[int, Field(strict=True, ge=1, le=1000)]


class DeriveParams(PlanModel):
    # Unknown transforms are represented and rejected by capability matching as F0.
    function: Name
    field: Name
    alias: Name
