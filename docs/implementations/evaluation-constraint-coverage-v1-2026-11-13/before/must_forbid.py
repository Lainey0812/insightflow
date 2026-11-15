"""Required check that forbidden fields were not used. Generic over structured rules; no case ids in code.

Rules come from either:
- ``case['forbid_rules']``: structured rules carried by the case itself;
- ``case['must_forbid']``: natural-language items, each resolved through the versioned
  adaptation table in forbid_rules. Unadapted items are never treated as satisfied.

Evidence and verdict order:
1. FAIL           a forbidden identifier appears in the plan, in a step the engine ran, or in a
                  result column. Profile membership is not needed: an explicit reference fails.
2. NOT_EVALUATED  an item is not adapted, or plan, profile, engine or result evidence needed to
                  prove absence is missing.
3. PASS           every needed piece of evidence is present and nothing forbidden is found.
Exceptions become EVALUATOR_ERROR through run_evaluator, never an agent failure.
"""
import hashlib
import re
import unicodedata

from .forbid_rules import ADAPTATIONS, ADAPTER_VERSION, RULES, adapter_sha256
from .protocol import EvaluationEvidence, Outcome

FIELD_KEYS = ('field', 'fields', 'dimensions', 'alias', 'column', 'columns', 'group_by', 'by')
NESTED_KEYS = ('conditions', 'metrics')
ENGINE_SUCCESS = {'success', 'partial_success'}
NOT_EXECUTED = {'BLOCKED', 'FAILED', 'TIMEOUT', 'CANCELLED'}


def normalize_identifier(value) -> str:
    return re.sub(r'[\s_\-.·]+', '', unicodedata.normalize('NFKC', str(value)).casefold())


def matches(identifier, match) -> bool:
    key = normalize_identifier(identifier)
    if not key:
        return False
    if key in {normalize_identifier(v) for v in [*match.get('names', []), *match.get('aliases', [])]}:
        return True
    return any(re.fullmatch(pattern, key) for pattern in match.get('patterns', []))


def step_identifiers(params):
    """Yield (path, identifier) for every structured field reference in step params."""
    if not isinstance(params, dict):
        return
    for key in FIELD_KEYS:
        value = params.get(key)
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            if isinstance(item, str):
                yield (f'{key}[{index}]' if isinstance(value, list) else key), item
    for key in NESTED_KEYS:
        for index, item in enumerate(params.get(key) or []):
            for path, identifier in step_identifiers(item if isinstance(item, dict) else {}):
                yield f'{key}[{index}].{path}', identifier


def resolve_rules(case, dataset_id, adaptations=ADAPTATIONS, rules=RULES):
    """Return (rules, unadapted_item_refs). Each rule is (rule_id, rule, source_refs)."""
    resolved, unadapted = [], []
    for index, rule in enumerate(case.get('forbid_rules') or []):
        resolved.append((rule.get('rule_id') or f'case-rule-{index}', rule, [f'case.forbid_rules[{index}]']))
    table = {item['index']: item for item in (adaptations.get(dataset_id) or {}).get(case.get('case_id'), [])}
    grouped = {}
    for index, text in enumerate(case.get('must_forbid') or []):
        ref = f'case.must_forbid[{index}]'
        item = table.get(index)
        if not item or item['text_sha256'] != hashlib.sha256(str(text).encode()).hexdigest():
            unadapted.append(ref)
        elif item['disposition'] == 'rule' and item.get('rule_id') in rules:
            grouped.setdefault(item['rule_id'], []).append(ref)
        elif item['disposition'] != 'clarification':
            unadapted.append(ref)
    for rule_id, refs in grouped.items():
        resolved.append((rule_id, rules[rule_id], refs))
    return resolved, unadapted


class MustForbidEvaluator:
    evaluator_id = 'insightflow.golden.must_forbid'
    evaluator_version = 'must-forbid-v1'
    scope = 'e2e'

    def __init__(self, adaptations=ADAPTATIONS, rules=RULES):
        self.adaptations, self.rules = adaptations, rules

    def config(self):
        return {'adapter_version': ADAPTER_VERSION, 'adapter_sha256': adapter_sha256(self.rules, self.adaptations),
                'rules': self.rules, 'adaptations': self.adaptations,
                'evidence': {'plan': 'artifacts.plan.tasks[].steps[].params field references',
                             'profile': 'artifacts.profile.fields id to display name',
                             'engine': 'artifacts.execution_steps joined to plan steps by task_id and step_id',
                             'result_columns': 'artifacts.result_tables row keys'},
                'identifier_keys': {'direct': list(FIELD_KEYS), 'nested': list(NESTED_KEYS)}}

    def applicable(self, evidence: EvaluationEvidence):
        case = evidence.case
        return (True, None) if case.get('must_forbid') or case.get('forbid_rules') else (False, 'no_forbid_rules')

    def evaluate(self, evidence: EvaluationEvidence):
        artifacts, refs = evidence.artifacts, evidence.refs
        rules, unadapted = resolve_rules(evidence.case, artifacts.get('dataset_id'), self.adaptations, self.rules)
        sources = [f"{refs.get('case', 'case')}.{ref.removeprefix('case.')}" for _, _, rule_refs in rules for ref in rule_refs]
        observed, missing, used = self._identifiers(evidence)
        for rule_id, rule, rule_refs in rules:
            if rule.get('kind') != 'forbid_field':
                unadapted += rule_refs
                continue
            for scope in rule.get('scopes') or []:
                for location, identifier, name in observed.get(scope, []):
                    if matches(identifier, rule['match']) or (name and matches(name, rule['match'])):
                        shown = identifier if not name or name == identifier else f'{identifier}({name})'
                        return Outcome('FAIL', rule.get('failure_code') or 'F-FORBIDDEN-FIELD',
                                       f'{rule_id}@{scope}:{location}={shown}',
                                       evidence_refs=tuple(sources + [r for r in (refs.get(scope),) if r]))
        if unadapted:
            return Outcome('NOT_EVALUATED', reason='rule_not_adapted:' + ','.join(unadapted), evidence_refs=tuple(sources))
        if not rules:
            return Outcome('NOT_EVALUATED', reason='no_executable_rule', evidence_refs=tuple(sources))
        needed = {scope for _, rule, _ in rules for scope in rule.get('scopes') or []}
        gaps = sorted(item for item in missing if item.split(':')[0] in needed | {'profile'})
        if gaps:
            return Outcome('NOT_EVALUATED', reason='missing_evidence:' + ','.join(gaps), evidence_refs=tuple(sources))
        checked = ','.join(scope for scope in ('plan', 'engine', 'result_columns') if scope in used)
        return Outcome('PASS', reason='no_forbidden_field_in:' + checked,
                       evidence_refs=tuple(sources + [refs[s] for s in ('plan', 'engine', 'result_columns') if s in used and refs.get(s)]))

    @staticmethod
    def _identifiers(evidence):
        """Collect identifiers per scope, the evidence that is missing, and the scopes actually checked."""
        artifacts, status = evidence.artifacts, evidence.execution.execution_status
        observed, missing, used = {'plan': [], 'engine': [], 'result_columns': []}, [], set()
        fields = (artifacts.get('profile') or {}).get('fields')
        names = {f.get('field_id'): f.get('display_name') for f in fields or [] if isinstance(f, dict)}
        if not isinstance(fields, list) or not fields:
            missing.append('profile')
        tasks = (artifacts.get('plan') or {}).get('tasks') if isinstance(artifacts.get('plan'), dict) else None
        steps = {}
        if isinstance(tasks, list) and tasks:
            used.add('plan')
            for task in tasks:
                for step in task.get('steps') or []:
                    steps[(task.get('task_id'), step.get('step_id'))] = step
                    for path, identifier in step_identifiers(step.get('params')):
                        observed['plan'].append((f"{task.get('task_id')}/{step.get('step_id')}.{path}", identifier, names.get(identifier)))
        else:
            missing.append('plan')
        engine_status = artifacts.get('engine_execution_status')
        executed = artifacts.get('execution_steps')
        ran = engine_status is not None or bool(executed) or status == 'COMPLETED'
        if ran:
            if not isinstance(executed, list) or not executed or not steps:
                missing.append('engine')
            else:
                used.add('engine')
                for entry in executed:
                    key = (entry.get('task_id'), entry.get('step_id'))
                    step = steps.get(key)
                    if step is None:
                        missing.append(f'engine:unmapped_step:{key[0]}/{key[1]}')
                        continue
                    for path, identifier in step_identifiers(step.get('params')):
                        observed['engine'].append((f'{key[0]}/{key[1]}.{path}', identifier, names.get(identifier)))
        elif status not in NOT_EXECUTED:
            missing.append('engine')
        if engine_status in ENGINE_SUCCESS:
            columns = []
            for t, table in enumerate(artifacts.get('result_tables') or []):
                keys = dict.fromkeys(str(key) for row in table or [] if isinstance(row, dict) for key in row)
                columns += [(f'table[{t}]', key) for key in keys]
            if columns:
                used.add('result_columns')
                observed['result_columns'] = [(location, column, None) for location, column in columns]
            else:
                missing.append('result_columns')
        return observed, missing, used
