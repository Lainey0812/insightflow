from pydantic import BaseModel

from app.domain.enums import Operation
from app.domain.models import AnalysisTask, DataProfile, Intent, Plan
from app.domain.dataset_profile import DatasetProfile
from app.domain.intent import IntentArtifact
from .base import Node


def make_task(operation: Operation) -> AnalysisTask:
    titles = {
        Operation.SUMMARY: ("销售概况", "汇总示例销售额，建立分析基线。"),
        Operation.TREND: ("月度销售趋势", "按月汇总销售额，观察变化。"),
        Operation.CATEGORY: ("产品销售贡献", "比较不同产品的销售额及占比。"),
        Operation.REGION: ("地区销售对比", "按地区汇总销售额并比较差异。"),
    }
    title, description = titles[operation]
    return AnalysisTask(title=title, description=description, operation=operation)


class PlannerInput(BaseModel):
    intent: IntentArtifact | Intent
    profile: DatasetProfile | DataProfile


class MockAnalysisPlanner(Node[PlannerInput, Plan]):
    name = "analysis_planner"

    async def process(self, payload: PlannerInput) -> Plan:
        return Plan(version=1, tasks=[make_task(op) for op in (
            Operation.SUMMARY, Operation.TREND, Operation.CATEGORY
        )], reason="基于固定销售示例生成的初始 Mock 计划。")
