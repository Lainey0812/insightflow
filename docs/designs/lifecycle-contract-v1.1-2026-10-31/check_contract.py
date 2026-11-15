"""Static documentation checks only. Never import application code or open databases.

This script is not a Workflow Policy Validator or Lifecycle Aggregator. It checks
frozen tables and source AST evidence; no real command is evaluated or executed.
Run with: python docs/designs/lifecycle-contract-v1.1-2026-10-31/check_contract.py
"""
from pathlib import Path
import ast
import hashlib
import itertools
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
checks = []


def check(name, condition):
    checks.append({'check': name, 'passed': bool(condition)})


def parse(path):
    return ast.parse((ROOT / path).read_text())


def literals(tree, name):
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return [v.value for v in node.value.slice.elts]


def control_edges():
    tree = parse('backend/app/workflow/transitions.py')
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'ALLOWED' for t in n.targets))
    return {k.attr: sorted(x.attr for x in v.elts) for k, v in zip(node.keys, node.values)}


def dict_assignment(tree, name):
    return next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def dict_sets(node):
    return {k.value: sorted(ast.literal_eval(v)) for k, v in zip(node.keys, node.values)}


def source_symbols(path):
    found = {}
    def visit(nodes, prefix=''):
        for n in nodes:
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + n.name] = n
                visit(n.body, prefix + n.name + '.')
    visit(parse(path).body)
    return found


def main():
    contract = json.loads((HERE / 'contract-tables.json').read_text())
    doc = (HERE / 'README.md').read_text()
    baseline = json.loads((HERE / 'source-before.json').read_text())
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in baseline}
    changed = [name for name in baseline if baseline[name] != after[name]]
    check('source_and_v1_0_and_phase02_unchanged', not changed)
    check('business_lifecycle_enum_unchanged', contract['business_lifecycle'] == literals(parse('backend/app/domain/lifecycle.py'), 'LifecycleStatus'))
    check('activity_enum_unchanged', contract['activity'] == literals(parse('backend/app/domain/lifecycle.py'), 'Activity'))
    legacy = contract['legacy_control_transitions']['matrix']
    target = contract['target_control_transitions']['matrix']
    check('legacy_allowed_exact_match_current_ast', legacy == control_edges())
    statuses = set(legacy)
    check('both_control_matrices_have_12_states', len(statuses) == 12 and set(target) == statuses)
    check('no_unknown_control_targets', all(set(v) <= statuses for v in target.values()))
    check('legacy_completed_revision_preserved', legacy['COMPLETED'] == ['AWAITING_APPROVAL'])
    check('native_completed_no_reopen', target['COMPLETED'] == [])
    check('native_preparing_has_no_route', target['PREPARING'] == [])
    source_root = dict_sets(dict_assignment(parse('backend/app/storage/trace_repository.py'), 'allowed_root'))
    observed = contract['legacy_root_transitions']['matrix']
    check('legacy_preparation_root_exact_source_edges', all(sorted(observed[k]) == v for k, v in source_root.items()) and all(observed[k] == [] for k in set(observed) - set(source_root)))
    check('root_complete_never_reopens', contract['target_root_transitions']['matrix']['complete'] == [])
    check('root_unavailable_not_new_native_write', all('unavailable' not in v for v in contract['target_root_transitions']['matrix'].values()))
    check('generation_terminal_retry_not_permitted', contract['generation_transitions']['matrix']['completed'] == [] and contract['generation_transitions']['matrix']['unavailable'] == [])

    command_errors = []
    for c in contract['commands']:
        owner, src, dst = c['owner'], c['source'], c['target']
        if owner == 'control':
            valid = src in target and (dst in target[src] or src == dst)
        elif owner == 'generation':
            valid = (src is None and dst == 'queued') or dst in contract['generation_transitions']['matrix'].get(src, [])
        else:
            valid = owner == 'creation' and src is None and dst == 'CREATED'
        if not valid or not c['guard'] or not c['persistent_evidence']:
            command_errors.append(c['id'])
        check('command_documented_' + c['id'], all(str(x) in doc for x in [c['id'], c['name'], c['guard'], c['persistent_evidence']]))
    check('every_permitted_command_has_edge_guard_and_evidence', not command_errors)
    check('command_ids_unique', len({c['id'] for c in contract['commands']}) == len(contract['commands']))

    cases = contract['engine_report_matrix']
    pairs = [(c['execution_outcome'], c['report_stage']) for c in cases]
    expected = set(itertools.product(['success', 'partial_success', 'failed'], ['absent', 'queued', 'generating', 'failed', 'unavailable', 'delivered_complete', 'delivered_partial']))
    check('21_result_combinations_exhaustive_unique', set(pairs) == expected and len(pairs) == 21)
    for c in cases:
        case = c['id']
        check('combination_documented_' + case, all(str(c[k]) in doc for k in ['id', 'execution_outcome', 'report_stage', 'business_lifecycle', 'activity', 'delivery_status']))
        check('lifecycle_enum_' + case, c['business_lifecycle'] in contract['business_lifecycle'])
        check('activity_enum_' + case, c['activity'] in contract['activity'])
        check('required_reason_codes_' + case, set(c['reason_codes']) <= set(literals(parse('backend/app/domain/lifecycle.py'), 'Reason')))
        if c['execution_outcome'] == 'partial_success':
            check('partial_never_hidden_' + case, c['business_lifecycle'] == 'partially_succeeded' and 'execution_partial' in c['reason_codes'])
        if c['business_lifecycle'] == 'succeeded':
            check('success_requires_complete_delivery_' + case, c['execution_outcome'] == 'success' and c['report_stage'] == 'delivered_complete' and c['delivery_status'] == 'delivered')
        if c['report_stage'] in {'absent', 'queued', 'generating', 'failed', 'unavailable'}:
            check('not_delivered_without_report_' + case, c['delivery_status'] == 'not_delivered')
        if c['execution_outcome'] == 'failed' and c['report_stage'].startswith('delivered'):
            check('failed_cannot_have_successful_report_' + case, c['business_lifecycle'] == 'unknown' and c['consistency'] == 'inconsistent')
    check('51_result_and_additional_fixtures', len(cases) + len(contract['acceptance_cases']) == 51)
    labels = set(contract['implementation_labels'])
    check('all_structured_rules_labelled', all(x['status'] in labels for x in contract['commands'] + cases + contract['acceptance_cases']))
    for c in contract['acceptance_cases']:
        check('acceptance_case_documented_' + c['id'], all(c[k] in doc for k in ['id', 'given', 'expected']))
    check('no_unrendered_tables', '<!-- GENERATED:' not in doc)

    refs = json.loads((HERE / 'source-evidence.json').read_text())
    for r in refs:
        node = source_symbols(r['path']).get(r['symbol'])
        check('source_reference_' + r['id'], node is not None and node.lineno == r['line'] and node.end_lineno == r['end_line'])
    check('63_actual_source_symbols', len(refs) == 63)
    check('dimension_aliases_not_api_migration', contract['dimension_mapping']['api_modified'] is False)
    check('new_span_flattening_target_not_claimed_current', 'parent_span_id必须为空' in doc and '通用Schema/SpanHandle仍支持嵌套' in doc)
    check('unsupported_engine_resume_explicit', 'Resume Engine task/step' in doc and '**不支持**' in doc)
    check('registry_and_trace_failures_separated', 'LLM_CAPTURE_FINALIZE_FAILED' in doc and 'TraceRecorder受控日志' in doc)
    check('legacy_broad_approval_guard_disclosed', '没有独立 `status == AWAITING_APPROVAL` 检查' in doc)
    check('all_p0_p1_documented', all(x in doc for x in ['execution_outcome', 'delivery_status', 'Recover / Retry / Resume', 'Workflow Fencing', 'Legacy', 'unavailable', 'PromptRegistry']))

    report = {'requirement': 'REQ-0079', 'contract_version': '1.1', 'design_check_only': True,
              'checks_total': len(checks), 'checks_passed': sum(c['passed'] for c in checks),
              'checks_failed': [c['check'] for c in checks if not c['passed']],
              'source_and_previous_documents_verified': len(baseline), 'changed_protected_files': changed,
              'command_rows': len(contract['commands']), 'engine_report_combinations': len(cases),
              'additional_acceptance_cases': len(contract['acceptance_cases']), 'source_references': len(refs),
              'application_imported': False, 'database_opened': False, 'http_or_llm_called': False,
              'business_regression_run': False, 'checks': checks}
    (HERE / 'source-after.json').write_text(json.dumps(after, indent=2, ensure_ascii=False) + '\n')
    (HERE / 'verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, indent=2, ensure_ascii=False))
    if report['checks_failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
