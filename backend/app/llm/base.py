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
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
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
    for key in ('temperature', 'top_p', 'max_tokens'):
        value = getattr(response, key, None)
        if value is not None:
            data[key] = value
    for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'total_tokens', 'estimated_cost'):
        if key in response.usage:
            data[key] = response.usage[key]
    return data


def recorded_metrics(response=None, error=None):
    data = llm_observation(response) if response is not None else {}
    raw = getattr(error, 'observation', None) if error is not None else None
    if isinstance(raw, dict):
        for key, value in raw.items():
            data.setdefault(key, value)
    usage = {key: data[key] for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'total_tokens', 'estimated_cost') if key in data}
    return data.get('http_status'), data.get('endpoint'), usage


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
