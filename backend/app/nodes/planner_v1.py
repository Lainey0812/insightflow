from pydantic import BaseModel

from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.intent import IntentArtifact, ParsedIntent
from app.domain.provenance import Provenance
from app.services.analysis_planner import AnalysisPlannerService
from .base import Node


class PlannerV1Input(BaseModel):
    intent: IntentArtifact | ParsedIntent
    profile: DatasetProfile


class AnalysisPlannerNode(Node[PlannerV1Input, ValidatedAnalysisPlan]):
    """Callable by the orchestrator; never routed to the legacy Mock Engine."""
    name = "analysis_planner_v1"
    error_provenance = Provenance(source="llm", dataset="unavailable", notice="规划失败，未使用 Mock 计划替代。")

    def __init__(self, planner: AnalysisPlannerService):
        self.planner = planner

    async def process(self, payload: PlannerV1Input) -> ValidatedAnalysisPlan:
        return await self.planner.plan(payload.intent, payload.profile)
