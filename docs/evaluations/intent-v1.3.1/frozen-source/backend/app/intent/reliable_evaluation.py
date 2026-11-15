"""Frozen V1.3 offline scoring. Never modifies IntentResult or invokes an LLM.

Reference-bound phrase/stance checks detect specified errors, not arbitrary entailment.
"""
import re

from app.intent.evaluation import normalized, score_case as base_score, summary as base_summary
from app.intent.focused_evaluation import constraint_items

SCORER_VERSION = "intent-reliable-v1.3"
ORDER_MARKERS = ("排名", "排序", "降序", "升序", "从高到低", "从低到高", "top")
EMPTY_ACTIONS = {"比较", "分析", "统计", "汇总", "看看", "探索", "处理"}
ACTION = re.compile(r"计算|分析|探索|比较|统计|汇总|估算|预测|研究|考察|提供|输出|增加|纳入|建议|推断|排除")
OPTIONAL = re.compile(r"不要求|非必[选须需]|不是必选|不是必须|非必要|不强制|可以不|可不|不必|可选|选做|都行|不需要|无需")
UNSPECIFIED = re.compile(r"未指定|没有指定|未明确|未决定|未确定|未选定|尚未决定|尚未确定|暂未决定|暂未确定|没有特别要求|口径未定|待确认|待确定|不限定")
PROHIBITED = re.compile(r"不要|禁止|不得|不允许|不能|不可以|明确排除|排除|避免|别(?:再|据此|计算|分析|推断|建议)|不(?:进行|开展|做|计算|分析|探索|比较|统计|排名|排序|取|输出|建议|推断|生成|加入|纳入)")
BOUNDARY = re.compile(r"不排除|不要排除|不要只看|不是只看|不局限于|不限于|不限定城市|不限城市")
CLAUSE = re.compile(r"[，,。；;\n]|(?:并且|同时|但是|但|而且|并)(?=计算|分析|探索|比较|统计|汇总|明确|不|要|可|考察|研究)")
PARENS = re.compile(r"（[^）]*）|\([^)]*\)")


def goal_stances(text, aliases):
    """Auditable Chinese stance heuristic, scoped to pre-annotated topic aliases.

    Main-clause requests are not neutralized by a parenthetical 'unspecified'.
    Ambiguous or unknown prose still requires a reviewer.
    """
    observations = []
    for clause in CLAUSE.split(text or ""):
        aliases_here = [a for a in aliases if normalized(a) in normalized(clause)]
        if not aliases_here:
            continue
        main = PARENS.sub("", clause)
        alias_main = [a for a in aliases_here if normalized(a) in normalized(main)]
        candidate = main if alias_main else clause
        alias = max(alias_main or aliases_here, key=len)
        # Most aliases are literal spans; normalized matching is used for whitespace.
        pos = normalized(candidate).find(normalized(alias))
        before = normalized(candidate)[:pos]
        after = normalized(candidate)[pos:]
        if BOUNDARY.search(candidate):
            stance = "boundary"
        elif OPTIONAL.search(candidate):
            stance = "optional"
        elif PROHIBITED.search(candidate):
            stance = "prohibited"
        elif UNSPECIFIED.search(before):
            stance = "unspecified"
        elif not alias_main and UNSPECIFIED.search(clause):
            stance = "unspecified"
        elif UNSPECIFIED.search(after) and not ACTION.search(before):
            stance = "unspecified"
        elif ACTION.search(main) or alias_main:
            stance = "required"
        else:
            stance = "mention"
        observations.append({"clause": clause.strip(), "topic": alias, "stance": stance})
    return observations


def unit_matches(unit, item, result):
    text = normalized(item["raw_text"])
    if normalized(unit["text"]) in text:
        return True
    context = normalized(" ".join(filter(None, [result.analysis_goal.analysis_object, result.analysis_goal.business_goal])))
    for equivalent in unit.get("equivalents", []):
        if normalized(equivalent["text"]) in text and all(
                normalized(token) in context for token in equivalent.get("context_all", [])):
            return True
    return False


def score_case(case, result=None, error=None):
    record = base_score(case, result, error)
    # Replace only fragment-based constraint findings with the frozen V1.3 matcher.
    record["failures"] = [f for f in record["failures"] if f["reason"] != "missing_constraint"]
    units = case["focused_units"]
    required = [u for u in units if u.get("required", True)]
    predictions = constraint_items(result) if result is not None else []
    seen_units = set()
    for item in predictions:
        own = [i for i,u in enumerate(units) if u["category"] == item["category"] and unit_matches(u,item,result)]
        foreign = []
        for i,u in enumerate(units):
            if u["category"] == item["category"] or not unit_matches(u,item,result):
                continue
            if any(normalized(u["text"]) in normalized(units[j]["text"]) for j in own):
                continue
            context_allowed = (item["category"] == "analysis_limits" and u["category"] == "metric_requirements"
                and any(p["category"] == "metric_requirements" and unit_matches(u,p,result)
                    and not any(m in normalized(p["raw_text"]).lower() for m in ORDER_MARKERS) for p in predictions))
            if not context_allowed:
                foreign.append(i)
        mixed_sort = item["category"] == "metric_requirements" and any(
            m in normalized(item["raw_text"]).lower() for m in ORDER_MARKERS)
        meaningless = normalized(item["raw_text"]) in EMPTY_ACTIONS
        forbidden = any(item["category"] == category and any(normalized(t) in normalized(item["raw_text"]) for t in terms)
            for check in case.get("polarity_checks", []) for category,terms in check.get("forbidden", {}).items())
        semantic_valid = bool(own) and not foreign and not mixed_sort and not meaningless and not forbidden
        duplicate = bool(set(own) & seen_units)
        if semantic_valid:
            seen_units.update(own)
        item.update(matched_unit_indices=own, foreign_unit_indices=foreign, semantic_valid=semantic_valid,
                    duplicate=duplicate, reference_aligned=semantic_valid and not duplicate)
        if not item["reference_aligned"]:
            record["failures"].append({"reason": "incorrect_constraint", **item})
    matched = set()
    for p in predictions:
        # Duplicate semantic facts contribute once to recall, and lower precision.
        if p["semantic_valid"]:
            matched.update(p["matched_unit_indices"])
    for i,u in enumerate(units):
        if u.get("required",True) and i not in matched:
            record["failures"].append({"reason":"missing_constraint","category":u["category"],"raw_text":u["text"]})
    polarity = []
    if result is not None:
        for check in case.get("polarity_checks",[]):
            violations=[]
            for category,terms in check.get("forbidden",{}).items():
                for p in predictions:
                    if p["category"]==category and any(normalized(t) in normalized(p["raw_text"]) for t in terms):
                        violations.append({"category":category,"raw_text":p["raw_text"]})
            limits=[p for p in predictions if p["category"]=='analysis_limits']
            phrases=check.get('required_limits',[])+([check['required_limit']] if check.get('required_limit') else [])
            for phrase in phrases:
                if not any(normalized(phrase) in normalized(p['raw_text']) for p in limits):
                    violations.append({'missing_negated_limit':phrase})
            if check.get('decision_must_be_null') and result.analysis_goal.decision_goal is not None:
                violations.append({'negated_decision_used':result.analysis_goal.decision_goal})
            if violations:polarity.append({'kind':check['kind'],'violations':violations})
    observations=[]
    core_errors=[]
    if result is not None:
        for expectation in case.get('semantic_expectations',[]):
            found=goal_stances(result.analysis_goal.business_goal,expectation['aliases'])
            observations.append({'topic':expectation['topic'],'expected':expectation['state'],'observed':found})
            allowed=expectation.get('allowed_goal_states',{
                'required':['required','mention'], 'optional':['optional','mention'],
                'unspecified':['unspecified','mention'], 'prohibited':['prohibited','mention'],
                'not_requested':['mention'], 'boundary':['boundary','mention']
            }[expectation['state']])
            violations=[o for o in found if o['stance'] not in allowed]
            if violations:
                error_item={'kind':'goal_stance_conflict','topic':expectation['topic'],'expected':expectation['state'],'violations':violations}
                if expectation['state']=='not_requested':core_errors.append(error_item)
                else:polarity.append(error_item)
    record['failures'].extend({'reason':'polarity_error',**p} for p in polarity)
    record['failures'].extend({'reason':'unrequested_core_goal',**p} for p in core_errors)
    metric_indices=[i for i,u in enumerate(units) if u.get('required',True) and u['category']=='metric_requirements']
    limit_indices=[i for i,u in enumerate(units) if u.get('required',True) and u['category']=='analysis_limits']
    negation_expected=bool(case.get('polarity_checks')) or any(e['state'] in ('unspecified','optional','prohibited','boundary') for e in case.get('semantic_expectations',[]))
    record.update(required_constraints=len(required),matched_constraints=sum(i in matched for i,u in enumerate(units) if u.get('required',True)),
        predicted_constraints=len(predictions),correct_predictions=sum(p['reference_aligned'] for p in predictions),prediction_checks=predictions,
        semantic_observations=observations,negation_expected=negation_expected,negation_assessed=negation_expected and result is not None,
        negation_error=bool(polarity),polarity_failures=polarity,unrequested_core_goal=bool(core_errors),core_goal_failures=core_errors,
        metric_units=len(metric_indices),matched_metric_units=sum(i in matched for i in metric_indices),
        metric_complete=result is not None and all(i in matched for i in metric_indices),
        limit_units=len(limit_indices),matched_limit_units=sum(i in matched for i in limit_indices),
        limit_complete=result is not None and all(i in matched for i in limit_indices),passed=not record['failures'])
    return record


def summary(records):
    result=base_summary(records)
    n=len(records);predicted=sum(r['predicted_constraints'] for r in records);correct=sum(r['correct_predictions'] for r in records)
    negatives=[r for r in records if r['negation_expected']]
    metrics=result['metrics']
    metrics.update(call_success_rate=result['returned_count']/n if n else None,
        constraint_precision=correct/predicted if predicted else None,complete_request_pass_rate=result['case_pass_rate'],
        negation_error_count=sum(r['negation_error'] for r in negatives),
        unrequested_core_goal_count=sum(r['unrequested_core_goal'] for r in records),
        metric_completeness_rate=(sum(r['metric_complete'] for r in records if r['metric_units'])/sum(bool(r['metric_units']) for r in records)) if any(r['metric_units'] for r in records) else None)
    result.update(scorer_version=SCORER_VERSION,predicted_constraint_count=predicted,correct_prediction_count=correct,
        negation_sample_count=len(negatives),negation_assessed_count=sum(r['negation_assessed'] for r in negatives),
        negation_unassessed_count=sum(not r['negation_assessed'] for r in negatives),
        independent_human_signoff=False,semantic_acceptance_passed=False,
        precision_scope='Frozen-reference semantics and category checks; stance rules are heuristic, human review required.')
    result['targets']={**result['targets'],'constraint_precision':.95,'negation_error_count':0,'unrequested_core_goal_count':0}
    result['engineering_targets_met']=(result['engineering_targets_met'] and predicted>0 and metrics['constraint_precision']>=.95
        and metrics['negation_error_count']==0 and metrics['unrequested_core_goal_count']==0 and not result['negation_unassessed_count'])
    return result
