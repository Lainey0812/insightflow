import httpx

from app.domain.errors import AppError
from .base import LLMRequest, LLMResponse


class UnconfiguredLLMProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise AppError("LLM_NOT_CONFIGURED", "尚未配置 LLM Provider，无法识别分析意图；请配置模型接口后重试。", 503)


class CompatibleLLMProvider:
    """Minimal Chat Completions JSON-Schema adapter. No implicit mock or JSON-mode fallback."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 30,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key, self.timeout, self.transport = model, api_key, timeout, transport

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if request.response_schema is None:
            raise AppError("LLM_SCHEMA_REQUIRED", "结构化模型请求缺少输出 Schema。", 500)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": request.system_prompt},
                         {"role": "user", "content": request.instruction}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": request.purpose, "strict": True, "schema": request.response_schema}},
            "stream": False,
        }
        if request.enable_thinking is not None:
            payload["enable_thinking"] = request.enable_thinking
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=False,
                                         trust_env=False) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise AppError("LLM_TIMEOUT", "模型调用超时，请稍后重试。", 504) from None
        except httpx.RequestError:
            raise AppError("LLM_UNAVAILABLE", "无法连接模型服务，请检查配置或稍后重试。", 502) from None
        if response.status_code >= 300:
            code = "LLM_RATE_LIMITED" if response.status_code == 429 else "LLM_HTTP_ERROR"
            raise AppError(code, "模型服务返回错误，未生成意图结果。", 503 if response.status_code == 429 else 502)
        if len(response.content) > 256 * 1024:
            raise AppError("LLM_INVALID_OUTPUT", "模型响应超出大小限制。", 502)
        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            if message.get("refusal"):
                raise AppError("LLM_REFUSED", "模型拒绝处理本次需求，未生成意图结果。", 502)
            if choice.get("finish_reason") != "stop":
                raise AppError("LLM_INCOMPLETE_OUTPUT", "模型输出未完整结束，未生成意图结果。", 502)
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing text content")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise AppError("LLM_INVALID_OUTPUT", "模型响应结构不正确。", 502) from None
        return LLMResponse(text=content, provider="compatible", model=self.model, is_mock=False)
