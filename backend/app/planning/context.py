"""Planner input built from existing contracts; no rows, samples or derived semantics."""
import json

from app.domain.analysis_plan import CoreRequirement
from app.intent.context import build_dataset_context
from app.domain.errors import AppError


def planner_context(intent, profile, registry):
    build_dataset_context(profile)
    requirements = [CoreRequirement(requirement_id="C01", description=intent.analysis_goal.business_goal)]
    descriptions = []
    if intent.analysis_goal.decision_goal:
        descriptions.append(intent.analysis_goal.decision_goal)
    for category in ("time_range", "filters", "metric_requirements", "analysis_limits"):
        items = getattr(intent.constraints, category)
        items = [items] if category == "time_range" and items else items or []
        if items:
            descriptions.append(category + "：" + "；".join(x.raw_text for x in items))
    if any(len(text) > 2000 for text in descriptions):
        raise AppError("PLANNER_CONTEXT_TOO_LARGE", "显式需求过长，未截断或调用模型。", 422)
    requirements += [CoreRequirement(requirement_id=f"C{i:02d}", description=text)
                     for i, text in enumerate(descriptions, 2)]
    context = {"intent": intent.model_dump(mode="json", by_alias=True),
        "core_requirements": [r.model_dump() for r in requirements],
        "profile": {"dataset_id": profile.dataset_id, "dataset_version": profile.dataset_version,
            "file_name": profile.file_name, "row_count": profile.row_count,
            "fields": [{"field_id": f.field_id, "name": f.display_name,
                "logical_type": f.logical_type.value, "physical_type": f.physical_type.value,
                "non_missing_count": f.non_missing_count, "missing_rate": f.missing_rate,
                "unique_count": f.unique_count} for f in profile.fields],
            "quality_issues": [{"code": i.code, "field_ids": i.field_ids} for i in profile.quality_issues]},
        "capabilities": registry.summary()}
    # No invented semantic_tags: the current profile contract does not have them.
    try:
        size = len(json.dumps(context, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, UnicodeError):
        raise AppError("PLANNER_INTENT_INVALID", "规划输入包含无效文本或数值。", 422) from None
    if size > 128 * 1024:
        raise AppError("PLANNER_CONTEXT_TOO_LARGE", "规划上下文过大，未调用模型。", 422)
    return context, requirements
