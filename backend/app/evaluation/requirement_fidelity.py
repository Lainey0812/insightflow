"""Trace whether a frozen obligation survives intent, the accepted plan, and execution.

The scorer reads already saved structures. It does not call a model, repair a plan,
or recompute a statistic. A matching plan version is not evidence that a constraint ran.
"""
import hashlib
import json
import re
from pathlib import Path

SCORER_VERSION = 'requirement-fidelity-v1'
GOLD_PATH = Path(__file__).resolve().parents[3] / 'docs/evaluations/requirement-fidelity-v1-2026-11-12/obligations.json'
EXCLUSION_MARKERS = ('排除', '不包含', '不含')
AGGREGATIONS = {'aggregate', 'group_aggregate'}


def _gold():
    if not GOLD_PATH.is_file():
        return {}
    return json.loads(GOLD_PATH.read_text()).get('cases') or {}


def _compact(text):
    return re.sub(r'\s+', '', text or '')


def _constraint_texts(intent):
    constraints = (intent or {}).get('constraints') or {}
    found = []
    for category, value in constraints.items():
        items = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
        for item in items:
            if isinstance(item, dict) and item.get('raw_text'):
                found.append((category, item['raw_text']))
    goal = ((intent or {}).get('analysis_goal') or {}).get('business_goal') or ''
    return found, goal


def _excludes(text, value):
    compact = _compact(text)
    target = _compact(str(value))
    if not target or target not in compact or f'不排除{target}' in compact:
        return False
    position = compact.find(target)
    return any(marker in compact and compact.find(marker) < position for marker in EXCLUSION_MARKERS)


def _includes(text, value):
    compact = _compact(text)
    target = _compact(str(value))
    return bool(target) and target in compact and not _excludes(text, value)


def _field_id(fields, name):
    matches = [field['field_id'] for field in fields or [] if field.get('display_name') == name or field.get('original_name') == name]
    return matches[0] if len(matches) == 1 else None


def _tasks(tasks, executable_ids):
    rows = tasks or []
    if executable_ids is None:
        return [task for task in rows if task.get('priority') == 'P0' and task.get('steps')]
    chosen = set(executable_ids)
    return [task for task in rows if task.get('task_id') in chosen]


def _aggregate_index(task):
    return next((index for index, step in enumerate(task.get('steps') or []) if step.get('operation') in AGGREGATIONS), None)


def _conditions_before_aggregate(task):
    steps = task.get('steps') or []
    limit = _aggregate_index(task)
    if limit is None:
        return []
    found = []
    for index, step in enumerate(steps[:limit]):
        if step.get('operation') != 'filter':
            continue
        for condition in (step.get('params') or {}).get('conditions') or []:
            found.append((step, condition))
    return found


def _same_condition(condition, field_id, operator, value):
    if condition.get('field') != field_id or not field_id:
        return False
    actual, actual_value = condition.get('operator'), condition.get('value')
    if actual == operator and actual_value == value:
        return True
    if operator == 'eq' and actual == 'in' and actual_value == [value]:
        return True
    if operator == 'ne' and actual == 'not_in' and actual_value == [value]:
        return True
    if operator == 'in' and actual == 'in' and isinstance(value, list) and isinstance(actual_value, list):
        encode = lambda items: {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items}
        return encode(actual_value) == encode(value)
    return False


def _year_on_task(task, field_id, year):
    if _aggregate_index(task) is None or not field_id:
        return False
    conditions = [condition for _, condition in _conditions_before_aggregate(task)]
    aliases = [(step.get('params') or {}).get('alias') for step in task.get('steps') or []
               if step.get('operation') == 'derive' and (step.get('params') or {}).get('function') == 'extract_year'
               and (step.get('params') or {}).get('field') == field_id]
    if any(condition.get('field') in aliases and condition.get('operator') == 'eq' and condition.get('value') == year for condition in conditions):
        return True
    low, high = f'{int(year):04d}-01-01', f'{int(year) + 1:04d}-01-01'
    for suffix in ('', 'T00:00:00'):
        lower = any(condition.get('field') == field_id and condition.get('operator') == 'gte' and condition.get('value') == low + suffix for condition in conditions)
        upper = any(condition.get('field') == field_id and condition.get('operator') == 'lt' and condition.get('value') == high + suffix for condition in conditions)
        if lower and upper:
            return True
    return False


def _filter_steps(task, field_id, operator, value):
    return [step.get('step_id') for step, condition in _conditions_before_aggregate(task)
            if _same_condition(condition, field_id, operator, value)]


def _plan_carries(task, obligation, field_id):
    kind = obligation['kind']
    if kind == 'filter':
        return bool(_filter_steps(task, field_id, obligation['operator'], obligation['value']))
    if kind == 'year':
        return _year_on_task(task, field_id, obligation['value'])
    if kind == 'metric':
        return any(metric.get('function') == obligation['function'] and metric.get('field') == field_id
                   for step in task.get('steps') or [] if step.get('operation') in AGGREGATIONS
                   for metric in (step.get('params') or {}).get('metrics') or [])
    if kind == 'dimension':
        return any(field_id in ((step.get('params') or {}).get('dimensions') or [])
                   for step in task.get('steps') or [] if step.get('operation') == 'group_aggregate')
    if kind == 'absent_field':
        return not _references(task, field_id)
    return False


def _references(task, field_id):
    if not field_id:
        return False
    for step in task.get('steps') or []:
        params = step.get('params') or {}
        refs = [params.get('field'), *((params.get('dimensions') or []))]
        refs += [item.get('field') for item in params.get('conditions') or []]
        refs += [item.get('field') for item in params.get('metrics') or []]
        if field_id in refs:
            return True
    return False


def _stage(status, detail=None):
    return {'status': status, 'detail': detail}


def _intent_stage(obligation, intent):
    if intent is None:
        return _stage('not_observed', 'intent_missing')
    texts, goal = _constraint_texts(intent)
    kind = obligation['kind']
    if kind == 'absent_field':
        mentioned = any(obligation['field_name'] in text for _, text in texts) or obligation['field_name'] in goal
        return _stage('pass' if mentioned else 'fail', None if mentioned else 'prohibition_missing')
    if kind == 'year':
        token = f"{obligation['value']}年"
        structured = any(token in _compact(text) for _, text in texts)
        if structured:
            return _stage('pass')
        return _stage('fail', 'prose_only' if token in _compact(goal) else 'missing')
    if kind in {'metric', 'dimension'}:
        token = obligation.get('text') or obligation['field_name']
        structured = any(token and token in _compact(text) for _, text in texts)
        if structured:
            return _stage('pass')
        return _stage('fail', 'prose_only' if token and token in _compact(goal) else 'missing')
    value = obligation['value']
    polarity = obligation['polarity']
    hits = [(category, text) for category, text in texts if (_excludes(text, value) if polarity == 'exclude' else _includes(text, value))]
    if hits:
        return _stage('pass')
    if polarity == 'exclude' and any(_includes(text, value) and any(marker in _compact(text) for marker in ('只看', '仅看', '只分析', '仅分析')) for _, text in texts):
        return _stage('fail', 'reversed')
    blob = goal if polarity == 'exclude' and _excludes(goal, value) else goal if polarity != 'exclude' and _includes(goal, value) else ''
    return _stage('fail', 'prose_only' if blob else 'missing')


def _proof_step_ids(task, obligation, field_id):
    if not _plan_carries(task, obligation, field_id):
        return []
    if obligation['kind'] == 'filter':
        return _filter_steps(task, field_id, obligation['operator'], obligation['value'])
    if obligation['kind'] == 'year':
        ids = []
        for step, condition in _conditions_before_aggregate(task):
            if condition.get('field') == field_id and condition.get('operator') in {'gte', 'lt'}:
                ids.append(step.get('step_id'))
            if condition.get('operator') == 'eq' and condition.get('value') == obligation['value']:
                ids.append(step.get('step_id'))
        for step in task.get('steps') or []:
            params = step.get('params') or {}
            if step.get('operation') == 'derive' and params.get('function') == 'extract_year' and params.get('field') == field_id:
                ids.append(step.get('step_id'))
        return list(dict.fromkeys(ids))
    return [step.get('step_id') for step in task.get('steps') or []
            if step.get('operation') in AGGREGATIONS and _plan_carries({'steps': [step], 'priority': 'P0'}, obligation, field_id)]


def _coverage(tasks, obligation, field_id, executable_ids):
    if tasks is None:
        return _stage('not_observed', 'plan_missing')
    if obligation.get('field_name') and field_id is None:
        return _stage('fail', 'field_unresolved')
    selected = _tasks(tasks, executable_ids)
    if not selected:
        return _stage('fail', 'no_executable_task')
    scope = obligation.get('scope', 'every_executed' if obligation['kind'] in {'filter', 'year'} else 'any_executed')
    carried = [task.get('task_id') for task in selected if _plan_carries(task, obligation, field_id)]
    if scope == 'every_executed':
        return _stage('pass' if len(carried) == len(selected) else 'fail', None if len(carried) == len(selected) else 'condition_missing')
    if obligation['kind'] == 'absent_field':
        clean = all(not _references(task, field_id) for task in selected)
        return _stage('pass' if clean else 'fail', None if clean else 'forbidden_field_used')
    return _stage('pass' if carried else 'fail', None if carried else 'condition_missing')


def _cell_values(tables):
    values = []
    for table in tables or []:
        for row in table or []:
            if isinstance(row, dict):
                values.extend(row.values())
            elif isinstance(row, list):
                values.extend(row)
    return values


def _engine_stage(obligation, observed, validated_tasks, field_id):
    if observed.get('execution_status') is None:
        return _stage('not_observed', 'not_executed')
    steps = observed.get('execution_steps')
    if steps is None:
        return _stage('not_observed', 'steps_not_captured')
    selected = _tasks(validated_tasks, observed.get('executable_task_ids'))
    if obligation['kind'] == 'filter' and obligation.get('polarity') == 'exclude':
        present = {str(value) for value in _cell_values(observed.get('result_tables'))}
        forbidden = {str(value) for value in obligation.get('forbidden_labels') or []}
        required = {str(value) for value in obligation.get('required_labels') or []}
        if forbidden and forbidden & present:
            return _stage('fail', 'excluded_value_in_result')
        if required and not required <= present:
            return _stage('fail', 'expected_group_missing')
    matched_steps = [(task.get('task_id'), step_id) for task in selected for step_id in _proof_step_ids(task, obligation, field_id)]
    if obligation['kind'] == 'absent_field':
        used = any(step.get('operation') for step in steps if any(task.get('task_id') == step.get('task_id') and _references(task, field_id) for task in selected))
        return _stage('fail' if used else 'pass', 'forbidden_field_executed' if used else None)
    if not matched_steps:
        return _stage('fail', 'condition_missing_from_executed_plan')
    ran = {(step.get('task_id'), step.get('step_id')) for step in steps if step.get('status') == 'success' and step.get('operation')}
    if any(pair not in ran for pair in matched_steps if pair[1]):
        return _stage('fail', 'step_not_run')
    return _stage('pass', 'effect_checked' if obligation.get('forbidden_labels') else 'step_ran')


def score_obligation(obligation, observed):
    fields = observed.get('fields') or []
    field_id = _field_id(fields, obligation.get('field_name')) if obligation.get('field_name') else None
    if obligation['kind'] == 'metric' and obligation.get('field_name') is None:
        field_id = None
    intent = _intent_stage(obligation, observed.get('intent'))
    planner = _coverage(observed.get('planner_tasks'), obligation, field_id, observed.get('planner_executable_task_ids'))
    validator = _coverage(observed.get('validated_tasks'), obligation, field_id, observed.get('executable_task_ids'))
    if observed.get('planner_tasks') is not None and observed.get('validated_tasks') is not None and planner['status'] == 'pass' and validator['status'] == 'fail':
        validator = _stage('fail', 'dropped_after_planning')
    engine = _engine_stage(obligation, observed, observed.get('validated_tasks'), field_id)
    stages = {'intent': intent, 'planner': planner, 'validator': validator, 'engine': engine}
    lost_at = next((name for name in ('intent', 'planner', 'validator', 'engine') if stages[name]['status'] == 'fail'), None)
    return {'id': obligation['id'], 'kind': obligation['kind'], 'lost_at': lost_at, **stages}


def score_snapshot(obligations, observed):
    rows = [score_obligation(item, observed or {}) for item in obligations]
    return {'scorer_version': SCORER_VERSION, 'status': 'scored', 'obligation_count': len(rows),
            'carried_count': sum(row['lost_at'] is None and all(row[name]['status'] == 'pass' for name in ('intent', 'planner', 'validator', 'engine')) for row in rows),
            'lost': [{'id': row['id'], 'lost_at': row['lost_at'], 'detail': row[row['lost_at']]['detail']} for row in rows if row['lost_at']],
            'obligations': rows}


def assess(case_id, observed, query=None):
    spec = _gold().get(case_id)
    if not spec:
        return {'scorer_version': SCORER_VERSION, 'status': 'not_in_gold'}
    if query is not None and hashlib.sha256(query.encode()).hexdigest() != spec.get('query_sha256'):
        return {'scorer_version': SCORER_VERSION, 'status': 'query_mismatch'}
    if not observed:
        return {'scorer_version': SCORER_VERSION, 'status': 'not_observed'}
    return score_snapshot(spec.get('obligations') or [], observed)
