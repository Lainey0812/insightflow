from pydantic import BaseModel

from pydantic import Field
from app.domain.dataset_profile import DatasetProfile
from app.domain.intent import IntentArtifact
from app.domain.provenance import Provenance
from app.services.intent_parser import IntentParserService
from .base import Node


class IntentInput(BaseModel):
    user_query: str
    profile: DatasetProfile
    clarification_answers: list[str] = Field(default_factory=list)


class IntentParserNode(Node[IntentInput, IntentArtifact]):
    name = "intent_parser"
    error_provenance = Provenance(source="llm", dataset="unavailable", notice="意图识别失败，未用 Mock 结果替代。")

    def __init__(self, parser: IntentParserService):
        self.parser = parser

    async def process(self, payload: IntentInput) -> IntentArtifact:
        return await self.parser.parse(payload.user_query, payload.profile, payload.clarification_answers)
