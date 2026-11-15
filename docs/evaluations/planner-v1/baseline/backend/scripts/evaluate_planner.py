"""Opt-in evaluation with synthetic recruiting and sales metadata; never uploads local workbooks."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.llm.compatible_provider import UnconfiguredLLMProvider
from app.llm.factory import create_provider
from app.planning.capabilities import CapabilityRegistry
from app.profiling.profiler import build_profile
from app.services.analysis_planner import AnalysisPlannerService


def make_intent(goal):
    return ParsedIntent.model_validate({"analysis_mode": "goal_driven", "next_action": "proceed",
        "analysis_goal": {"analysis_object": "岗位" if "岗位" in goal or "薪资" in goal or "JD" in goal else "销售",
                          "business_goal": goal, "decision_goal": None},
        "constraints": {"time_range": None, "filters": [], "metric_requirements": [], "analysis_limits": []},
        "uncertainties": [], "clarification_questions": []})


def examples():
    jobs = build_profile('城市,薪资区间,发布日期,JD\n上海,20-30K,2026-01-01,Python\n北京,30-40K,2026-02-01,SQL\n'.encode(), ".csv", "synthetic-jobs", "synthetic-jobs.csv")
    sales = build_profile(b"region,revenue,date\neast,100,2026-01-01\nwest,200,2026-02-01\n", ".csv", "synthetic-sales", "synthetic-sales.csv")
    return [("city_count", "分析各城市岗位数量", jobs, "complete"),
            ("salary_text", "计算薪资区间的平均薪资，不能用其他指标替代", jobs, "blocked"),
            ("skills", "抽取JD技能并比较各城市岗位技能要求", jobs, "blocked"),
            ("sales_sum", "比较各地区销售额总和", sales, "complete"),
            ("sales_year", "按年份比较销售额总和", sales, "complete")]


def signature(output):
    # Structural stability diagnostic; wording differences do not create false failures.
    return sorted((t.priority, json.dumps([(s.operation, s.params) for s in t.steps], sort_keys=True, ensure_ascii=False))
                  for t in output.plan.tasks)


async def evaluate(args):
    settings = Settings.from_env()
    provider = create_provider(settings)
    if isinstance(provider, UnconfiguredLLMProvider):
        print("未配置模型：请先设置 INSIGHTFLOW_LLM_BASE_URL / INSIGHTFLOW_LLM_MODEL。", file=sys.stderr)
        return 2
    planner = AnalysisPlannerService(provider, CapabilityRegistry(), settings.llm_timeout_seconds)
    results, failed = [], False
    for name, goal, profile, expected in examples():
        runs, signatures = [], []
        for index in range(args.repeats):
            try:
                output = await planner.plan(make_intent(goal), profile)
                ok = output.coverage_status == expected and any(t.priority == "P0" for t in output.plan.tasks)
                if name == "city_count": ok &= len(output.plan.tasks) <= 2
                if name == "sales_year": ok &= any(r.feasibility == "F1" for r in output.validation_results)
                failed |= not ok
                signatures.append(signature(output))
                runs.append({"pass": ok, "output": output.model_dump(mode="json")})
                print(f"{name} run {index + 1}: {'PASS' if ok else 'FAIL'} ({output.coverage_status})")
            except AppError as exc:
                failed = True
                runs.append({"pass": False, "error_code": exc.error.code})
                print(f"{name} run {index + 1}: ERROR {exc.error.code}")
        stable = bool(signatures) and len(signatures) == args.repeats and all(s == signatures[0] for s in signatures)
        failed |= not stable
        print(f"{name}: structural priority/operation consistency={'PASS' if stable else 'REVIEW'}")
        results.append({"case": name, "goal": goal, "expected_coverage": expected, "consistent": stable, "runs": runs})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"notice": "真实模型规划评测，使用合成元数据；业务问题覆盖和优先级理由仍需人工评审。",
        "results": results}, ensure_ascii=False, indent=2) + "\n")
    print(f"详细结果：{args.output.resolve()}")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Real Planner semantic evaluation (explicit network opt-in)")
    parser.add_argument("--live", action="store_true", help="Explicitly allow configured model calls")
    parser.add_argument("--repeats", type=int, default=3, choices=range(2, 6))
    parser.add_argument("--output", type=Path, default=Path("var/planner-evaluation.json"))
    args = parser.parse_args()
    if not args.live:
        parser.error("真实模型评测必须显式指定 --live；普通测试不会调用模型。")
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())
