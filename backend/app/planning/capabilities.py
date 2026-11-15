from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from pydantic import BaseModel

from app.domain.dataset_profile import LogicalType as L
from . import operations
from .params import AggregateParams, DeriveParams, FilterParams, GroupParams, SortParams, TopNParams

NUMERIC = {L.INTEGER, L.NUMBER}
TEMPORAL = {L.DATE, L.DATETIME}
COMPARABLE = {L.TEXT, L.BOOLEAN, *NUMERIC, *TEMPORAL, L.TIME}


class CapabilityError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None):
        self.code, self.message, self.field = code, message, field
        super().__init__(message)


@dataclass(frozen=True)
class FieldState:
    kind: L
    non_missing: int | None = None
    requires_transformation: bool = False


@dataclass(frozen=True)
class OperationSpec:
    params_model: type[BaseModel]
    handler: Callable
    input_rules: str
    output_rules: str


class CapabilityRegistry:
    version = "1.0"

    def __init__(self):
        self.operations = {
            "filter": OperationSpec(FilterParams, operations.filter_rows,
                "AND conditions; typed comparisons; null only via is_null/not_null; no semantic matching",
                "Preserves all current fields; no new fields"),
            "group_aggregate": OperationSpec(GroupParams, operations.group_aggregate,
                "Unique comparable dimensions; numeric sum/avg/median/min/max; count optional field; distinct_count comparable field",
                "Replaces input with dimensions and unique fresh metric aliases; missing groups retained"),
            "aggregate": OperationSpec(AggregateParams, operations.aggregate,
                "Numeric sum/avg/median/min/max; count optional field; distinct_count comparable field",
                "Replaces input with metric aliases only"),
            "sort": OperationSpec(SortParams, operations.sort_rows,
                "Existing comparable field; stable asc/desc; null last", "Preserves fields"),
            "top_n": OperationSpec(TopNParams, operations.top_n,
                "Existing comparable field; n integer 1..1000; sort then head; stable ties", "Preserves fields"),
            "derive": OperationSpec(DeriveParams, operations.derive,
                "Only extract_year/extract_month; homogeneous DATE/DATETIME including valid ISO strings",
                "Preserves fields and adds a fresh INTEGER alias; no text-to-date guess, salary parsing or skill extraction"),
        }

    def summary(self):
        return {"version": self.version, "operations": {
            name: {"supported": True, "params_schema": spec.params_model.model_json_schema(),
                   "input_rules": spec.input_rules, "output_rules": spec.output_rules}
            for name, spec in self.operations.items()},
            "aggregate_functions": ["count", "sum", "avg", "median", "min", "max", "distinct_count"],
            "derive_functions": ["extract_year", "extract_month"],
            "execution_scope": "tested kernels with versioned dataset execution service; server-owned approval required; cross-task dependencies unsupported",
            "null_policy": "count()=rows; count(field)=nonmissing; distinct_count excludes null; numeric all-null result=null; missing groups retained",
            "logical_input_policy": "CSV homogeneous logical numbers/ISO dates are interpreted deterministically; no mixed/text semantic conversion"}

    def propagate(self, operation, params, fields: dict[str, FieldState], reserved: set[str]):
        """Type/output rules for the same kernels advertised by this registry."""
        def require(name):
            if name not in fields:
                raise CapabilityError("INVALID_FIELD_REFERENCE", "字段不在当前步骤输入中。", name)
            return fields[name]

        def comparable(name):
            state = require(name)
            if state.kind not in COMPARABLE:
                raise CapabilityError("TYPE_MISMATCH", "字段类型不支持该操作。", name)
            return state

        def fresh(alias):
            if alias in reserved:
                raise CapabilityError("INVALID_FIELD_REFERENCE", "输出别名与原始字段或已有别名冲突。", alias)

        if operation == "derive":
            if params.function not in {"extract_year", "extract_month"}:
                raise CapabilityError("UNSUPPORTED_OPERATION", "未实现该派生能力。", params.field)
            state = require(params.field)
            if state.kind not in TEMPORAL:
                raise CapabilityError("TYPE_MISMATCH", "时间派生只接受有效日期/日期时间，不能猜测文本日期。", params.field)
            if state.non_missing == 0:
                raise CapabilityError("INVALID_DATA", "时间字段没有有效值。", params.field)
            fresh(params.alias)
            return {**fields, params.alias: FieldState(L.INTEGER, state.non_missing, True)}
        if operation in {"aggregate", "group_aggregate"}:
            dimensions = params.dimensions if operation == "group_aggregate" else []
            if len(dimensions) != len(set(dimensions)):
                raise CapabilityError("INVALID_SCHEMA", "分组字段不能重复。")
            output = {name: comparable(name) for name in dimensions}
            for metric in params.metrics:
                fresh(metric.alias)
                if metric.alias in output:
                    raise CapabilityError("INVALID_SCHEMA", "指标别名不能重复。", metric.alias)
                state = (require(metric.field) if metric.function == "count" else comparable(metric.field)) if metric.field is not None else None
                if metric.function not in {"count", "distinct_count"}:
                    if state.kind not in NUMERIC:
                        raise CapabilityError("TYPE_MISMATCH", "数值聚合需要可计算数值字段；薪资区间文本不可直接求均值。", metric.field)
                    if state.non_missing == 0:
                        raise CapabilityError("INVALID_DATA", "数值字段没有有效值。", metric.field)
                kind = L.INTEGER if metric.function in {"count", "distinct_count"} else (L.NUMBER if metric.function in {"avg", "median"} else state.kind)
                needs_transform = any(fields[name].requires_transformation for name in dimensions)
                needs_transform |= state.requires_transformation if state is not None else False
                output[metric.alias] = FieldState(kind, requires_transformation=needs_transform)
            return output
        if operation in {"sort", "top_n"}:
            comparable(params.field)
        elif operation == "filter":
            for c in params.conditions:
                state = require(c.field)
                if c.operator in {"is_null", "not_null"}:
                    continue
                comparable(c.field)
                values = c.value if isinstance(c.value, list) else [c.value]
                for value in values:
                    valid = False
                    if state.kind in NUMERIC:
                        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
                    elif state.kind == L.BOOLEAN:
                        valid = isinstance(value, bool) and c.operator in {"eq", "ne", "in", "not_in"}
                    elif state.kind == L.TEXT:
                        valid = isinstance(value, str) and c.operator in {"eq", "ne", "in", "not_in"}
                    elif state.kind in TEMPORAL and isinstance(value, str):
                        try:
                            parsed = operations.temporal(value)
                            valid = isinstance(parsed, datetime) if state.kind == L.DATETIME else type(parsed) is date
                        except ValueError:
                            pass
                    if not valid:
                        raise CapabilityError("TYPE_MISMATCH", "筛选值/比较方式与字段类型不兼容。", c.field)
        refs = [params.field] if operation in {"sort", "top_n"} else [c.field for c in params.conditions]
        if any(fields[name].requires_transformation for name in refs):
            return {name: FieldState(state.kind, state.non_missing, True) for name, state in fields.items()}
        return dict(fields)

    def request_schema(self):
        """Strict provider schema with per-operation parameter contracts (no free dict)."""
        from app.domain.analysis_plan import PlannerDraft
        schema = PlannerDraft.model_json_schema()
        branches = []
        for name, spec in self.operations.items():
            params = spec.params_model.model_json_schema()
            schema["$defs"].update(params.pop("$defs", {}))
            branches.append({"type": "object", "properties": {
                "step_id": {"type": "string", "minLength": 1, "maxLength": 120, "pattern": r"\S"},
                "operation": {"type": "string", "enum": [name]}, "params": params},
                "required": ["step_id", "operation", "params"], "additionalProperties": False})
        schema["$defs"]["AnalysisStep"] = {"anyOf": branches}
        # Strict output requires nullable Metric.field to be explicitly present.
        def required_objects(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    value["additionalProperties"] = False
                    value["required"] = list(value.get("properties", {}))
                value.pop("default", None)
                for child in value.values():
                    required_objects(child)
            elif isinstance(value, list):
                for child in value:
                    required_objects(child)
        required_objects(schema)
        return schema
