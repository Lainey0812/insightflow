from .base import LLMRequest, LLMResponse


class MockLLMProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="Mock 规划演示：使用预设任务，不调用真实模型。",
                           provider="mock", is_mock=True)
