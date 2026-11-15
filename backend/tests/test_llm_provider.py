import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.llm.base import LLMRequest
from app.llm.compatible_provider import CompatibleLLMProvider, UnconfiguredLLMProvider
from app.llm.factory import create_provider
from intent_fixtures import intent_payload


def request():
    return LLMRequest(purpose="intent_v1", instruction='{"user_query":"分析数据"}',
                      system_prompt="interpret only", response_schema=ParsedIntent.model_json_schema())


def test_compatible_provider_uses_structured_schema_and_separate_system_data_messages():
    captured = []
    def handler(http_request):
        captured.append(http_request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(intent_payload()), "refusal": None}}]})
    provider = CompatibleLLMProvider("https://llm.example.test/v1", "configured-model", "test-secret", transport=httpx.MockTransport(handler))
    output = asyncio.run(provider.generate(request()))
    assert not output.is_mock and output.model == "configured-model"
    sent = json.loads(captured[0].content)
    assert str(captured[0].url) == "https://llm.example.test/v1/chat/completions"
    assert captured[0].headers["Authorization"] == "Bearer test-secret"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["schema"] == ParsedIntent.model_json_schema()
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert "tools" not in sent


@pytest.mark.parametrize("status,code", [(401, "LLM_HTTP_ERROR"), (429, "LLM_RATE_LIMITED"), (500, "LLM_HTTP_ERROR"), (302, "LLM_HTTP_ERROR")])
def test_upstream_errors_do_not_expose_bodies_or_secrets(status, code):
    provider = CompatibleLLMProvider("https://llm.example.test/v1", "model", "test-secret",
        transport=httpx.MockTransport(lambda req: httpx.Response(status, text="test-secret upstream diagnostics")))
    with pytest.raises(AppError) as error:
        asyncio.run(provider.generate(request()))
    assert error.value.error.code == code
    assert "test-secret" not in error.value.error.message


@pytest.mark.parametrize("body,code", [
    ({"choices": []}, "LLM_INVALID_OUTPUT"),
    ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, "LLM_INCOMPLETE_OUTPUT"),
    ({"choices": [{"finish_reason": "stop", "message": {"refusal": "no", "content": None}}]}, "LLM_REFUSED"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": None}}]}, "LLM_INVALID_OUTPUT"),
    ({"choices": [{"finish_reason": "stop", "message": None}]}, "LLM_INVALID_OUTPUT"),
])
def test_incomplete_refused_or_malformed_response_is_error(body, code):
    provider = CompatibleLLMProvider("https://llm.example.test/v1", "model",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
    with pytest.raises(AppError) as error:
        asyncio.run(provider.generate(request()))
    assert error.value.error.code == code


def test_timeout_and_connect_failure_are_distinct():
    for exception, code in [(httpx.ReadTimeout("secret"), "LLM_TIMEOUT"), (httpx.ConnectError("secret"), "LLM_UNAVAILABLE")]:
        def handler(req):
            raise exception
        provider = CompatibleLLMProvider("https://llm.example.test/v1", "model", transport=httpx.MockTransport(handler))
        with pytest.raises(AppError) as error:
            asyncio.run(provider.generate(request()))
        assert error.value.error.code == code


def test_factory_has_no_implicit_mock_fallback(tmp_path):
    assert isinstance(create_provider(Settings(tmp_path)), UnconfiguredLLMProvider)
    assert isinstance(create_provider(Settings(tmp_path, llm_base_url="https://llm.example.test/v1", llm_model="chosen-model")), CompatibleLLMProvider)


def test_output_schema_requires_all_properties_including_nullable_fields():
    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)
    inspect(ParsedIntent.model_json_schema())


@pytest.mark.parametrize('enabled', [None, False, True])
def test_thinking_extension_is_explicit_per_request(enabled):
    captured = []
    def handler(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(intent_payload())}}]})
    provider = CompatibleLLMProvider('https://llm.example.test/v1', 'chosen-model', transport=httpx.MockTransport(handler))
    data = request().model_copy(update={'enable_thinking': enabled})
    asyncio.run(provider.generate(data))
    if enabled is None:
        assert 'enable_thinking' not in captured[0]
    else:
        assert captured[0]['enable_thinking'] is enabled
    assert captured[0]['response_format']['type'] == 'json_schema'


@pytest.mark.parametrize('value,expected', [('', None), ('false', False), ('true', True), ('0', False), ('1', True)])
def test_intent_thinking_environment_is_optional(monkeypatch, value, expected):
    monkeypatch.setenv('INSIGHTFLOW_INTENT_ENABLE_THINKING', value)
    assert Settings.from_env().intent_enable_thinking is expected


def test_invalid_thinking_environment_does_not_echo_value(monkeypatch):
    monkeypatch.setenv('INSIGHTFLOW_INTENT_ENABLE_THINKING', 'private-config-value')
    with pytest.raises(ValueError) as caught:
        Settings.from_env()
    assert 'private-config-value' not in str(caught.value)


def test_generation_parameters_are_sent_and_usage_is_priced_when_configured():
    captured = []
    body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(intent_payload())}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                      "prompt_tokens_details": {"cached_tokens": 2}}}
    def handler(http_request):
        captured.append(json.loads(http_request.content))
        return httpx.Response(200, json=body)
    provider = CompatibleLLMProvider("https://llm.example.test/v1", "configured-model", transport=httpx.MockTransport(handler),
        temperature=0.7, top_p=0.8, max_tokens=8192, input_usd_per_million=1, output_usd_per_million=2)
    output = asyncio.run(provider.generate(request()))
    assert captured[0]["temperature"] == 0.7
    assert captured[0]["top_p"] == 0.8
    assert captured[0]["max_tokens"] == 8192
    assert output.http_status == 200
    assert output.temperature == 0.7
    assert output.usage["input_tokens"] == 11
    assert output.usage["output_tokens"] == 7
    assert output.usage["cached_tokens"] == 2
    assert output.usage["estimated_cost"] == pytest.approx((11 + 14) / 1_000_000)


def test_factory_sends_the_configured_generation_parameters(tmp_path):
    provider = create_provider(Settings(tmp_path, llm_base_url="https://llm.example.test/v1", llm_model="chosen-model"))
    assert provider.temperature == 0.7 and provider.top_p == 0.8 and provider.max_tokens == 8192


def test_saved_endpoint_hash_resolves_only_the_matching_provider():
    from app.llm.compatible_provider import provider_observation
    url = "https://user:test-secret@llm.example.test/v1/chat/completions"
    digest = __import__('hashlib').sha256(url.encode()).hexdigest()
    assert provider_observation({'endpoint_sha256': digest}, url) == {
        'endpoint': 'https://llm.example.test/v1/chat/completions'}
    assert provider_observation({'endpoint_sha256': '0' * 64}, url) == {}
    assert provider_observation({}, url) == {}


def test_provider_keeps_usage_status_and_strips_endpoint_secrets():
    body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(intent_payload())}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                      "prompt_tokens_details": {"cached_tokens": 3}, "estimated_cost": 0.01}}
    provider = CompatibleLLMProvider("https://user:test-secret@llm.example.test/v1", "configured-model", "test-secret",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
    output = asyncio.run(provider.generate(request()))
    assert output.http_status == 200
    assert output.endpoint == "https://llm.example.test/v1/chat/completions"
    assert output.usage == {"input_tokens": 11, "output_tokens": 7, "cached_tokens": 3,
                             "total_tokens": 18, "estimated_cost": 0.01}
    assert "test-secret" not in output.endpoint


def test_missing_usage_is_not_recorded_as_zero():
    provider = CompatibleLLMProvider("https://llm.example.test/v1", "configured-model",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(intent_payload())}}]})))
    output = asyncio.run(provider.generate(request()))
    assert output.usage == {}
    assert output.http_status == 200


def test_http_error_keeps_status_without_the_secret():
    provider = CompatibleLLMProvider("https://user:test-secret@llm.example.test/v1", "model", "test-secret",
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="test-secret upstream diagnostics")))
    with pytest.raises(AppError) as error:
        asyncio.run(provider.generate(request()))
    assert error.value.observation["http_status"] == 500
    assert error.value.observation["endpoint"] == "https://llm.example.test/v1/chat/completions"
    assert "test-secret" not in error.value.error.message
    assert "test-secret" not in error.value.observation["endpoint"]


def test_failed_span_stores_status_and_frames_without_the_exception_text():
    from app.observability.recorder import SpanHandle, safe

    class Record:
        def __init__(self):
            self.status = "running"
            self.attributes = {}
            self.error_code = None
            self.error_message = None
            self.finished_at = None
            self.duration_ms = None

    class Context:
        run = None
        active = None
        node_attempts = {}
        def call(self, action):
            return False

    handle = SpanHandle(Context(), "intent_parser")
    handle.record = Record()
    handle.context = Context()
    try:
        raise AppError("LLM_HTTP_ERROR", "test-secret upstream diagnostics", 502)
    except AppError as error:
        error.observation = {"http_status": 502, "endpoint": "https://llm.example.test/v1/chat/completions"}
        handle.finish(error)
    assert handle.record.attributes["http_status"] == 502
    assert handle.record.attributes["endpoint"] == "https://llm.example.test/v1/chat/completions"
    assert "AppError" in handle.record.attributes["error_stack"]
    assert "LLM_HTTP_ERROR" in handle.record.attributes["error_stack"]
    assert "test-secret" not in handle.record.attributes["error_stack"]
    assert "test-secret" not in handle.record.error_message
    assert len(safe({"error_stack": "x" * 500})["error_stack"]) == 500
    assert len(safe({"model": "x" * 500})["model"]) == 160
