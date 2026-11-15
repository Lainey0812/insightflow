"""Strict model transport validation, using the existing plan and capability schemas."""
from pydantic import ValidationError

from app.domain.analysis_plan import PlannerDraft
from app.domain.errors import AppError
from app.intent.validation import strict_json


def request_schema(registry):
    schema = registry.request_schema()
    # Equivalent nonblank constraint for full-match structured decoders. Domain
    # schemas, Registry and downstream contracts stay unchanged.
    def visit(node):
        if isinstance(node, dict):
            if node.get("pattern") == r"\S":
                node["pattern"] = r"[\s\S]*\S[\s\S]*"
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(schema)
    return schema


def validate_draft(text, registry):
    if not isinstance(text, str):
        raise AppError("PLANNER_SCHEMA_INVALID", "规划输出必须为JSON文本。", 502, details={"stage": "schema"})
    try:
        size = len(text.encode("utf-8"))
        if size > 128 * 1024:
            raise AppError("PLANNER_OUTPUT_TOO_LARGE", "规划输出超过128 KiB。", 502, details={"stage": "schema"})
        payload = strict_json(text)
        import json
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise AppError("PLANNER_INVALID_JSON", "规划模型未返回合法且唯一键的JSON。", 502, details={"stage": "json"}) from None
    try:
        draft = PlannerDraft.model_validate(payload)
        ids = [t.task_id for t in draft.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate task IDs")
        for task in draft.tasks:
            for step in task.steps:
                spec = registry.operations.get(step.operation)
                if spec is None:
                    raise ValueError("Undeclared operation")
                spec.params_model.model_validate(step.params)
    except (ValidationError, ValueError, TypeError):
        raise AppError("PLANNER_SCHEMA_INVALID", "规划字段、操作参数、枚举或唯一ID不符合Schema。", 502,
                       details={"stage": "schema"}) from None
    if not any(t.priority == "P0" for t in draft.tasks):
        raise AppError("PLANNER_BUSINESS_INVALID", "计划未保留任何核心P0任务，未生成可审批计划。", 502,
                       details={"stage": "business"})
    return draft
