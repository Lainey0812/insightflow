import pandas as pd

from app.domain.enums import Operation
from app.domain.models import ExecutionResult, Plan, Provenance, TaskResult
from .base import Node

# Fixed demo fixture. These records NEVER originate from the uploaded file or LLM.
DEMO_ROWS = [
    {"month": month, "product": product, "region": region, "sales": sales}
    for month, numbers in [
        ("2026-01", [18000, 12000]), ("2026-02", [22000, 14000]),
        ("2026-03", [21000, 18000]), ("2026-04", [28000, 17000]),
        ("2026-05", [32000, 21000]), ("2026-06", [36000, 24000]),
    ]
    for product, region, sales in zip(["产品 A", "产品 B"], ["华东", "华南"], numbers)
]


class MockAnalysisEngine(Node[Plan, ExecutionResult]):
    name = "analysis_engine"

    async def process(self, payload: Plan) -> ExecutionResult:
        frame = pd.DataFrame(DEMO_ROWS)
        results = []
        fields = {Operation.TREND: "month", Operation.CATEGORY: "product", Operation.REGION: "region"}
        for task in payload.tasks:
            if task.operation == Operation.SUMMARY:
                labels, values = ["销售总额"], [float(frame["sales"].sum())]
                evidence = "固定示例 12 条记录；对 sales 列求和，单位：元。"
            else:
                # Enum + explicit map are the only executable operations; no eval or generated code.
                field = fields[task.operation]
                grouped = frame.groupby(field, sort=True)["sales"].sum()
                labels, values = list(grouped.index), [float(v) for v in grouped.values]
                evidence = f"固定示例 12 条记录；按 {field} 分组后对 sales 求和，单位：元。"
            results.append(TaskResult(task_id=task.id, operation=task.operation, title=task.title,
                                      labels=labels, values=values, evidence=evidence))
        return ExecutionResult(plan_version=payload.version, results=results,
                               provenance=Provenance(plan_version=payload.version))
