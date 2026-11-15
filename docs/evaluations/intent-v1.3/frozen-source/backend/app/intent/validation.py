"""Deterministic output checks. Grounding is traceability, not general semantic proof."""
import json

from pydantic import ValidationError

from app.domain.errors import AppError
from app.domain.intent import ParsedIntent

MAX_OUTPUT_BYTES = 64 * 1024
SAFE_FIELDS = {"analysis_mode", "next_action", "analysis_goal", "analysis_object", "business_goal", "decision_goal",
               "constraints", "time_range", "filters", "metric_requirements", "analysis_limits", "raw_text",
               "validation_status", "uncertainties", "id", "issue", "reason", "description", "impact", "action",
               "resolve_at", "clarification_questions"}


def strict_json(text: str):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Non-JSON numeric constant")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def fail(code, message, stage):
    return AppError(code, message, 502, details={"stage": stage})


def validate_grounding(result: ParsedIntent, sources: list[str]) -> None:
    """Exact spans apply to extracted constraints and decision evidence only.

    Goals and uncertainty explanations may paraphrase; this is not a semantic
    entailment validator. Never joins sources or accepts invented filter values.
    """
    invalid = []
    for category in ("time_range", "filters", "metric_requirements", "analysis_limits"):
        values = getattr(result.constraints, category)
        if category == "time_range":
            values = [values] if values else []
        for index, item in enumerate(values):
            if not any(item.raw_text in source for source in sources):
                path = ["constraints", category]
                if category != "time_range":
                    path.append(index)
                invalid.append({"type": "non_contiguous_source_span", "path": path + ["raw_text"]})
    if invalid:
        error = fail("LLM_UNGROUNDED_OUTPUT", "约束 raw_text 必须来自一段连续用户原话，不能改写、接句或补造筛选值。", "semantic")
        error.error.details["validation_errors"] = invalid[:5]
        raise error
    decision = result.analysis_goal.decision_goal
    if decision is not None and not any(decision in source for source in sources):
        raise fail("LLM_UNGROUNDED_OUTPUT", "模型输出的决策目的缺少用户原话依据。", "semantic")


def validate_output(text: str, sources: list[str]) -> ParsedIntent:
    if not isinstance(text, str):
        raise fail("INTENT_SCHEMA_INVALID", "意图模型输出必须是 JSON 文本。", "schema")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise fail("LLM_INVALID_JSON", "意图模型输出含无效 Unicode 文本。", "json") from None
    if size > MAX_OUTPUT_BYTES:
        raise fail("INTENT_OUTPUT_TOO_LARGE", "意图模型输出无效或超过 64 KiB。", "schema")
    try:
        payload = strict_json(text)
        # JSON escapes can carry lone surrogates that would fail later HTTP serialization.
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise fail("LLM_INVALID_JSON", "意图模型未返回合法且唯一键的 JSON。", "json") from None
    try:
        result = ParsedIntent.model_validate(payload)
    except ValidationError as exc:
        # Model validators encode action/phase/flow rules; field validators handle structure.
        semantic = any(item["type"] == "value_error" for item in exc.errors(include_input=False))
        code = "INTENT_SEMANTIC_INVALID" if semantic else "INTENT_SCHEMA_INVALID"
        message = "意图模型输出的澄清状态或不确定性规则冲突。" if semantic else "意图模型输出的字段、枚举或约束结构不符合 Schema。"
        error = fail(code, message, "semantic" if semantic else "schema")
        error.error.details["validation_errors"] = [{"type": item["type"],
            "path": [part if isinstance(part, int) or part in SAFE_FIELDS else "<extra_field>" for part in item["loc"]]}
            for item in exc.errors(include_input=False, include_context=False)[:5]]
        raise error from None
    validate_grounding(result, sources)
    return result
