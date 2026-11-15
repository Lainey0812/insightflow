from typing import Any

from fastapi import APIRouter

from app.domain.analysis_plan import PlanModel, ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetRef
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, ParsedIntent
from app.planning.capabilities import CapabilityRegistry
from app.planning.validator import PlanValidator
from app.services.analysis_planner import AnalysisPlannerService
from app.storage.dataset_repository import DatasetRepository


class GeneratePlanRequest(PlanModel):
    intent: IntentArtifact | ParsedIntent
    dataset_ref: DatasetRef | None = None


class ValidatePlanRequest(PlanModel):
    dataset_ref: DatasetRef
    plan: dict[str, Any]


def create_plan_router(planner: AnalysisPlannerService, datasets: DatasetRepository, registry: CapabilityRegistry):
    router = APIRouter(prefix="/api/v1", tags=["Analysis Planner V1"])
    validator = PlanValidator(registry)

    @router.get("/capabilities")
    def capabilities():
        return registry.summary()

    @router.post("/plans/generate", response_model=ValidatedAnalysisPlan)
    async def generate(request: GeneratePlanRequest):
        ref = request.dataset_ref or (request.intent.dataset_ref if isinstance(request.intent, IntentArtifact) else None)
        if ref is None:
            raise AppError("DATASET_CONTEXT_REQUIRED", "请提供已保存画像的数据集版本引用。", 422)
        profile = datasets.profile(ref.dataset_id, ref.dataset_version)
        return await planner.plan(request.intent, profile)

    @router.post("/plans/validate", response_model=ValidatedAnalysisPlan)
    def validate(request: ValidatePlanRequest):
        profile = datasets.profile(request.dataset_ref.dataset_id, request.dataset_ref.dataset_version)
        return validator.validate(request.plan, profile)

    return router
