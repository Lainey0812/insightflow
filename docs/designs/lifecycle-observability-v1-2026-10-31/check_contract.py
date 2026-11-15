"""Static documentation verification, not runtime instrumentation or a policy.

Only Python's standard library is used. Never import app, open SQLite, send HTTP,
or create a Trace. Results are written only into this design directory; after
freezing, reruns must be made in a separate review copy to preserve the artifact.
"""
import ast
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
checks = []


def check(name, value):
    checks.append({'check': name, 'passed': bool(value)})


def source(path):
    return ast.parse((ROOT / path).read_text())


def status_values(class_name):
    tree = source('backend/app/domain/tracing.py')
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    field = next(n for n in cls.body if isinstance(n, ast.AnnAssign) and n.target.id == 'status')
    return [n.value for n in field.annotation.slice.elts]


def find_symbol(path, symbol):
    found = {}
    def visit(nodes, parent=''):
        for n in nodes:
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                found[parent + n.name] = n
                visit(n.body, parent + n.name + '.')
    visit(source(path).body)
    return found.get(symbol)


def type_valid(value, descriptor, nodes, span_states, run_states):
    if '|' in descriptor:
        return any(type_valid(value, d, nodes, span_states, run_states) for d in descriptor.split('|'))
    if descriptor == 'null': return value is None
    if descriptor.startswith('literal:'): return value == descriptor[8:]
    if descriptor.startswith('int>='):
        return type(value) is int and value >= int(descriptor[5:])
    if descriptor == 'bool': return type(value) is bool
    if descriptor == 'id': return isinstance(value, str) and 0 < len(value) <= 128 and not re.search(r'\s', value)
    if descriptor == 'sha256': return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None
    if descriptor == 'bounded_ids':
        return isinstance(value, list) and len(value) <= 80 and all(type_valid(v, 'id', nodes, span_states, run_states) for v in value)
    if descriptor == 'controlled_ref': return isinstance(value, str) and 0 < len(value) <= 160 and not value.startswith(('/', 'file:'))
    if descriptor == 'bounded_code': return isinstance(value, str) and re.fullmatch('[A-Za-z0-9_.:/-]{1,96}', value) is not None
    if descriptor == 'node_key': return value in nodes
    if descriptor == 'span_status': return value in span_states
    if descriptor == 'run_status': return value in run_states
    if descriptor == 'utc_time':
        try:
            return isinstance(value, str) and datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() == timezone.utc.utcoffset(None)
        except (ValueError, TypeError): return False
    return value == descriptor


def event_valid(payload, event, contract, node_keys, span_states, run_states):
    if any(f not in payload for f in event['required_fields']): return False
    if payload.get('source_phase') != event['source_phase']: return False
    if any(k not in contract['field_dictionary'] for k in payload): return False
    if any(not type_valid(v, contract['field_dictionary'][k], node_keys, span_states, run_states) for k, v in payload.items()): return False
    if any(payload.get(k) not in allowed for k, allowed in event['value_constraints'].items()): return False
    if event['name'] == 'insight.candidates.summarized':
        if payload['accepted_count'] + payload['rejected_count'] != payload['candidate_count']: return False
    if event['name'] == 'report.commit.reconciled':
        expected = {'accepted': True, 'not_committed': False, 'unknown': None, 'inconsistent': None}
        if payload['accepted'] is not expected[payload['accepted_status']]: return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result-file', default='verification-final.json')
    parser.add_argument('--after-file', default='source-after-final.json')
    args = parser.parse_args()
    for name in (args.result_file, args.after_file):
        if Path(name).name != name or (HERE / name).exists():
            raise SystemExit('Use a new output filename in this directory; frozen results are never overwritten')
    d = json.loads((HERE / 'contract.json').read_text())
    refs = json.loads((HERE / 'source-index.json').read_text())
    fixtures = json.loads((HERE / 'event-fixtures.json').read_text())
    before = json.loads((HERE / 'source-before.json').read_text())
    after = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in before}
    changed = [path for path in before if before[path] != after[path]]
    check('all_old_source_config_v12_unchanged', not changed)
    check('v12_manifest_exact', all(hashlib.sha256((ROOT / 'docs/designs/lifecycle-contract-v1.2-2026-10-31' / p).read_bytes()).hexdigest() == h
        for p, h in json.loads((ROOT / 'docs/designs/lifecycle-contract-v1.2-2026-10-31/freeze-manifest.json').read_text())['sha256'].items()))
    span_states, run_states = status_values('TraceSpan'), status_values('TraceRun')
    check('span_enum_matches_actual_source', d['span_states'] == span_states)
    check('no_third_trace_level_or_attempt_entity', d['hierarchy'] == {'levels': ['workflow_root', 'node_span'], 'node_parent_span_id': None, 'attempt_entity': False})
    check('running_updates_or_terminal_only', set(d['span_transitions']['running']) == set(span_states))
    check('every_terminal_is_immutable', all(d['span_transitions'][s] == [] for s in span_states if s != 'running'))
    expected_nodes = {'data_profiler', 'intent_parser', 'analysis_planner', 'plan_validator', 'hitl', 'analysis_engine',
                      'evidence_builder', 'chart_builder', 'insight_generator', 'fact_validator', 'report_assembler', 'report_persistence'}
    keys = {n['node_key'] for n in d['nodes']}
    check('exactly_12_unique_required_nodes', keys == expected_nodes and len(d['nodes']) == 12)
    events = {e['name']: e for e in d['events']}
    check('32_unique_events', len(events) == len(d['events']) == 32)
    check('fixtures_are_not_trace_records', fixtures['not_runtime_evidence'] is True and all(f['fixture_only'] for f in fixtures['events']))
    check('every_event_has_one_schema_fixture', {f['event_name'] for f in fixtures['events']} == set(events) and len(fixtures['events']) == len(events))
    ids = {r['id'] for r in refs}
    for n in d['nodes']:
        prefix = 'node.' + n['node_key']
        check(prefix + '.maturity_label', n['current_coverage'] in {'已实现', '部分实现', '未实现'})
        check(prefix + '.rule_label', n['rule_status'] == '目标')
        check(prefix + '.all_six_states_explicit', set(n['state_evidence']) == set(span_states))
        check(prefix + '.start_end_defined', bool(n['start_condition']) and bool(n['end_condition']))
        check(prefix + '.real_complete_failure_interrupt_evidence', all(n['state_evidence'][k] for k in ['running', 'complete', 'failed', 'interrupted']))
        check(prefix + '.ids_unique', len(n['required_ids']) == len(set(n['required_ids'])))
        check(prefix + '.common_identity', all(k in n['required_ids'] for k in ['workflow_id', 'root_run_id', 'span_id', 'node_attempt', 'operation_id']))
        check(prefix + '.events_declared', set(n['event_names']) <= set(events))
        check(prefix + '.real_sources_exist', set(n['source_refs']) <= ids)
        check(prefix + '.retry_and_llm_roles', bool(n['retry_and_recovery']) and bool(n['llm_role']) and bool(n['current_gap']))
    check('coverage_not_overclaimed', sum(n['current_coverage'] == '部分实现' for n in d['nodes']) == 9 and
          {n['node_key'] for n in d['nodes'] if n['current_coverage'] == '未实现'} == {'hitl', 'analysis_engine', 'chart_builder'})
    for e in d['events']:
        prefix = 'event.' + e['name']
        check(prefix + '.fields_unique_typed', len(e['required_fields']) == len(set(e['required_fields'])) and set(e['required_fields']) <= set(d['field_dictionary']))
        check(prefix + '.versioned_common_fields', set(d['common_event_fields']) <= set(e['required_fields']))
        check(prefix + '.source_phase', e['source_phase'] in d['field_dictionary']['source_phase'].split('|'))
        check(prefix + '.source_and_trigger', set(e['source_refs']) <= ids and bool(e['trigger']) and e['rule_status'] == '目标')
    for f in fixtures['events']:
        event = events[f['event_name']]
        check('fixture.' + f['event_name'], event_valid(f['payload'], event, d, keys, span_states, run_states))
        for key in event['required_fields']:
            mutated = {k: v for k, v in f['payload'].items() if k != key}
            check('fixture.' + f['event_name'] + '.missing.' + key, not event_valid(mutated, event, d, keys, span_states, run_states))
    for r in refs:
        n = find_symbol(r['path'], r['symbol'])
        check('source.' + r['id'], n is not None and n.lineno == r['line'] and n.end_lineno == r['end_line'])
    cases = d['acceptance_cases']
    check('533_design_cases_unique', len(cases) == len({c['id'] for c in cases}) == 533)
    for c in cases:
        check('case.' + c['id'], bool(c['given']) and bool(c['expected']) and c['rule_status'] == '目标' and
              (c['node_key'] is None or c['node_key'] in keys) and (c['event_name'] is None or c['event_name'] in events))
    for key in keys:
        check('all_36_pairs.' + key, len([c for c in cases if c['node_key'] == key and c['kind'] == 'transition']) == 36)
    wanted = {'scope.two_workflows','fencing.revision','fencing.key','fencing.attempt','engine.partial','validation.blocked',
              'insight.no_evidence','trace.down','c19.after_commit','c19.before_trace','c19.trace_write_failed','c19.memory_lost',
              'legacy.report_run','registry.begin','registry.finish','c20.unavailable'}
    check('all_mandatory_acceptance_themes', wanted <= {c['id'] for c in cases})
    docs = {p.name: p.read_text() for p in HERE.glob('*.md')}
    check('seven_deliverables_exist', all(name in docs for name in ['README.md','node-instrumentation-matrix.md','event-dictionary.md',
          'trace-identity-correlation.md','recovery-failure-matrix.md','implementation-gap-report.md','phase03-c2-admission.md']))
    check('c20_gap_not_silently_extended', 'C20' in docs['implementation-gap-report.md'] and 'A04' in docs['phase03-c2-admission.md'] and '未决' in docs['recovery-failure-matrix.md'])
    check('node_sections_rendered', all('`' + n['node_key'] + '`' in docs['node-instrumentation-matrix.md'] for n in d['nodes']))
    check('event_sections_rendered', all('`' + name + '`' in docs['event-dictionary.md'] for name in events))
    gap_ids = set(re.findall(r'\| (G\d+) \|', docs['implementation-gap-report.md']))
    check('19_unique_gaps', len(gap_ids) == 19)
    check('registry_fail_closed_and_trace_fail_open_distinct', 'LLM_CAPTURE_FINALIZE_FAILED' in docs['trace-identity-correlation.md'] and
          'fail-open' in docs['trace-identity-correlation.md'])
    safe_keys = set()
    tree = source('backend/app/observability/recorder.py')
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAFE_KEYS' for t in n.targets):
            safe_keys.update(ast.literal_eval(n.value))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'SAFE_KEYS' and n.func.attr == 'update':
            safe_keys.update(ast.literal_eval(n.args[0]))
    field_gaps = sorted({f for e in d['events'] for f in e['required_fields']} - safe_keys)
    check('expected_current_field_gap_disclosed', bool(field_gaps) and 'SAFE_KEYS' in docs['implementation-gap-report.md'])
    result = {'requirement':'REQ-0082','scope':'static_document_contract_check_only','checks_total':len(checks),
              'checks_passed':sum(c['passed'] for c in checks),'checks_failed':[c['check'] for c in checks if not c['passed']],
              'protected_files':len(before),'changed_existing_files':changed,'node_count':len(keys),'event_count':len(events),
              'acceptance_design_cases':len(cases),'executed_business_tests':0,'source_references':len(refs),
              'current_event_field_gaps':field_gaps,'application_imported':False,'database_opened':False,'api_or_llm_called':False,
              'trace_created':False,'checks':checks}
    with (HERE / args.after_file).open('x') as f:
        f.write(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    with (HERE / args.result_file).open('x') as f:
        f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'checks','current_event_field_gaps'}},ensure_ascii=False,indent=2))
    if result['checks_failed']: raise SystemExit(1)


if __name__ == '__main__':
    main()
