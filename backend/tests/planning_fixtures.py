import json

from app.llm.base import LLMResponse
from app.profiling.profiler import build_profile

CSV = '城市,薪资区间,薪资,发布日期,JD\n上海,20-30K,25,2026-01-02,Python\n北京,30-40K,35,2026-02-03,SQL\n上海,20-30K,25,2025-12-01,Python\n'.encode()


def recruiting_profile():
    return build_profile(CSV, ".csv", "recruiting", "recruiting.csv")


def step(operation="group_aggregate", params=None, sid="S01"):
    return {"step_id": sid, "operation": operation, "params": params if params is not None else {
        "dimensions": ["field_0001"], "metrics": [{"function": "count", "alias": "job_count"}]}}


def task(steps=None, tid="A01", priority="P0"):
    return {"task_id": tid, "title": "城市岗位数量", "business_question": "不同城市岗位有何差异？",
        "priority": priority, "priority_reason": "删除后无法比较城市岗位数量，核心问题将无法回答。",
        "requirement_ids": ["C01"] if priority == "P0" else [], "depends_on": [], "missing_inputs": [],
        "steps": steps if steps is not None else [step()]}


def plan(tasks=None, profile=None):
    profile = profile or recruiting_profile()
    return {"plan_id": "test_plan", "dataset_id": profile.dataset_id, "dataset_version": profile.dataset_version,
        "plan_version": 1, "tasks": tasks if tasks is not None else [task()],
        "core_requirements": [{"requirement_id": "C01", "description": "比较城市岗位数量"}]}


class PlannerProvider:
    """Scripted output tests verify contracts, not real LLM business judgment."""
    def __init__(self, *outputs):
        self.outputs = list(outputs) or [{"tasks": [task()]}]
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        output = self.outputs[min(len(self.requests) - 1, len(self.outputs) - 1)]
        if isinstance(output, Exception):
            raise output
        return LLMResponse(text=output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
                           provider="scripted-planner", is_mock=True, model="contract-fixture")
