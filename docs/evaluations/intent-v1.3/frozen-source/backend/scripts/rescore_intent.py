"""Re-score saved model outputs under a frozen reviewed reference. Makes no LLM calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.intent import IntentArtifact
from scripts.evaluate_intent import scoring_tools


def rescore(source_path, cases_path, output_path):
    if output_path.resolve() in (source_path.resolve(), cases_path.resolve()):
        raise ValueError("Output must not overwrite source results or reference labels")
    if output_path.exists():
        raise FileExistsError("Re-score output already exists; choose a new path to preserve history")
    original = json.loads(source_path.read_text())
    suite = json.loads(cases_path.read_text())
    score_case, summary = scoring_tools(suite.get("scoring_protocol"))
    cases = {c["id"]: c for c in suite["cases"]}
    records = []
    for item in original["records"]:
        case = cases[item["case_id"]]
        if case["query"] != item["query"]:
            raise ValueError("Saved query does not match reference; refusing an invalid comparison")
        result = IntentArtifact.model_validate(item["result"]) if item["result"] else None
        scored = score_case(case, result, item.get("error"))
        scored["repeat"] = item.get("repeat", 1)
        records.append(scored)
    record = {key: original.get(key) for key in ("run_at", "configured_model", "prompt_version", "max_attempts",
              "total_timeout_seconds", "intent_enable_thinking", "intent_schema_sha256")}
    record.update(status="rescored_saved_outputs", source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                  suite_sha256=hashlib.sha256(cases_path.read_bytes()).hexdigest(),
                  suite_version=suite["version"], human_reviewed_labels=suite["human_reviewed"],
                  scoring_protocol=suite.get("scoring_protocol"),
                  new_llm_calls=0, records=records, summary=summary(records),
                  bad_cases=[r for r in records if not r["passed"]], acceptance_passed=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rescore(args.source, args.cases, args.output)["summary"], ensure_ascii=False, indent=2))
