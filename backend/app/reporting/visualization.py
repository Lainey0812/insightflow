from app.domain.analysis_report import ChartSpec


class VisualizationBuilder:
    def build(self, execution, descriptions, evidence, tasks, intent):
        charts = []
        for executed in execution.tasks:
            if executed.status != "success" or not executed.result.rows:
                continue
            table, desc = executed.result, descriptions[executed.task_id]
            refs = [e.evidence_id for e in evidence if e.task_id == executed.task_id]
            if not refs:
                continue
            metrics = list(desc.metrics)
            dimension = desc.dimensions[0] if len(desc.dimensions) == 1 else None
            supported, default, order = ["table"], "table", "original"
            note = "结果已由上游截断；图表和表格仅覆盖返回数据。" if table.truncated else None
            if any(step.operation == "top_n" for step in tasks[executed.task_id].steps):
                note = (note + " " if note else "") + "任务含 Top N 筛选；此处展示选定结果，不推断未返回分组。"
            if not desc.dimensions and len(table.rows) == 1 and len(metrics) == 1:
                supported, default = ["kpi", "table"], "kpi"
            elif dimension and metrics:
                supported, default, order = ["bar", "table"], "bar", "value_desc"
                values = [row[dimension] for row in table.rows if row[dimension] is not None]
                if dimension in desc.temporal_dimensions and len(values) >= 2:
                    supported, default, order = ["line", "bar", "table"], "line", "dimension_asc"
                    note = (note + " " if note else "") + "按已有时间点展示；缺失时间分组仅见表格，不推断连续性。"
                else:
                    share_rows = {i for e in evidence if e.task_id == executed.task_id and e.evidence_type == "proportion" and e.result_field == metrics[0] for i in e.source_row_indices}
                    short_labels = all(len(str(value)) <= 12 for value in values)
                    if len(metrics) == 1 and len(table.rows) <= 5 and short_labels and desc.complete_partition and not table.truncated and len(share_rows) == len(table.rows):
                        supported = ["bar", "pie", "table"]
                        goal = intent.analysis_goal.business_goal or ""
                        if any(word in goal for word in ["占比", "构成", "组成"]):
                            default = "pie"
                if len(table.rows) > 10 and default != "line":
                    note = (note + " " if note else "") + "图表默认展示前 10 个返回分组；完整返回结果可在数据表中查看。"
            # Engine already executed the approved ordering. A default chart
            # recommendation must not silently reverse an ascending metric or
            # descending date request. Preserve the actual result sequence.
            if any(step.operation in {'sort', 'top_n'} for step in tasks[executed.task_id].steps):
                order = 'original'
            charts.append(ChartSpec(chart_id=f"C{len(charts) + 1:03d}", task_id=executed.task_id,
                title=tasks[executed.task_id].title, chart_type=default, dimension=dimension, metrics=metrics,
                data_ref=table.result_id, supported_chart_types=supported, evidence_refs=refs,
                display_limit=10, order=order, note=note))
        return charts
