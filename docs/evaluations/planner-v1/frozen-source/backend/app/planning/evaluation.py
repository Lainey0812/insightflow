"""Frozen reference checks for Planner evaluation, not production semantic repair.

No LLM judge, statistics or output mutation. Business value/coverage needs human review.
"""
import json

SCORER_VERSION = "planner-reference-v1"


def signature(output):
    tasks = []
    for task in output.plan.tasks:
        aliases, steps = {}, []
        for step in task.steps:
            p = json.loads(json.dumps(step.params))
            def ref(value):
                return aliases.get(value, value)
            if "field" in p:
                p["field"] = ref(p["field"])
            if "dimensions" in p:
                p["dimensions"] = [ref(x) for x in p["dimensions"]]
            for c in p.get("conditions", []):
                c["field"] = ref(c["field"])
            for m in p.get("metrics", []):
                m["field"] = ref(m.get("field"))
                original = m["alias"]
                aliases[original] = f"alias_{len(aliases) + 1}"
                m["alias"] = aliases[original]
            if "alias" in p:
                original = p["alias"]
                aliases[original] = f"alias_{len(aliases) + 1}"
                p["alias"] = aliases[original]
            steps.append([step.operation, p])
        tasks.append({"priority": task.priority, "steps": steps,
                      "blocked": bool(task.missing_inputs)})
    return sorted(json.dumps(t, sort_keys=True, ensure_ascii=False) for t in tasks)


def score(case, output, profile, error=None):
    expected = case['expected']
    checks = []
    def check(kind, ok, details=None, constraint=False):
        checks.append({'kind': kind, 'passed': bool(ok), 'details': details, 'constraint': constraint})
    if expected.get('clarify_rejected'):
        check('clarify_gate', output is None and error and error['code'] == 'INTENT_CLARIFICATION_REQUIRED')
        return {'passed': all(c['passed'] for c in checks), 'checks': checks, 'failures': [c for c in checks if not c['passed']]}
    if output is None:
        return {'passed': False, 'checks': [], 'failures': [{'kind': 'call_or_output_failure', 'error': error}]}
    by_name = {f.display_name: f.field_id for f in profile.fields}
    names = {v: k for k, v in by_name.items()}
    tasks = output.plan.tasks
    vr = {r.task_id:r for r in output.validation_results}
    core = [t for t in tasks if t.priority == 'P0']
    check('p0_retained', bool(core))
    check('task_count', expected.get('min_tasks', 1) <= len(tasks) <= expected.get('max_tasks', 5), len(tasks))
    check('technical_coverage', output.coverage_status == expected.get('coverage','complete'), output.coverage_status)
    if expected.get('must_block'):
        check('blocked_core_preserved', bool(output.unmet_core_requirements) and any(not vr[t.task_id].executable for t in core))
        for text in expected.get('missing_mentions',[]):
            check('unresolved_condition_reported', any(text in '；'.join(t.missing_inputs) for t in core), text, True)
        return {'passed': all(c['passed'] for c in checks), 'checks':checks, 'failures':[c for c in checks if not c['passed']]}
    check('all_tasks_validated', all(r.executable for r in output.validation_results))
    check('no_duplicate_tasks', len(signature(output)) == len(set(signature(output))))
    metric_entries = [(t,s,m) for t in tasks for s in t.steps for m in s.params.get('metrics',[])]
    for metric in expected.get('metrics',[]):
        field = by_name.get(metric['field']) if metric['field'] is not None else None
        check('required_metric', any(t.priority=='P0' and m.get('field')==field and m['function']==metric['function'] for t,s,m in metric_entries), metric, True)
    if expected.get('metrics'):
        allowed={(by_name[m['field']] if m['field'] is not None else None,m['function']) for m in expected['metrics']}
        check('no_unrequested_metrics',all((m.get('field'),m['function']) in allowed for t,s,m in metric_entries),constraint=True)
    for dimension in expected.get('dimensions',[]):
        check('required_dimension', any(by_name[dimension] in s.params.get('dimensions',[]) for t in core for s in t.steps), dimension, True)
    for field, operator, value in expected.get('filters',[]):
        def matching(task):
            for s in task.steps:
                for c in s.params.get('conditions',[]):
                    if c['field']!=by_name[field]:continue
                    if c['operator']==operator and c['value']==value:return True
                    if operator=='eq' and c['operator']=='in' and c['value']==[value]:return True
                    if operator=='ne' and c['operator']=='not_in' and c['value']==[value]:return True
                    if operator=='in' and c['operator']=='in' and set(c['value'])==set(value):return True
            return False
        check('filter_in_every_core_task', all(matching(t) for t in core), [field,operator,value], True)
    if 'year' in expected:
        year=expected['year']
        def year_filter(task):
            date_fields={f.field_id for f in profile.fields if f.logical_type.value in ('date','datetime')}
            conditions=[c for s in task.steps for c in s.params.get('conditions',[])]
            derived={s.params['alias'] for s in task.steps if s.operation=='derive' and s.params['function']=='extract_year' and s.params['field'] in date_fields}
            if any(c['field'] in derived and c['operator']=='eq' and c['value']==year for c in conditions):return True
            for f in date_fields:
                low=any(c['field']==f and c['operator']=='gte' and c['value']==f'{year}-01-01' for c in conditions)
                high=any(c['field']==f and c['operator']=='lt' and c['value']==f'{year+1}-01-01' for c in conditions)
                if low and high:return True
            return False
        check('year_filter_in_every_core_task',all(year_filter(t) for t in core),year,True)
    if 'top_n' in expected:
        aliases={m['alias'] for t,s,m in metric_entries if t.priority=='P0'}
        check('aggregate_before_top_n',any(s.operation=='top_n' and s.params['n']==expected['top_n'] and s.params['direction']==expected['direction'] and s.params['field'] in aliases and any(x.operation in ('group_aggregate','aggregate') for x in t.steps[:i]) for t in core for i,s in enumerate(t.steps)),expected['top_n'],True)
    all_refs=set()
    for t in tasks:
        for s in t.steps:
            p=s.params
            all_refs.update(p.get('dimensions',[]))
            if p.get('field'):all_refs.add(p['field'])
            all_refs.update(m['field'] for m in p.get('metrics',[]) if m.get('field'))
            all_refs.update(c['field'] for c in p.get('conditions',[]))
    for f in expected.get('forbidden_fields',[]):
        check('no_forbidden_field',by_name[f] not in all_refs,f,True)
    for function in expected.get('forbidden_functions',[]):
        check('no_unconfirmed_statistic',not any(m['function']==function for t,s,m in metric_entries),function,True)
    for f in expected.get('no_filter_fields',[]):
        check('no_scope_reversal',not any(c['field']==by_name[f] for t in tasks for s in t.steps for c in s.params.get('conditions',[])),f,True)
    if 'derive' in expected:
        check('supported_transformation',any(s.operation=='derive' and s.params['function']==expected['derive'] for t in core for s in t.steps),expected['derive'])
    if expected.get('require_f1'):
        check('validator_f1',any(r.feasibility=='F1' for r in output.validation_results))
    if 'boundary_text' in expected:
        text=expected['boundary_text']
        check('boundary_visible',any(text in t.business_question+' '+t.priority_reason for t in tasks),text,True)
    return {'passed':all(c['passed'] for c in checks),'checks':checks,'failures':[c for c in checks if not c['passed']]}


def summarize(records):
    planned=[r for r in records if not r['expected'].get('clarify_rejected')]
    constraints=[c for r in planned for c in r['assessment']['checks'] if c.get('constraint')]
    return {'request_count':len(records),'plan_request_count':len(planned),
        'valid_plan_count':sum(r.get('output') is not None for r in planned),
        'complete_request_pass_count':sum(r['assessment']['passed'] for r in records),
        'complete_request_pass_rate':sum(r['assessment']['passed'] for r in records)/len(records) if records else None,
        'constraint_checks_passed':sum(c['passed'] for c in constraints),'constraint_check_count':len(constraints),
        'constraint_inheritance_accuracy':sum(c['passed'] for c in constraints)/len(constraints) if constraints else None,
        'constraint_assessment_failed_requests':sum(r.get('output') is None for r in planned),
        'business_semantics_human_verified':False,'acceptance_passed':False,
        'notice':'Reference checks only; missing outputs are separate failures, not omitted successes. P0/priority/business fidelity requires human review.'}
