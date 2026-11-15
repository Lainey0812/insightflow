"""Reference-based evaluation. Does not judge open-ended prose or call another LLM."""
import unicodedata

TARGETS = {"schema_valid_rate": 1.0, "mode_accuracy": .90, "constraint_recall": .95,
           "fabricated_decision_count": 0, "blocking_recall": .95}


def normalized(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def score_case(case, result=None, error=None):
    expected = case["expected"]
    required = [(category, fragment) for category, fragments in expected["constraints"].items() for fragment in fragments]
    failures, matched = [], []
    if result is None:
        failures.append({"reason": "parser_error", "code": error["code"]})
    else:
        if result.analysis_mode != expected["analysis_mode"]:
            failures.append({"reason": "mode_mismatch", "expected": expected["analysis_mode"], "actual": result.analysis_mode.value})
        if result.next_action != expected["next_action"]:
            failures.append({"reason": "action_mismatch", "expected": expected["next_action"], "actual": result.next_action})
        decision = result.analysis_goal.decision_goal
        if expected["decision_goal"] is None and decision is not None:
            failures.append({"reason": "fabricated_decision", "actual": decision})
        elif expected["decision_goal"] is not None and (decision is None or normalized(expected["decision_goal"]) not in normalized(decision)):
            failures.append({"reason": "missing_explicit_decision", "expected": expected["decision_goal"], "actual": decision})
        for category, fragment in required:
            values = getattr(result.constraints, category)
            values = ([values] if values else []) if category == "time_range" else values
            if any(normalized(fragment) in normalized(value.raw_text) for value in values):
                matched.append((category, fragment))
            else:
                failures.append({"reason": "missing_constraint", "category": category, "raw_text": fragment})
        if expected.get("required_uncertainty_action") and not any(u.action == expected["required_uncertainty_action"] for u in result.uncertainties):
            failures.append({"reason": "missing_uncertainty", "action": expected["required_uncertainty_action"]})
    return {"case_id": case["id"], "dataset": case["dataset"], "query": case["query"], "tags": case["tags"],
        "expected": expected, "returned": result is not None, "schema_valid": result is not None,
        "mode_correct": result is not None and result.analysis_mode == expected["analysis_mode"],
        "blocking_expected": expected["next_action"] == "clarify",
        "blocking_identified": result is not None and result.next_action == "clarify",
        "no_decision_expected": expected["decision_goal"] is None,
        "fabricated_decision": result is not None and expected["decision_goal"] is None and result.analysis_goal.decision_goal is not None,
        "required_constraints": len(required), "matched_constraints": len(matched), "passed": not failures,
        "failures": failures, "error": error,
        "result": result.model_dump(mode="json", by_alias=True) if result is not None else None}


def summary(records):
    def ratio(n, d): return n / d if d else None
    n = len(records)
    returned = sum(r["returned"] for r in records)
    blocking = [r for r in records if r["blocking_expected"]]
    constraints = sum(r["required_constraints"] for r in records)
    metrics = {"schema_valid_rate": ratio(sum(r["schema_valid"] for r in records), returned),
        "mode_accuracy": ratio(sum(r["mode_correct"] for r in records), n),
        "constraint_recall": ratio(sum(r["matched_constraints"] for r in records), constraints),
        "fabricated_decision_count": sum(r["fabricated_decision"] for r in records) if returned else None,
        "blocking_recall": ratio(sum(r["blocking_identified"] for r in blocking), len(blocking))}
    # Errors never disappear from mode/constraint/blocker denominators. Zero returns is not 100% success.
    met = returned == n and n > 0 and all(metrics[key] is not None and
        (metrics[key] == 0 if key == "fabricated_decision_count" else metrics[key] >= target)
        for key, target in TARGETS.items())
    return {"sample_count": n, "returned_count": returned, "error_count": n-returned,
        "passed_cases": sum(r["passed"] for r in records), "case_pass_rate": ratio(sum(r["passed"] for r in records), n),
        "mode_denominator": n, "constraint_denominator": constraints, "blocking_denominator": len(blocking),
        "no_decision_cases": sum(r["no_decision_expected"] for r in records), "metrics": metrics,
        "targets": TARGETS, "engineering_targets_met": met,
        "prose_semantics_verified": False, "human_review_required": True}
