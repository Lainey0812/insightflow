from typing import Annotated

from fastapi import APIRouter
from pydantic import Field, StrictStr

from app.domain.dataset_profile import DatasetRef
from app.domain.intent import IntentArtifact, IntentModel
from app.services.intent_parser import IntentParserService
from app.storage.dataset_repository import DatasetRepository


class IntentRequest(IntentModel):
    user_query: Annotated[StrictStr, Field(max_length=2000)]
    dataset_ref: DatasetRef | None = None
    clarification_answers: list[Annotated[StrictStr, Field(max_length=2000)]] = Field(default_factory=list, max_length=10)


def create_intent_router(parser: IntentParserService, datasets: DatasetRepository) -> APIRouter:
    router = APIRouter(prefix="/api/v1/intents", tags=["Intent Parser V1"])

    @router.post("/parse", response_model=IntentArtifact)
    async def parse_intent(request: IntentRequest):
        profile = datasets.profile(request.dataset_ref.dataset_id, request.dataset_ref.dataset_version) if request.dataset_ref else None
        return await parser.parse(request.user_query, profile, request.clarification_answers)

    return router
