"""Offline reference scoring only. Never repairs, enriches or modifies model output.

Precision is item-level alignment to frozen reference units, not a general semantic proof.
Recall is unit-level; a single item can express multiple same-category reference units.
"""
from app.intent.evaluation import normalized, score_case as legacy_score, summary as legacy_summary

CATEGORIES = ("time_range", "filters", "metric_requirements", "analysis_limits")
SCORER_VERSION = "intent-focused-v1"


def constraint_items(result):
    items = []
    for category in CATEGORIES:
        values = getattr(result.constraints, category)
        if category == "time_range":
            values = [values] if values else []
        items.extend({"category": category, "raw_text": value.raw_text} for value in values)
    return items


def score_case(case, result=None, error=None):
    record = legacy_score(case, result, error)
    units = case["focused_units"]
    predictions = constraint_items(result) if result is not None else []
    checks = case.get("polarity_checks", [])
    polarity_failures = []
    for check in checks:
        violations = []
        for category, fragments in check.get("forbidden", {}).items():
            for prediction in predictions:
                if prediction["category"] == category and any(
                        normalized(f) in normalized(prediction["raw_text"]) for f in fragments):
                    violations.append({"category": category, "raw_text": prediction["raw_text"]})
        limits = [p["raw_text"] for p in predictions if p["category"] == "analysis_limits"]
        required = check.get("required_limits", []) + ([check["required_limit"]] if check.get("required_limit") else [])
        for fragment in required:
            if not any(normalized(fragment) in normalized(text) for text in limits):
                violations.append({"missing_negated_limit": fragment})
        if result is not None and check.get("decision_must_be_null") and result.analysis_goal.decision_goal is not None:
            violations.append({"negated_decision_used": result.analysis_goal.decision_goal})
        # A call error is counted separately as unassessed, never a verified absence of semantic errors.
        if violations and result is not None:
            polarity_failures.append({"kind": check["kind"], "violations": violations})

    seen = set()
    for prediction in predictions:
        category, text = prediction["category"], normalized(prediction["raw_text"])
        hits = [u for u in units if u["category"] == category and normalized(u["text"]) in text]
        foreign = [u for u in units if u["category"] != category and normalized(u["text"]) in text
                   and not any(normalized(u["text"]) in normalized(hit["text"]) for hit in hits)]
        negated = any(category == cat and any(normalized(f) in text for f in fragments)
                      for check in checks for cat, fragments in check.get("forbidden", {}).items())
        # Detect obvious mixed ordering clauses even when the task's limit is a longer phrase.
        mixed_sort = category == "metric_requirements" and any(
            marker in text.lower() for marker in ("排名", "降序", "升序", "从高到低", "从低到高", "top"))
        key = (category, tuple(sorted(u["text"] for u in hits)))
        valid = bool(hits) and not foreign and not negated and not mixed_sort and key not in seen
        if hits:
            seen.add(key)
        prediction.update(reference_aligned=valid, matched_units=[u["text"] for u in hits],
                          foreign_category_units=[u["text"] for u in foreign])
        if not valid:
            record["failures"].append({"reason": "unverified_or_incorrect_constraint", **prediction})

    required_units = [u for u in units if u.get("required", True)]
    def matched(unit):
        return any(p["category"] == unit["category"] and normalized(unit["text"]) in normalized(p["raw_text"])
                   for p in predictions)
    metrics = [u for u in required_units if u["category"] == "metric_requirements"]
    limits = [u for u in required_units if u["category"] == "analysis_limits"]
    for failure in polarity_failures:
        record["failures"].append({"reason": "polarity_error", **failure})
    record.update(predicted_constraints=len(predictions), correct_predictions=sum(p["reference_aligned"] for p in predictions),
                  prediction_checks=predictions, negation_expected=bool(checks), negation_assessed=bool(checks) and result is not None,
                  negation_error=bool(polarity_failures), polarity_failures=polarity_failures,
                  metric_units=len(metrics), matched_metric_units=sum(matched(u) for u in metrics),
                  metric_complete=result is not None and all(matched(u) for u in metrics),
                  limit_units=len(limits), matched_limit_units=sum(matched(u) for u in limits),
                  limit_complete=result is not None and all(matched(u) for u in limits),
                  passed=not record["failures"])
    return record


def summary(records):
    result = legacy_summary(records)
    predicted = sum(r["predicted_constraints"] for r in records)
    correct = sum(r["correct_predictions"] for r in records)
    negation = [r for r in records if r["negation_expected"]]
    metric_cases = [r for r in records if r["metric_units"]]
    sort_cases = [r for r in records if "sort_classification" in r["tags"] or "multiple_constraints" in r["tags"]]
    result["metrics"].update(constraint_precision=correct / predicted if predicted else None,
        complete_request_pass_rate=result["case_pass_rate"],
        negation_error_count=sum(r["negation_error"] for r in negation),
        metric_completeness_rate=sum(r["metric_complete"] for r in metric_cases)/len(metric_cases) if metric_cases else None,
        sort_classification_pass_rate=sum(r["limit_complete"] and all(p["reference_aligned"] for p in r["prediction_checks"])
                                          for r in sort_cases)/len(sort_cases) if sort_cases else None)
    result.update(scorer_version=SCORER_VERSION, predicted_constraint_count=predicted, correct_prediction_count=correct,
                  negation_sample_count=len(negation), negation_assessed_count=sum(r["negation_assessed"] for r in negation),
                  negation_unassessed_count=sum(not r["negation_assessed"] for r in negation),
                  metric_sample_count=len(metric_cases), sort_sample_count=len(sort_cases),
                  independent_human_signoff=False, semantic_acceptance_passed=False,
                  precision_scope="Frozen-reference item alignment; no arbitrary prose entailment proof.")
    result["targets"] = {**result["targets"], "constraint_precision": .95, "negation_error_count": 0}
    result["engineering_targets_met"] = (result["engineering_targets_met"]
        and predicted > 0 and result["metrics"]["constraint_precision"] >= .95
        and not result["metrics"]["negation_error_count"] and not result["negation_unassessed_count"])
    return result
