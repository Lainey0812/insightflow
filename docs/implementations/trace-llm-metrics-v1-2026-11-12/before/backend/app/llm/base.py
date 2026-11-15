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
    http_status: int | None = None
    endpoint: str | None = None
    usage: dict[str, int | float] = Field(default_factory=dict)
    call_id: str | None = Field(default=None,exclude=True)
    request_snapshot_id: str | None = Field(default=None,exclude=True)
    template_snapshot_id: str | None = Field(default=None,exclude=True)


def llm_observation(response: LLMResponse) -> dict:
    """Only values the provider actually returned. Missing usage stays absent."""
    data = {}
    if response.http_status is not None:
        data['http_status'] = response.http_status
    if response.endpoint:
        data['endpoint'] = response.endpoint
    for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'total_tokens', 'estimated_cost'):
        if key in response.usage:
            data[key] = response.usage[key]
    return data


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
