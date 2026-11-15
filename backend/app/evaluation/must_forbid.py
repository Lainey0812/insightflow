"""Required check of Golden constraints through the versioned Constraint Coverage Mapping.

Constraints come from either:
- ``case['forbid_rules']``: structured rules carried by the case itself;
- ``case['must_forbid']`` (and mapped ``case['must_execute']`` items): sentences resolved through
  constraint_coverage.MAPPING. Unmapped or stale sentences are never treated as satisfied.

Verification modes:
- ``forbid_field``    a forbidden identifier in the plan, an executed step or a result column.
- ``row_set``         rows that reached aggregation, recovered by replaying the executed plan on
                      the pinned dataset rows (row_set.aggregation_inputs).
- ``ORACLE_COVERED``  holds only when the oracle rule passes on the same evidence; otherwise the
                      sentence stays NOT_EVALUATED and the oracle evaluator carries the failure.
- ``NON_ASSERTION``   listed for traceability, never a gate.
Guard ``unique-oracle-labels`` fails a result table that repeats an oracle label.

Verdict order: FAIL if any check finds a violation; NOT_EVALUATED if any sentence is unmapped,
stale, or lacks evidence; PASS otherwise. Exceptions become EVALUATOR_ERROR through run_evaluator.
"""
import re
import unicodedata

from app.planning.capabilities import CapabilityRegistry
from app.regression.scoring import _key

from .constraint_coverage import CHECK_EVALUATOR, GUARDS, MAPPING, MAPPING_VERSION, mapping_sha256, resolve
from .evaluators import GoldenOracleEvaluator
from .forbid_rules import RULES, RULES_VERSION, rules_sha256
from .golden_fidelity import _exact_oracle
from .protocol import EvaluationEvidence, Outcome
from .row_set import aggregation_inputs

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


def duplicate_labels(tables, labels):
    """Yield (table index, column, label) where an oracle label occurs in more than one row."""
    wanted = {_key(label) for label in labels}
    for t, table in enumerate(tables or []):
        columns = dict.fromkeys(key for row in table or [] if isinstance(row, dict) for key in row)
        for column in columns:
            seen = [_key(row.get(column)) for row in table if isinstance(row, dict) and column in row]
            for label in sorted(wanted):
                if seen.count(label) > 1:
                    yield t, column, label


class MustForbidEvaluator:
    evaluator_id = CHECK_EVALUATOR
    evaluator_version = 'must-forbid-v2'
    scope = 'e2e'

    def __init__(self, mapping=MAPPING, guards=GUARDS, rules=RULES):
        self.mapping, self.guards, self.rules = mapping, guards, rules

    def config(self):
        return {'mapping_version': MAPPING_VERSION, 'mapping_sha256': mapping_sha256(self.mapping, self.guards),
                'mapping': self.mapping, 'guards': self.guards,
                'rules_version': RULES_VERSION, 'rules_sha256': rules_sha256(self.rules), 'rules': self.rules,
                'capability_version': CapabilityRegistry.version,
                'evidence': {'plan': 'artifacts.plan.tasks[].steps[].params field references',
                             'profile': 'artifacts.profile.fields id to display name',
                             'engine': 'artifacts.execution_steps joined to plan steps by task_id and step_id',
                             'result_columns': 'artifacts.result_tables row keys',
                             'dataset_rows': 'artifacts.dataset_rows, replayed through the registered kernels'},
                'identifier_keys': {'direct': list(FIELD_KEYS), 'nested': list(NESTED_KEYS)}}

    def applicable(self, evidence: EvaluationEvidence):
        case = evidence.case
        return (True, None) if case.get('must_forbid') or case.get('forbid_rules') else (False, 'no_forbid_rules')

    def current_versions(self):
        return {GoldenOracleEvaluator.evaluator_id: GoldenOracleEvaluator.evaluator_version,
                self.evaluator_id: self.evaluator_version}

    def evaluate(self, evidence: EvaluationEvidence):
        case, artifacts, refs = evidence.case, evidence.artifacts, evidence.refs
        rows = artifacts.get('dataset_rows')
        entries, unadapted, stale = resolve(case, artifacts.get('dataset_id'), rows, self.current_versions(),
                                            CapabilityRegistry.version, self.mapping)
        cited = lambda ref: f"{refs.get('case', 'case')}.{ref.removeprefix('case.')}"
        sources = [cited(ref) for ref, _ in entries]
        fails, pending, passed = [], [], []
        by_mode = {}
        for ref, entry in entries:
            check = entry.get('check') or {}
            mode = 'ORACLE_COVERED' if entry['verification_mode'] == 'ORACLE_COVERED' else check.get('kind') or entry['verification_mode']
            by_mode.setdefault(mode, []).append((ref, entry))

        rules, bad = [], []
        for index, rule in enumerate(case.get('forbid_rules') or []):
            rules.append((rule.get('rule_id') or f'case-rule-{index}', rule, [f'case.forbid_rules[{index}]']))
        grouped = {}
        for ref, entry in by_mode.get('forbid_field', []):
            grouped.setdefault(entry['check'].get('rule_id'), []).append(ref)
        for rule_id, rule_refs in grouped.items():
            if rule_id in self.rules:
                rules.append((rule_id, self.rules[rule_id], rule_refs))
            else:
                bad += rule_refs
        for kind in set(by_mode) - {'ORACLE_COVERED', 'forbid_field', 'row_set', 'NON_ASSERTION'}:
            bad += [ref for ref, _ in by_mode[kind]]
        bad += [ref for _, rule, rule_refs in rules if rule.get('kind') != 'forbid_field' for ref in rule_refs]
        if unadapted or bad:
            pending.append('rule_not_adapted:' + ','.join(unadapted + bad))
        if stale:
            pending.append('coverage_stale:' + ','.join(stale))
        self._forbid_fields(evidence, [r for r in rules if r[1].get('kind') == 'forbid_field'], fails, pending, passed, refs, sources)
        self._row_sets(evidence, by_mode.get('row_set', []), fails, pending, passed, cited)
        self._oracle_covered(evidence, by_mode.get('ORACLE_COVERED', []), pending, passed)
        self._guards(evidence, fails, passed)

        if fails:
            code, reason, extra = fails[0]
            return Outcome('FAIL', code, reason, evidence_refs=tuple(dict.fromkeys(sources + extra)))
        if pending:
            return Outcome('NOT_EVALUATED', reason=';'.join(pending), evidence_refs=tuple(sources))
        if not passed:
            return Outcome('NOT_EVALUATED', reason='no_executable_rule', evidence_refs=tuple(sources))
        used = [refs[s] for s in ('plan', 'engine', 'result_columns', 'output') if refs.get(s)]
        return Outcome('PASS', reason=';'.join(passed), evidence_refs=tuple(dict.fromkeys(sources + used)))

    def _forbid_fields(self, evidence, executable, fails, pending, passed, refs, sources):
        if not executable:
            return
        sources += [ref for _, _, rule_refs in executable for ref in rule_refs if ref.startswith('case.forbid_rules')]
        observed, missing, used = self._identifiers(evidence)
        for rule_id, rule, _ in executable:
            for scope in rule.get('scopes') or []:
                for location, identifier, name in observed.get(scope, []):
                    if matches(identifier, rule['match']) or (name and matches(name, rule['match'])):
                        shown = identifier if not name or name == identifier else f'{identifier}({name})'
                        fails.append((rule.get('failure_code') or 'F-FORBIDDEN-FIELD', f'{rule_id}@{scope}:{location}={shown}',
                                      [r for r in (refs.get(scope),) if r]))
                        return
        needed = {scope for _, rule, _ in executable for scope in rule.get('scopes') or []}
        gaps = sorted(item for item in missing if item.split(':')[0] in needed | {'profile'})
        if gaps:
            pending.append('missing_evidence:' + ','.join(gaps))
        else:
            passed.append('forbid_field:' + ','.join(scope for scope in ('plan', 'engine', 'result_columns') if scope in used))

    @staticmethod
    def _row_sets(evidence, entries, fails, pending, passed, cited):
        if not entries:
            return
        artifacts = evidence.artifacts
        row_id = entries[0][1]['check'].get('row_id')
        inputs, gaps = aggregation_inputs(artifacts.get('plan'), artifacts.get('profile'), artifacts.get('execution_steps'),
                                          artifacts.get('dataset_rows'), row_id)
        nonempty = sum(1 for table in artifacts.get('result_tables') or [] if table)
        if not gaps and len(inputs) != nonempty:
            gaps.append(f'replay_table_count:{len(inputs)}!={nonempty}')
        if gaps:
            pending.append('row_set_unverified:' + ','.join(gaps))
            return
        violated = False
        for ref, entry in entries:
            check = entry['check']
            for task_id, reached in sorted(inputs.items()):
                extra = sorted(reached & set(check.get('forbid_rows') or []))
                lost = sorted(set(check.get('require_rows') or []) - reached)
                if extra or lost:
                    detail = f'included={"+".join(extra)}' if extra else f'missing={"+".join(lost)}'
                    fails.append((check['failure_code'], f'row_set@{ref.removeprefix("case.")}:{task_id}:{detail}', [cited(ref)]))
                    violated = True
                    break
        if not violated:
            passed.append(f'row_set:{len(entries)}')

    @staticmethod
    def _oracle_covered(evidence, entries, pending, passed):
        if not entries:
            return
        artifacts, case = evidence.artifacts, evidence.case
        tables = artifacts.get('result_tables') or []
        refs = ','.join(ref for ref, _ in entries)
        if not isinstance(artifacts.get('dataset_rows'), list) or not artifacts.get('dataset_rows'):
            pending.append('missing_evidence:dataset_rows')
        elif artifacts.get('engine_execution_status') != 'success' or not any(tables):
            pending.append('oracle_not_evaluated:' + refs)
        elif not isinstance(case.get('oracle'), dict) or not _exact_oracle(tables, case['oracle']):
            pending.append('oracle_not_pass:' + refs)
        else:
            passed.append(f'oracle_covered:{len(entries)}')

    def _guards(self, evidence, fails, passed):
        artifacts, case = evidence.artifacts, evidence.case
        guard = (self.guards.get(artifacts.get('dataset_id')) or {}).get('unique-oracle-labels')
        tables = artifacts.get('result_tables') or []
        if not guard or not isinstance(case.get('oracle'), dict) or not any(tables):
            return
        for t, column, label in duplicate_labels(tables, case['oracle']):
            fails.append((guard['failure_code'], f'unique-oracle-labels@table[{t}].{column}={label}', []))
            return

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
