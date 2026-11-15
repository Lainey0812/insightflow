import math
from decimal import Decimal
from datetime import datetime, timezone
from app.planning.operations import temporal as parse_temporal

from app.domain.analysis_report import Evidence
from app.domain.errors import AppError
from .contracts import ResultDescription


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return f'{value:,}'
    if isinstance(value, Decimal):
        text = format(value, ',f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if isinstance(value, float) and math.isfinite(value):
        # Preserve source decimals, including tiny durations. Only explicitly
        # derived comparison percentages have a fixed rounding contract.
        text = format(Decimal(str(value)), ',f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    return str(value)[:100] if value is not None else "缺失分组"


def arithmetic(left, right, operation):
    # Decimal avoids intermediate float overflow; discard unrepresentable derived values.
    a, b = Decimal(str(left)), Decimal(str(right))
    value = a - b if operation == "difference" else a / b * 100
    converted = int(value) if value == value.to_integral_value() else float(value)
    return converted if math.isfinite(converted) else None


class EvidenceBuilder:
    def build(self, execution, profile, descriptions: dict[str, ResultDescription]):
        evidence = []
        successful = {task.result.result_id: task for task in execution.tasks if task.status == "success"}
        def add(task, field, kind, value, rows, statement, calculation, related=()):
            item = Evidence(evidence_id=f"E{len(evidence) + 1:04d}", task_id=task.task_id,
                data_ref=task.result.result_id, result_field=field, evidence_type=kind, value=value,
                source_row_indices=rows, related_result_refs=list(related), scope=task.scope,
                calculation=(task.calculation[:1000] + "；" + calculation)[:2000], statement=statement)
            evidence.append(item)
        for task in execution.tasks:
            if task.status != "success":
                continue
            table, desc = task.result, descriptions[task.task_id]
            columns = {c.field: c for c in table.columns}
            usable = any(value is not None for row in table.rows for value in row.values())
            if desc.metrics and not any(number(row[field]) for row in table.rows for field in desc.metrics):
                usable = False
            if not usable:
                continue
            if task.valid_sample_count is not None:
                percent = arithmetic(task.valid_sample_count, profile.row_count, "percentage")
                add(task, "$execution.valid_sample_count", "coverage",
                    {"valid_samples": task.valid_sample_count, "effective_rows": task.effective_row_count,
                     "dataset_rows": profile.row_count, "coverage_percent": percent}, [],
                    f"该任务有效样本量为 {fmt(task.valid_sample_count)}，占上传数据行数约 {fmt(percent)}%。",
                    f"{task.sample_definition}；有效样本量 / 画像总行数 × 100；有效行数由执行模块提供。")
            dimension = desc.dimensions[0] if len(desc.dimensions) == 1 else None
            for field, metric in desc.metrics.items():
                column = columns[field]
                pairs = [(index, row[field]) for index, row in enumerate(table.rows) if number(row[field])]
                if not pairs:
                    continue
                label = column.label[:100]
                if not desc.dimensions and len(table.rows) == 1:
                    add(task, field, "metric", {"value": pairs[0][1], "unit": column.unit}, [0],
                        f"{label}为 {fmt(pairs[0][1])}{column.unit or ''}。", f"读取已计算指标 {field}，函数 {metric.function}。")
                if dimension:
                    ranked = sorted(pairs, key=lambda pair: -pair[1])
                    scope = "当前返回结果" if table.truncated or not desc.complete_partition else "该任务完整分组结果"
                    for index, value in ranked[:5]:
                        category = table.rows[index][dimension]
                        rank = 1 + sum(other > value for _, other in pairs)
                        add(task, field, "ranking", {"category": category, "value": value, "rank": rank}, [index],
                            f"在{scope}中，{fmt(category)}的{label}为 {fmt(value)}{column.unit or ''}，并列值采用同一名次，排名 {rank}。",
                            f"对已返回的 {field} 降序比较，竞争排名；不推断未返回类别。")
                    for kind, choose, word in [("maximum", max, "最大"), ("minimum", min, "最小")]:
                        target = choose(value for _, value in pairs)
                        indices = [index for index, value in pairs if value == target]
                        add(task, field, kind, {"value": target, "category": table.rows[indices[0]][dimension], "tie_count": len(indices)}, indices,
                            f"{scope}的{label}{word}值为 {fmt(target)}{column.unit or ''}，对应 {fmt(table.rows[indices[0]][dimension])}等 {len(indices)} 个分组。",
                            f"读取 {field} 的{word}值，保留并列来源行。")
                    if len(ranked) >= 2:
                        temporal = dimension in desc.temporal_dimensions
                        time_pairs = [pair for pair in pairs if table.rows[pair[0]][dimension] is not None]
                        def time_key(pair):
                            value = table.rows[pair[0]][dimension]
                            if isinstance(value, (int, float)):
                                return value
                            parsed = parse_temporal(value)
                            if isinstance(parsed, datetime) and parsed.tzinfo is not None:
                                parsed = parsed.astimezone(timezone.utc)
                            return parsed.isoformat()
                        ordered = sorted(time_pairs, key=time_key) if temporal else ranked
                        if len(ordered) < 2:
                            continue
                        first, second = (ordered[-1], ordered[0]) if temporal else (ranked[0], ranked[1])
                        a, b = first[1], second[1]
                        delta = arithmetic(a, b, "difference")
                        left, right = table.rows[first[0]][dimension], table.rows[second[0]][dimension]
                        if delta is not None:
                            add(task, field, "difference", {"left": left, "right": right, "left_value": a, "right_value": b, "difference": delta},
                                [first[0], second[0]], f"在{scope}中，{fmt(left)}与{fmt(right)}的{label}差值为 {fmt(delta)}{column.unit or ''}。",
                                f"已计算值相减：{field}[{first[0]}] - {field}[{second[0]}]；不是因果或显著性检验。")
                        if temporal and b > 0 and delta is not None:
                            rate = arithmetic(delta, b, "percentage")
                            if rate is not None:
                                add(task, field, "change_rate", {"from": right, "to": left, "baseline": b, "current": a, "change_percent": rate},
                                    [second[0], first[0]], f"在已返回时间点中，{label}从 {fmt(right)}至{fmt(left)}变化约 {fmt(rate)}%。",
                                    f"(末期已计算值 - 首期已计算值) / 首期已计算值 × 100；首期分母为正；不保证时间点连续。")
                    total_ref = next((ref for ref in table.total_refs if ref.metric_field == field), None)
                    denominator, related = None, []
                    if total_ref:
                        denominator_task = successful.get(total_ref.result_id)
                        if denominator_task is None:
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母引用的结果不存在或执行失败。", 422)
                        other = descriptions[denominator_task.task_id]
                        other_table = denominator_task.result
                        other_metric = other.metrics.get(total_ref.result_field)
                        denom_column = next((c for c in other_table.columns if c.field == total_ref.result_field), None)
                        valid = (metric.function in {"count", "sum"} and other_metric is not None and
                            (other_metric.function, other_metric.field) == (metric.function, metric.field) and
                            other.scope_key == desc.scope_key and denominator_task.effective_row_count == task.effective_row_count and not other.dimensions and not other_table.truncated and
                            len(other_table.rows) == 1 and denom_column is not None and denom_column.unit == column.unit)
                        if not valid:
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母必须来自同统计范围、同指标口径的成功标量结果。", 422)
                        denominator = other_table.rows[0][total_ref.result_field]
                        related = [other_table.result_id]
                        if not number(denominator) or denominator <= 0 or any(value < 0 or value > denominator for _, value in pairs):
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母无效或小于分组指标。", 422)
                    elif desc.complete_partition and metric.function in {"count", "sum"} and len(pairs) == len(table.rows) and all(value >= 0 for _, value in pairs):
                        summed = sum(Decimal(str(value)) for _, value in pairs)
                        denominator = float(summed)
                        if not math.isfinite(denominator) or denominator <= 0:
                            denominator = None
                    if denominator is not None:
                        for index, value in ranked[:5]:
                            share = arithmetic(value, denominator, "percentage")
                            if share is None:
                                continue
                            category = table.rows[index][dimension]
                            add(task, field, "proportion", {"category": category, "numerator": value, "denominator": denominator, "percent": share}, [index],
                                f"{fmt(category)}的{label}占该任务同口径总体约 {fmt(share)}%。",
                                "已计算分组指标 / 已验证同口径总体分母 × 100；分母来自" + ("显式成功标量引用。" if related else "完整互斥分组之和。"), related)
            # A returned-group sum is NOT a population denominator. Never sum averages,
            # medians or distinct counts, and never treat an incomplete preview as full data.
            if desc.dimensions and not table.truncated and table.row_offset == 0:
                for field, metric in desc.metrics.items():
                    values = [row[field] for row in table.rows]
                    if metric.function not in {"sum", "count"} or not values or not all(number(v) for v in values):
                        continue
                    exact = sum(Decimal(str(v)) for v in values)
                    total = int(exact) if exact == exact.to_integral_value() else float(exact)
                    if not math.isfinite(total):
                        continue
                    column = columns[field]
                    label = "本次返回分组合计（" + column.label[:80] + "）"
                    add(task, field, "metric", {"value": total, "unit": column.unit, "label": label},
                        list(range(len(table.rows))),
                        f"本次返回的 {len(table.rows)} 个分组的{column.label[:100]}合计为 {fmt(total)}{column.unit or ''}。",
                        "仅将当前完整返回表中的可加指标相加；含 Top N 时只代表所选分组，不作为总体占比分母。")
            # Compare already calculated metrics only when their units/bases are compatible.
            if not desc.dimensions and len(table.rows) == 1:
                names = list(desc.metrics)
                if len(names) >= 2:
                    left, right = names[:2]
                    a, b = table.rows[0][left], table.rows[0][right]
                    lm, rm = desc.metrics[left], desc.metrics[right]
                    same_measure = lm.field == rm.field and lm.field is not None and (lm.function in {"count", "distinct_count"}) == (rm.function in {"count", "distinct_count"})
                    same_unit = columns[left].unit is not None and columns[left].unit == columns[right].unit and lm.function == rm.function
                    if number(a) and number(b) and (same_measure or same_unit):
                        delta = arithmetic(a, b, "difference")
                        if delta is not None:
                            add(task, left, "comparison", {"left_field": left, "right_field": right, "left_value": a, "right_value": b, "difference": delta}, [0],
                                f"已计算的{columns[left].label[:80]}与{columns[right].label[:80]}差值为 {fmt(delta)}{columns[left].unit or ''}。",
                                f"比较同口径指标 {left} 与 {right} 的已计算值，不生成新的基础指标。")
        from .comparisons import comparison_evidence
        evidence.extend(comparison_evidence(execution, descriptions, len(evidence)))
        return evidence
