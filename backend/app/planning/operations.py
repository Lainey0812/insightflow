"""Small tested operation kernels. No dataset loader, scheduler, LLM or execution API."""
from datetime import date, datetime

import pandas as pd

from app.domain.dataset_profile import LogicalType as L
from .params import AggregateParams, DeriveParams, FilterParams, GroupParams, SortParams, TopNParams


def temporal(value):
    if isinstance(value, (date, datetime)):
        return value
    text = str(value).strip()
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if "T" in text or " " in text else date.fromisoformat(text)


def normalize(frame: pd.DataFrame, types: dict[str, L]) -> pd.DataFrame:
    """Interpret homogeneous profiler logical types, with errors raised, never coerced away."""
    result = frame.copy(deep=True)
    for name in result.columns:
        values = result[name].map(lambda x: None if pd.isna(x) or (isinstance(x, str) and not x.strip()) else x)
        kind = types[name]
        if kind in {L.INTEGER, L.NUMBER}:
            values = pd.to_numeric(values, errors="raise")
        elif kind in {L.DATE, L.DATETIME}:
            values = values.map(lambda x: None if pd.isna(x) else temporal(x))
        elif kind == L.BOOLEAN:
            def boolean(x):
                if pd.isna(x):
                    return None
                if isinstance(x, bool):
                    return x
                if isinstance(x, str) and x.strip().casefold() in {"true", "false"}:
                    return x.strip().casefold() == "true"
                raise ValueError("Invalid boolean")
            values = values.map(boolean)
        result[name] = values
    return result


def filter_rows(frame: pd.DataFrame, params: FilterParams, types: dict[str, L]):
    mask = pd.Series(True, index=frame.index)
    for condition in params.conditions:
        column = frame[condition.field]
        value = condition.value
        if types[condition.field] in {L.DATE, L.DATETIME} and value is not None:
            value = [temporal(x) for x in value] if isinstance(value, list) else temporal(value)
        op = condition.operator
        if op == "is_null":
            part = column.isna()
        elif op == "not_null":
            part = column.notna()
        elif op in {"in", "not_in"}:
            part = column.isin(value)
            if op == "not_in":
                part = ~part
            part &= column.notna()
        else:
            part = {"eq": column.eq, "ne": column.ne, "gt": column.gt,
                    "gte": column.ge, "lt": column.lt, "lte": column.le}[op](value)
            part &= column.notna()
        mask &= part.fillna(False)
    return frame.loc[mask].copy()


def metric_value(frame, metric):
    if metric.function == "count":
        return len(frame) if metric.field is None else int(frame[metric.field].count())
    series = frame[metric.field]
    if metric.function == "distinct_count":
        return int(series.nunique(dropna=True))
    if series.count() == 0:
        return None
    if metric.function == "sum":
        return series.sum(min_count=1)
    return getattr(series, {"avg": "mean"}.get(metric.function, metric.function))()


def aggregate(frame: pd.DataFrame, params: AggregateParams, types):
    return pd.DataFrame([{m.alias: metric_value(frame, m) for m in params.metrics}])


def group_aggregate(frame: pd.DataFrame, params: GroupParams, types):
    records = []
    for key, group in frame.groupby(params.dimensions, dropna=False, sort=False, observed=True):
        key = key if isinstance(key, tuple) else (key,)
        record = dict(zip(params.dimensions, key))
        record.update({m.alias: metric_value(group, m) for m in params.metrics})
        records.append(record)
    return pd.DataFrame(records, columns=[*params.dimensions, *(m.alias for m in params.metrics)])


def sort_rows(frame: pd.DataFrame, params: SortParams, types):
    return frame.sort_values(params.field, ascending=params.direction == "asc", kind="stable", na_position="last")


def top_n(frame: pd.DataFrame, params: TopNParams, types):
    return sort_rows(frame, params, types).head(params.n).copy()


def derive(frame: pd.DataFrame, params: DeriveParams, types):
    if params.function not in {"extract_year", "extract_month"}:
        raise ValueError("Unsupported transform")
    result = frame.copy()
    attr = "year" if params.function == "extract_year" else "month"
    result[params.alias] = pd.array([None if pd.isna(x) else getattr(temporal(x), attr)
                                   for x in frame[params.field]], dtype="Int64")
    return result
