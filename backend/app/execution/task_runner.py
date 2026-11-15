import json
import math
from datetime import date, datetime, time
from numbers import Integral, Real
from time import perf_counter

import pandas as pd

from app.domain.dataset_profile import LogicalType as L
from app.domain.execution import (ExecutedTask, ExecutionError, ResultColumn, ResultTable,
                                  StepExecutionLog, TaskExecutionMetadata, SampleStatistics, SampleField, MetricParticipation)
from app.domain.models import now, uid
from app.planning.capabilities import CapabilityError, FieldState
from app.planning.operations import normalize
from app.planning.params import AggregateParams, DeriveParams, FilterParams, GroupParams, SortParams


class TaskDataError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def references(params):
    if isinstance(params, FilterParams): return [c.field for c in params.conditions]
    if isinstance(params, AggregateParams):
        return ([*params.dimensions] if isinstance(params, GroupParams) else []) + [m.field for m in params.metrics if m.field is not None]
    if isinstance(params, (SortParams, DeriveParams)): return [params.field]
    return []


def scalar(value, kind):
    if value is None or pd.isna(value): return None
    if hasattr(value, "item"): value = value.item()
    if kind == L.INTEGER:
        if isinstance(value, bool) or not isinstance(value, (Integral, Real)) or int(value) != value:
            raise TaskDataError("INVALID_RESULT_TYPE", "整数结果包含不兼容值。")
        if not isinstance(value, Integral) and abs(value) >= 2 ** 53:
            raise TaskDataError("NUMERIC_PRECISION_LOSS", "内核将大整数转为浮点数，无法保证整数精度。")
        return int(value)
    if kind == L.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (Integral, Real)) or not math.isfinite(value):
            raise TaskDataError("NON_FINITE_RESULT", "数值结果无效或超出有限表示范围。")
        return float(value)
    if kind == L.BOOLEAN:
        if not isinstance(value, bool): raise TaskDataError("INVALID_RESULT_TYPE", "布尔结果类型不一致。")
        return value
    if isinstance(value, (datetime, date, time)): return value.isoformat()
    if kind in {L.TEXT, L.DATE, L.DATETIME, L.TIME}:
        if not isinstance(value, str): raise TaskDataError("INVALID_RESULT_TYPE", "文本或时间结果类型不一致。")
        return value
    if isinstance(value, float) and not math.isfinite(value):
        raise TaskDataError("NON_FINITE_RESULT", "结果包含非有限值。")
    return value


def normalize_fields(frame, names, fields):
    if not names: return
    original = frame[names]
    normalized = normalize(original, {name: fields[name].kind for name in names})
    for name in names:
        if fields[name].kind == L.INTEGER:
            values = []
            for old, value in zip(original[name], normalized[name]):
                if pd.isna(value): values.append(None); continue
                # Refuse lossy nullable integer conversion; never return rounded statistics.
                expected = int(old.strip()) if isinstance(old, str) else int(old)
                if int(value) != expected:
                    raise TaskDataError("NUMERIC_PRECISION_LOSS", "整数规范化会丢失精度，未执行该步骤。")
                values.append(expected)
            # Python integers avoid NumPy int64 sum wrapping; kernels remain unchanged.
            frame[name] = pd.Series(values, index=frame.index, dtype=object)
        else:
            frame[name] = normalized[name]


def task_error(exc, task_id, step_id):
    if isinstance(exc, (TaskDataError, CapabilityError)):
        return ExecutionError(code=exc.code, message=exc.message, task_id=task_id, step_id=step_id)
    code, message = ("NUMERIC_OVERFLOW", "计算超出数值表示范围。") if isinstance(exc, OverflowError) else ("OPERATION_DATA_ERROR", "操作无法处理当前数据，请检查类型、日期和数值范围。")
    return ExecutionError(code=code, message=message, task_id=task_id, step_id=step_id)


class TaskRunner:
    def __init__(self, registry): self.registry = registry

    def run(self, task, loaded, preview_bytes, preview_cells):
        started, timer = now(), perf_counter()
        frame = loaded.frame.copy(deep=True)
        fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in loaded.profile.fields}
        reserved, normalized = set(fields), set()
        logs, warnings, metrics = [], [], {}
        labels = {f.field_id: f.display_name for f in loaded.profile.fields}
        effective, aggregated, metric_valid = len(frame), False, {}
        sample_statistics = None
        single_aggregate = sum(s.operation in {'aggregate', 'group_aggregate'} for s in task.steps) == 1
        step_id = None
        try:
            for step in task.steps:
                step_id, step_timer, input_rows = step.step_id, perf_counter(), len(frame)
                try:
                    spec = self.registry.operations.get(step.operation)
                    if spec is None:
                        raise TaskDataError("UNSUPPORTED_OPERATION", "该操作未在当前能力目录中实现。")
                    params = spec.params_model.model_validate(step.params)
                    new_fields = self.registry.propagate(step.operation, params, fields, reserved)
                    needed = [name for name in dict.fromkeys(references(params)) if name not in normalized and name in loaded.frame.columns]
                    normalize_fields(frame, needed, fields)
                    normalized.update(needed)
                    if isinstance(params, AggregateParams):
                        if not aggregated: effective = len(frame)
                        aggregated = True
                        metrics = {m.alias:m for m in params.metrics}
                        metric_valid = {m.alias: len(frame) if m.field is None else int(frame[m.field].count()) for m in params.metrics}
                        if single_aggregate:
                            key_fields = list(dict.fromkeys(references(params)))
                            missing = frame[key_fields].isna() if key_fields else None
                            sample_statistics = SampleStatistics(aggregate_step_id=step.step_id,
                                input_row_count=len(frame),
                                key_fields=[SampleField(field=name, label=labels.get(name, name)[:1800],
                                    missing_count=int(missing[name].sum())) for name in key_fields],
                                complete_row_count=int((~missing.any(axis=1)).sum()) if key_fields else None,
                                missing_row_count=int(missing.any(axis=1).sum()) if key_fields else None,
                                metrics={m.alias: MetricParticipation(function=m.function, field=m.field,
                                    label=labels.get(m.field, '记录')[:1800],
                                    basis='rows' if m.field is None else 'distinct_non_null_values' if m.function == 'distinct_count' else 'non_null_values',
                                    participating_count=metric_valid[m.alias]) for m in params.metrics})
                        functions = {"count":"计数", "distinct_count":"去重计数", "sum":"合计", "avg":"均值", "median":"中位数", "min":"最小值", "max":"最大值"}
                        for metric in params.metrics:
                            labels[metric.alias] = (labels.get(metric.field, "记录")[:1800] + " · " + functions[metric.function])[:2000]
                    elif isinstance(params, DeriveParams):
                        labels[params.alias] = labels.get(params.field, params.field)[:1800] + (" · 年份" if params.function == "extract_year" else " · 月份")
                    result = spec.handler(frame, params, {name:state.kind for name,state in fields.items()})
                    if not isinstance(result, pd.DataFrame) or list(result.columns) != list(new_fields):
                        raise TaskDataError("INVALID_RESULT_SCHEMA", "计算内核输出字段与能力目录不一致。")
                    # Validate numeric intermediates before another step can hide an
                    # overflow or consume a rounded nullable integer produced by Pandas.
                    for name, state in new_fields.items():
                        if state.kind in {L.INTEGER, L.NUMBER} and (name in normalized or name not in loaded.frame.columns):
                            for value in result[name]:
                                scalar(value, state.kind)
                    frame, fields = result, new_fields
                    reserved.update(fields)
                    step_warnings = ["本步骤结果为空，仍按成功记录。"] if frame.empty else []
                    logs.append(StepExecutionLog(step_id=step_id, operation=step.operation, status="success",
                        input_row_count=input_rows, output_row_count=len(frame), duration_ms=(perf_counter()-step_timer)*1000,
                        warnings=step_warnings))
                except Exception as exc:
                    error = task_error(exc, task.task_id, step_id)
                    logs.append(StepExecutionLog(step_id=step_id, operation=step.operation, status="failed",
                        input_row_count=input_rows, output_row_count=None, duration_ms=(perf_counter()-step_timer)*1000, error=error))
                    raise TaskDataError(error.code, error.message) from None
            if not aggregated: effective = len(frame)
            remaining = [name for name in frame.columns if name in loaded.frame.columns and name not in normalized]
            normalize_fields(frame, remaining, fields)
            columns = [ResultColumn(field=name, label=labels.get(name,name)[:2000], logical_type=state.kind,
                role="metric" if name in metrics else "dimension",
                unit="条" if name in metrics and metrics[name].function in {"count","distinct_count"} else None) for name,state in fields.items()]
            rows = [{name:scalar(value, fields[name].kind) for name,value in zip(frame.columns, values)}
                    for values in frame.itertuples(index=False, name=None)]
            # Full rows are persisted separately. Preview is a bounded prefix, never a computation input.
            preview, used = [], 0
            for row in rows[:min(100, preview_cells // max(1,len(columns)))]:
                size = len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode())
                if used + size > preview_bytes: break
                preview.append(row); used += size
            result_id = "result_" + uid()
            table = ResultTable(result_id=result_id, columns=columns, rows=preview,
                truncated=len(preview) != len(rows), total_result_rows=len(rows))
            counts = set(metric_valid.values())
            valid_count = next(iter(counts)) if len(counts) == 1 else (effective if not aggregated else None)
            if len(preview) < len(rows): warnings.append("响应仅包含预览；完整结果已保存，不能把预览行数当作完整行数。")
            metadata = TaskExecutionMetadata(input_row_count=len(loaded.frame), started_at=started, finished_at=now(),
                duration_ms=(perf_counter()-timer)*1000, preview_row_count=len(preview), metric_valid_counts=metric_valid, sample_statistics=sample_statistics,
                steps=logs, warnings=warnings)
            output = ExecutedTask(task_id=task.task_id, status="success", result=table, result_id=result_id,
                result_ref=result_id, row_count=len(rows), effective_row_count=effective, valid_sample_count=valid_count,
                sample_definition="聚合前各最终指标的非缺失参与数；指标样本数不同时不提供统一有效样本量。" if aggregated else "结果保留记录数；未执行通用整行缺失剔除。",
                scope="指定数据集版本内，按批准任务的筛选和选择操作限定的范围。",
                calculation="批准操作链：" + " → ".join(s.operation for s in task.steps), failure_reason=None,
                execution_metadata=metadata)
            return output, [column.model_dump(mode="json") for column in columns], rows, used
        except Exception as exc:
            error = task_error(exc, task.task_id, step_id)
            return ExecutedTask(task_id=task.task_id, status="failed", result=None,
                effective_row_count=effective, valid_sample_count=None, sample_definition="任务未完成，不提供有效样本量。",
                scope="指定数据集版本", calculation="任务未完成，未生成统计结果。", failure_reason=error.message,
                error=error, execution_metadata=TaskExecutionMetadata(input_row_count=len(loaded.frame), started_at=started,
                    finished_at=now(), duration_ms=(perf_counter()-timer)*1000, preview_row_count=0, steps=logs)), None, None, 0
