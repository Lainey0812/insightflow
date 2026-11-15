from app.domain.enums import Operation
from app.domain.models import ExecutionResult, Report, ReportSection
from .base import Node


class MockReportModule(Node[ExecutionResult, Report]):
    name = "report_module"

    async def process(self, payload: ExecutionResult) -> Report:
        sections = []
        for result in payload.results:
            total = sum(result.values)
            if result.operation == Operation.SUMMARY:
                insight = f"固定示例的销售总额为 ¥{total:,.0f}。"
            else:
                index = max(range(len(result.values)), key=lambda i: result.values[i])
                share = result.values[index] / total * 100 if total else 0
                insight = (f"固定示例中，{result.labels[index]}销售额最高，为 "
                           f"¥{result.values[index]:,.0f}，占该分组总额的 {share:.1f}%。")
            option = {
                "tooltip": {"trigger": "axis", "valueFormatter": None},
                "grid": {"left": 68, "right": 24, "top": 24, "bottom": 36},
                "xAxis": {"type": "category", "data": result.labels, "axisLine": {"show": False},
                          "axisTick": {"show": False}},
                "yAxis": {"type": "value", "splitLine": {"lineStyle": {"color": "#eef0f5"}}},
                "series": [{"data": result.values,
                            "type": "line" if result.operation == Operation.TREND else "bar",
                            "smooth": True, "barMaxWidth": 48,
                            "itemStyle": {"color": "#7061d8"},
                            "areaStyle": {"color": "#f0edff"}}],
            }
            sections.append(ReportSection(title=result.title, insight=insight,
                                          evidence=result.evidence, result=result, chart_option=option))
        return Report(title="销售数据分析 · 示例报告", sections=sections, provenance=payload.provenance)
