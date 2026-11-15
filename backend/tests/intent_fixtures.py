import copy
import json

from app.llm.base import LLMResponse


def intent_payload(mode="goal_driven", action="proceed", business_goal="分析数据", analysis_object="数据"):
    result = {
        "analysis_mode": mode, "next_action": action,
        "analysis_goal": {"analysis_object": analysis_object, "business_goal": business_goal, "decision_goal": None},
        "constraints": {"time_range": None, "filters": [], "metric_requirements": [], "analysis_limits": []},
        "uncertainties": [], "clarification_questions": [],
    }
    if action == "clarify":
        result["uncertainties"] = [{"id": "missing_analysis", "description": "分析目标需要补充。",
            "impact": "无法制定合理计划。", "action": "clarify", "resolve_at": "before_planning"}]
        result["clarification_questions"] = ["你希望开展哪方面的分析？"]
    return result


class StubProvider:
    """Scripted transport fixture; never presented as a real language-understanding test."""
    def __init__(self, payload=None, error=None):
        self.payload = copy.deepcopy(payload if payload is not None else intent_payload())
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(text=text, provider="test-fixture", model="scripted", is_mock=True)
