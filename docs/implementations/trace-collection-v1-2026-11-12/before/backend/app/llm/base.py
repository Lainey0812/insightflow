from typing import Any, Protocol

from pydantic import BaseModel, StrictBool, Field
from app.domain.prompt_registry import CallBinding


class LLMRequest(BaseModel):
    purpose: str
    instruction: str
    system_prompt: str = ""
    response_schema: dict[str, Any] | None = None
    enable_thinking: StrictBool | None = None
    call_binding: CallBinding | None = Field(default=None, exclude=True, repr=False)


class LLMResponse(BaseModel):
    text: str
    provider: str
    is_mock: bool
    model: str | None = None
    call_id: str | None = Field(default=None,exclude=True)
    request_snapshot_id: str | None = Field(default=None,exclude=True)
    template_snapshot_id: str | None = Field(default=None,exclude=True)


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
