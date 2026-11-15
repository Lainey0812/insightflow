import asyncio
import json
import logging
from uuid import uuid4

from app.domain.dataset_profile import DatasetProfile, DatasetRef
from app.domain.errors import AppError
from app.domain.intent import IntentArtifact, LLMMetadata, ParsedIntent
from app.domain.provenance import Provenance
from app.intent.context import build_dataset_context
from app.intent.prompt import PROMPT_VERSION, SYSTEM_PROMPT
# Re-export strict_json for existing Planner/Report imports; no downstream change required.
from app.intent.validation import strict_json, validate_output
from app.llm.base import LLMProvider, LLMRequest

logger = logging.getLogger("app.intent")
RETRYABLE = {"LLM_INVALID_JSON", "INTENT_SCHEMA_INVALID", "INTENT_SEMANTIC_INVALID", "LLM_UNGROUNDED_OUTPUT",
             "LLM_INVALID_OUTPUT", "LLM_INCOMPLETE_OUTPUT", "INTENT_OUTPUT_TOO_LARGE"}
MAX_REQUEST_BYTES = 96 * 1024
PROVIDER_ERRORS = {
    "LLM_NOT_CONFIGURED": ("尚未配置模型地址和模型名，无法识别分析意图。", 503),
    "LLM_TIMEOUT": ("模型调用超时，未生成意图结果。", 504),
    "LLM_UNAVAILABLE": ("无法连接模型服务，请检查配置。", 502),
    "LLM_HTTP_ERROR": ("模型服务返回错误，未生成意图结果。", 502),
    "LLM_RATE_LIMITED": ("模型服务暂时限流，请稍后重试。", 503),
    "LLM_REFUSED": ("模型拒绝处理本次需求。", 502),
    "LLM_INCOMPLETE_OUTPUT": ("模型输出未完整结束。", 502),
    "LLM_INVALID_OUTPUT": ("模型响应协议结构不正确。", 502),
    "LLM_SCHEMA_REQUIRED": ("模型请求缺少结构化 Schema。", 500),
    "LLM_CALL_FAILED": ("模型调用失败，未生成意图结果。", 502),
}


class IntentParserService:
    def __init__(self, provider: LLMProvider, timeout_seconds: float = 30, *, max_attempts: int = 2,
                 enable_thinking: bool | None = None):
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Intent timeout must be within (0, 300]")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("Intent max_attempts must be an integer within [1, 3]")
        if enable_thinking is not None and type(enable_thinking) is not bool:
            raise ValueError("Intent enable_thinking must be boolean or None")
        self.provider, self.timeout_seconds, self.max_attempts = provider, timeout_seconds, max_attempts
        self.enable_thinking = enable_thinking

    async def _generate(self, request):
        # A replaceable adapter must not leak arbitrary exception messages, bodies or credentials.
        try:
            return await self.provider.generate(request)
        except AppError as exc:
            code = exc.error.code if exc.error.code in PROVIDER_ERRORS else "LLM_CALL_FAILED"
            message, status = PROVIDER_ERRORS[code]
            raise AppError(code, message, status, details={"stage": "call"}) from None
        except TimeoutError:
            raise AppError("LLM_TIMEOUT", PROVIDER_ERRORS["LLM_TIMEOUT"][0], 504, details={"stage": "call"}) from None
        except Exception:
            raise AppError("LLM_CALL_FAILED", PROVIDER_ERRORS["LLM_CALL_FAILED"][0], 502, details={"stage": "call"}) from None

    async def parse(self, user_query: str, profile: DatasetProfile | None,
                    clarification_answers: list[str] | None = None) -> IntentArtifact:
        context = build_dataset_context(profile)
        if (not isinstance(user_query, str) or
                (clarification_answers is not None and (not isinstance(clarification_answers, list) or
                 len(clarification_answers) > 10 or any(not isinstance(x, str) or len(x) > 2000 for x in clarification_answers)))):
            raise AppError("INTENT_INPUT_INVALID", "需求和澄清答复必须是规定长度内的文本。", 422)
        answers = list(clarification_answers or [])
        sources = [user_query, *answers]
        try:
            for source in sources:
                source.encode("utf-8")
        except UnicodeError:
            raise AppError("INTENT_INPUT_INVALID", "需求或澄清答复包含无效 Unicode 文本。", 422) from None
        if len(user_query) > 2000 or sum(map(len, sources)) > 8000:
            raise AppError("INTENT_INPUT_TOO_LONG", "需求或累计澄清内容过长。", 422)
        dataset_ref = DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version)
        parse_id, attempts = uuid4().hex, 0

        def artifact(result, response=None):
            return IntentArtifact(**result.model_dump(), user_query=user_query, clarification_answers=answers,
                dataset_ref=dataset_ref, parse_origin="llm" if response else "input_guard",
                llm=LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock) if response else None,
                parser_version="1.1", prompt_version=PROMPT_VERSION, llm_attempts=attempts, parse_id=parse_id,
                provenance=Provenance(source=("mock" if response.is_mock else "llm") if response else "input_guard",
                    dataset=profile.dataset_id, dataset_version=profile.dataset_version,
                    notice="结构化意图识别；约束未验证，未生成任务或计算结果。" if response else "空输入校验：等待用户补充，未调用模型。"))

        if not any(source.strip() for source in sources):
            logger.info("Intent requires input", extra={"event": "intent_guard", "parse_id": parse_id,
                "attempt": 0, "prompt_version": PROMPT_VERSION})
            return artifact(ParsedIntent.model_validate({
                "analysis_mode": "undetermined", "next_action": "clarify",
                "analysis_goal": {"analysis_object": None, "business_goal": None, "decision_goal": None},
                "constraints": {"time_range": None, "filters": [], "metric_requirements": [], "analysis_limits": []},
                "uncertainties": [{"id": "missing_query", "issue": "尚未提供分析需求。",
                    "reason": "无法确定需要开展什么分析。", "action": "clarify", "resolve_at": "before_planning"}],
                "clarification_questions": ["你希望分析什么问题，还是先探索这份数据的主要特征和规律？"]}))

        data = {"user_query": user_query, "clarification_answers": answers, "dataset_context": context.model_dump()}
        failure = None
        try:
            # One total deadline, including validation retries. A retry never doubles the timeout.
            async with asyncio.timeout(self.timeout_seconds):
                for attempts in range(1, self.max_attempts + 1):
                    instruction_data = dict(data)
                    if failure:
                        instruction_data["validation_feedback"] = {"previous_error_code": failure.error.code,
                            "stage": failure.error.details.get("stage", "call"),
                            "instruction": "按同一用户原话和系统规则重新生成完整 JSON；不要补造信息，不要输出解释。"}
                        if failure.error.code == "LLM_UNGROUNDED_OUTPUT":
                            instruction_data["validation_feedback"]["instruction"] = (
                                "约束raw_text只摘录一段真实连续原话；不要改写或把两处片段接成新句。"
                                "未知筛选值留在uncertainty，不补造值。目标和不确定性解释允许忠实改写。"
                                "重新生成完整JSON，不输出检查过程。")
                    instruction = json.dumps(instruction_data, ensure_ascii=False)
                    if len(instruction.encode("utf-8")) > MAX_REQUEST_BYTES:
                        raise AppError("INTENT_REQUEST_TOO_LARGE", "当前意图上下文请求超过 96 KiB，未发送本次调用。", 422,
                            details={"stage": "input", "attempts": attempts - 1, "parse_id": parse_id})
                    request = LLMRequest(purpose="intent_v1", system_prompt=SYSTEM_PROMPT,
                        instruction=instruction, response_schema=ParsedIntent.model_json_schema(),
                        enable_thinking=self.enable_thinking)
                    try:
                        response = await self._generate(request)
                        result = validate_output(response.text, sources)
                    except AppError as exc:
                        exc.error.details = {"stage": "call", **exc.error.details, "attempts": attempts, "parse_id": parse_id}
                        logger.info("Intent attempt failed", extra={"event": "intent_attempt", "parse_id": parse_id,
                            "stage": exc.error.details["stage"], "error_code": exc.error.code, "attempt": attempts,
                            "prompt_version": PROMPT_VERSION})
                        if exc.error.code not in RETRYABLE or attempts == self.max_attempts:
                            raise
                        failure = exc
                        continue
                    except Exception:
                        raise AppError("LLM_CALL_FAILED", "模型调用失败，未生成意图结果。", 502,
                            details={"stage": "call", "attempts": attempts, "parse_id": parse_id}) from None
                    logger.info("Intent parsed", extra={"event": "intent_success", "parse_id": parse_id,
                        "attempt": attempts, "prompt_version": PROMPT_VERSION})
                    return artifact(result, response)
        except TimeoutError:
            logger.info("Intent timed out", extra={"event": "intent_attempt", "parse_id": parse_id,
                "stage": "call", "error_code": "LLM_TIMEOUT", "attempt": attempts, "prompt_version": PROMPT_VERSION})
            raise AppError("LLM_TIMEOUT", "意图模型调用超过总时间限制，未生成意图结果。", 504,
                details={"stage": "call", "attempts": attempts, "parse_id": parse_id}) from None
        raise AssertionError("Intent retries exhausted without an outcome")
