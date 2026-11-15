"""Explicit live evaluation against fixed synthetic data. Never substitutes scripted outputs."""
import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.intent.evaluation import score_case, summary
from app.intent.prompt import PROMPT_VERSION
from app.intent.prompt import SYSTEM_PROMPT
from app.llm.compatible_provider import UnconfiguredLLMProvider
from app.llm.factory import create_provider
from app.profiling.profiler import build_profile
from app.services.intent_parser import IntentParserService, PROVIDER_ERRORS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "backend/evaluation/intent_cases.json"
DEFAULT_OUTPUT = ROOT / "docs/intent-live-evaluation.json"


def scoring_tools(protocol):
    if protocol == "intent-reliable-v1.3":
        from app.intent.reliable_evaluation import score_case as score, summary as summarize
    elif protocol == "intent-focused-v1":
        from app.intent.focused_evaluation import score_case as score, summary as summarize
    elif protocol in (None, "intent-reference-v1"):
        score, summarize = score_case, summary
    else:
        raise ValueError("Unknown scoring protocol; refusing to silently use another scorer")
    return score, summarize


class EvaluationRecorder:
    """A test-only adapter recorder, not an additional model node or call.

    Synthetic eval output only; production logging is unchanged. No headers or keys.
    """
    def __init__(self, provider, api_key):
        self.provider, self.api_key, self.attempts = provider, api_key, []

    async def generate(self, request):
        item = {"attempt": len(self.attempts) + 1, "status": "pending"}
        self.attempts.append(item)
        started = time.perf_counter()
        try:
            response = await self.provider.generate(request)
            text = response.text.replace(self.api_key, "[REDACTED]") if self.api_key else response.text
            text = text.encode("utf-8", errors="replace").decode("utf-8")
            item.update(status="returned", text=text[:65536], truncated=len(text)>65536,
                        model=response.model, is_mock=response.is_mock)
            return response
        except AppError as exc:
            item.update(status="call_failed", code=exc.error.code if exc.error.code in PROVIDER_ERRORS else "LLM_CALL_FAILED")
            raise
        except asyncio.CancelledError:
            item.update(status="cancelled", code="LLM_TIMEOUT")
            raise
        except Exception:
            item.update(status="call_failed", code="LLM_CALL_FAILED")
            raise
        finally:
            item["duration_seconds"] = round(time.perf_counter()-started, 4)


def write_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


async def evaluate(cases_path, output, repeats=1):
    if output.exists():
        raise FileExistsError("Evaluation output already exists; choose a new path to preserve history")
    settings = Settings.from_env()
    provider = create_provider(settings)
    raw = cases_path.read_bytes()
    dataset = json.loads(raw)
    cases = dataset["cases"]
    score, summarize = scoring_tools(dataset.get("scoring_protocol"))
    record = {"run_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "timezone": "Asia/Shanghai",
        "prompt_version": PROMPT_VERSION, "suite_version": dataset["version"], "suite_sha256": hashlib.sha256(raw).hexdigest(),
        "annotation_source": dataset["annotation_source"], "human_reviewed_labels": dataset["human_reviewed"],
        "configured_model": settings.llm_model or None, "max_attempts": settings.intent_max_attempts,
        "total_timeout_seconds": settings.llm_timeout_seconds, "repeats": repeats,
        "intent_enable_thinking": settings.intent_enable_thinking,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "system_prompt": SYSTEM_PROMPT,
        "scoring_protocol": dataset.get("scoring_protocol", "intent-reference-v1"),
        "schema_version": "IntentResult/V1 (unchanged; canonical SHA256 below)",
        "sampling_parameters": "temperature/top_p/max_tokens omitted; provider defaults",
        "intent_schema_sha256": hashlib.sha256(json.dumps(ParsedIntent.model_json_schema(), sort_keys=True).encode()).hexdigest(),
        "planned_sample_count": len(cases) * repeats, "actual_sample_count": 0,
        "llm_attempt_count": 0, "records": [], "acceptance_passed": False}
    if isinstance(provider, UnconfiguredLLMProvider):
        record.update(status="blocked", blocking_reason="LLM_NOT_CONFIGURED", metrics=None,
            summary=None, bad_cases=[], note="真实模型调用 0 次。未计算或宣称语义准确率；需配置服务地址和模型名，云端按服务要求配置 Key。")
        write_record(output, record)
        print(json.dumps({key: record[key] for key in ["status", "blocking_reason", "planned_sample_count", "actual_sample_count", "metrics"]}, ensure_ascii=False))
        return 2
    profiles = {name: build_profile(data["csv"].encode(), ".csv", "eval_"+name, data["filename"])
                for name, data in dataset["datasets"].items()}
    recorder = EvaluationRecorder(provider, settings.llm_api_key)
    parser = IntentParserService(recorder, settings.llm_timeout_seconds, max_attempts=settings.intent_max_attempts,
                                 enable_thinking=settings.intent_enable_thinking)
    record["status"] = "running"
    for repeat in range(repeats):
        for case in cases:
            recorder.attempts = []
            try:
                result = await parser.parse(case["query"], profiles[case["dataset"]])
                if result.llm is None or result.llm.is_mock:
                    raise AppError("EVALUATION_NON_LIVE_RESULT", "真实评测不接受 Mock Provider 或未调用模型的输入守卫。", 502)
                item = score(case, result)
                record["llm_attempt_count"] += result.llm_attempts
            except AppError as exc:
                item = score(case, error={"code": exc.error.code, "details": exc.error.details})
                record["llm_attempt_count"] += exc.error.details.get("attempts", 0)
            item["repeat"] = repeat + 1
            item["model_attempts"] = recorder.attempts
            record["records"].append(item)
            record["actual_sample_count"] += 1
            record["summary"] = summarize(record["records"])
            record["bad_cases"] = [r for r in record["records"] if not r["passed"]]
            write_record(output, record)
            print(json.dumps({"case_id": case["id"], "repeat": repeat+1, "passed": item["passed"],
                "failures": item["failures"]}, ensure_ascii=False), flush=True)
    record["status"] = "completed"
    attempts = [a for r in record["records"] for a in r["model_attempts"]]
    record["provider_response_rate"] = sum(a["status"] == "returned" for a in attempts)/len(attempts) if attempts else None
    record["acceptance_passed"] = record["summary"]["engineering_targets_met"] and dataset["human_reviewed"]
    record["metrics"] = record["summary"]["metrics"]
    write_record(output, record)
    print(json.dumps(record["summary"], ensure_ascii=False, indent=2))
    return 0 if record["summary"]["engineering_targets_met"] else 1


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--live", action="store_true", help="Call configured model using synthetic metadata; may incur cost.")
    arguments.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    arguments.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments.add_argument("--repeats", type=int, default=1, choices=range(1, 4))
    args = arguments.parse_args()
    if not args.live:
        arguments.error("--live is required; no model calls were made")
    raise SystemExit(asyncio.run(evaluate(args.cases, args.output, args.repeats)))
