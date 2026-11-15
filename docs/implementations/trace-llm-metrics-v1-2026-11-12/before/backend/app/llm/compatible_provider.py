import httpx
import hashlib
from urllib.parse import urlsplit, urlunsplit

from app.domain.errors import AppError
from .base import LLMRequest, LLMResponse


class UnconfiguredLLMProvider:
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise AppError("LLM_NOT_CONFIGURED", "尚未配置 LLM Provider，无法识别分析意图；请配置模型接口后重试。", 503)


class CompatibleLLMProvider:
    """Minimal Chat Completions JSON-Schema adapter. No implicit mock or JSON-mode fallback."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 30,
                 transport: httpx.AsyncBaseTransport | None = None, capture=None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key, self.timeout, self.transport = model, api_key, timeout, transport
        self.capture = capture

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = self.build_payload(request)
        handle = self.capture.begin(request,payload,{'endpoint_sha256':hashlib.sha256(self.url.encode()).hexdigest(),
            'timeout_seconds':self.timeout,'provider':type(self).__name__}) if self.capture else None
        try:
            response = await self._send(payload)
        except BaseException as error:
            if handle: self.capture.finish(handle,error=error)
            observed = getattr(error, 'observation', None)
            if not isinstance(observed, dict):
                error.observation = {'endpoint': redact_endpoint(self.url)}
            elif 'endpoint' not in observed:
                error.observation = {**observed, 'endpoint': redact_endpoint(self.url)}
            raise
        if handle:
            self.capture.finish(handle,response=response)
            response = response.model_copy(update={'call_id':handle[0].call_id,
                'request_snapshot_id':handle[0].request_snapshot_id,'template_snapshot_id':handle[0].template_snapshot_id})
        return response

    def build_payload(self, request):
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
        return payload

    async def _send(self, payload):
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=False,
                                         trust_env=False) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise AppError("LLM_TIMEOUT", "模型调用超时，请稍后重试。", 504) from None
        except httpx.RequestError:
            raise AppError("LLM_UNAVAILABLE", "无法连接模型服务，请检查配置或稍后重试。", 502) from None
        try:
            return self._parse(response)
        except AppError as error:
            # Kept for the controlled response snapshot; never logged or returned to the business caller.
            error.raw_response = response.text
            observed = getattr(error, 'observation', None) or {}
            error.observation = {'http_status': response.status_code, 'endpoint': redact_endpoint(self.url), **observed}
            raise

    def _parse(self, response):
        if response.status_code >= 300:
            code = "LLM_RATE_LIMITED" if response.status_code == 429 else "LLM_HTTP_ERROR"
            error = AppError(code, "模型服务返回错误，未生成意图结果。", 503 if response.status_code == 429 else 502)
            error.observation = {'http_status': response.status_code, 'endpoint': redact_endpoint(self.url)}
            raise error
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
        return LLMResponse(text=content, provider="compatible", model=self.model, is_mock=False,
            http_status=response.status_code, endpoint=redact_endpoint(self.url), usage=read_usage(body))


def provider_observation(client_config, url):
    """Show the configured endpoint only when this call's saved hash matches it."""
    stored = client_config.get('endpoint_sha256') if isinstance(client_config, dict) else None
    if not isinstance(url, str) or not url or not isinstance(stored, str):
        return {}
    if hashlib.sha256(url.encode()).hexdigest() != stored:
        return {}
    return {'endpoint': redact_endpoint(url)}


def redact_endpoint(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    if parts.port:
        host = f'{host}:{parts.port}'
    return urlunsplit((parts.scheme, host, parts.path, '', ''))


def read_usage(body):
    usage = body.get('usage') if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return {}
    result = {}

    def number(*keys):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                continue
            return value
        return None

    prompt = number('prompt_tokens', 'input_tokens')
    completion = number('completion_tokens', 'output_tokens')
    total = number('total_tokens')
    details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
    cached = None
    if isinstance(details, dict):
        for key in ('cached_tokens', 'cache_read_input_tokens'):
            value = details.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                continue
            cached = value
            break
    if cached is None:
        cached = number('cached_tokens')
    cost = None
    for key in ('estimated_cost', 'cost'):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            continue
        cost = value
        break
    if prompt is not None:
        result['input_tokens'] = prompt
    if completion is not None:
        result['output_tokens'] = completion
    if cached is not None:
        result['cached_tokens'] = cached
    if total is not None:
        result['total_tokens'] = total
    if cost is not None:
        result['estimated_cost'] = cost
    return result
