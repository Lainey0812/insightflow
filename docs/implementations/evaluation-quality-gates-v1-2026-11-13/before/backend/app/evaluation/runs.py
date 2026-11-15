"""One read-only entry point for Golden (gf_*) and TC regression (rg_*) run directories.

Nothing here writes. Historical raw results are returned in ``legacy`` and interpretations
in ``projection`` with their sources. Historical evaluator versions are not backfilled.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .aggregate import summarize
from .contracts import (CaseExecution, Derivation, E2ESummary, EvaluationRun, EvaluatorRef, EvaluatorResult)
from .golden_fidelity import GOLD_PATH
from .manifest import CONFIG_FILE, MANIFEST_FILE, sha256_file
from .projection import classify

LEGACY_UNVERIFIED = ['agent_id', 'agent_version', 'dataset_version', 'evaluator_manifest']
LEGACY_CASE_UNVERIFIED = ['execution_id', 'attempt', 'started_at', 'finished_at', 'output_ref']
GOLDEN_LEGACY_EVALUATOR = 'insightflow.golden.score_case'
TC_LEGACY_EVALUATOR = 'insightflow.tc.checks'


class RunNotReadable(ValueError):
    pass


@dataclass(frozen=True)
class RunView:
    run: EvaluationRun
    executions: list[CaseExecution]
    evaluator_results: list[EvaluatorResult]
    e2e: list[E2ESummary]


def _json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_run(run_dir: Path, *, gold_path: Path = GOLD_PATH) -> RunView:
    run_dir = Path(run_dir)
    if run_dir.name.startswith('gf_'):
        return read_golden_run(run_dir, gold_path=gold_path)
    if run_dir.name.startswith('rg_'):
        return read_regression_run(run_dir)
    raise RunNotReadable('Unknown run directory kind: ' + run_dir.name)


def _legacy_result(execution, evaluator_id, verdict, *, reason=None, failure_code=None, basis, legacy, refs):
    return EvaluatorResult(evaluator_id=evaluator_id, evaluator_version=None, evaluator_config_hash=None,
                           case_execution_ref=execution.locator, evaluation_scope='e2e', required=True, verdict=verdict,
                           failure_code=failure_code, reason=reason, evidence_refs=refs, evaluated_at=None,
                           provenance='legacy_projection', basis=basis, legacy=legacy)


def read_golden_run(run_dir: Path, *, gold_path: Path = GOLD_PATH) -> RunView:
    if (run_dir / CONFIG_FILE).is_file():
        return _golden_recorded(run_dir)
    if not (run_dir / 'summary.json').is_file():
        raise RunNotReadable('Golden run has neither run-config.json nor summary.json')
    return _golden_legacy(run_dir, _json(run_dir / 'summary.json'), gold_path)


def _golden_recorded(run_dir: Path) -> RunView:
    config = _json(run_dir / CONFIG_FILE)
    manifest = _json(run_dir / MANIFEST_FILE) if (run_dir / MANIFEST_FILE).is_file() else None
    executions, results, summaries, missing = [], [], [], []
    for case_id in config['case_ids']:
        path = run_dir / case_id / 'result.json'
        if not path.is_file():
            missing.append(case_id)
            continue
        record = _json(path)
        executions.append(CaseExecution.model_validate(record['execution']))
        results += [EvaluatorResult.model_validate(item) for item in record['evaluator_results']]
        summaries.append(E2ESummary.model_validate(record['e2e']))
    projection = {}
    if manifest:
        actual = sha256_file(run_dir / CONFIG_FILE)
        projection['config_integrity'] = Derivation(
            value='verified' if actual == manifest.get('config_sha256') else 'mismatch',
            sources=[CONFIG_FILE, MANIFEST_FILE + '#config_sha256'], basis='SHA-256 of the config snapshot bytes against the final manifest.')
    dataset, agent = config['dataset'], config['agent']
    run = EvaluationRun(run_id=config['run_id'], run_kind='golden', provenance='recorded', agent_id=agent.get('id'),
                        agent_version=agent.get('version'), dataset_id=dataset.get('id'), dataset_version=dataset.get('version'),
                        dataset_hash=dataset.get('sha256'),
                        evaluator_manifest=[EvaluatorRef(evaluator_id=e['evaluator_id'], evaluator_version=e['evaluator_version'],
                                                         config_sha256=e['config_sha256'], required=e['required'], scope=e['scope'])
                                            for e in config['evaluators']],
                        execution_config={'model': config.get('model'), 'environment': config.get('environment'), 'policy': config.get('policy')},
                        created_at=config.get('created_at'), finished_at=(manifest or {}).get('finished_at'),
                        status='FINISHED' if manifest else 'INCOMPLETE', case_execution_refs=[e.locator for e in executions],
                        missing_case_ids=missing, projection=projection,
                        unverified=[name for name in ('agent_version', 'dataset_version') if not (agent if name == 'agent_version' else dataset).get('version')])
    return RunView(run, executions, results, summaries)


def _golden_legacy(run_dir: Path, summary: dict, gold_path: Path) -> RunView:
    run_id = summary['run_id']
    projection, unverified = {}, list(LEGACY_UNVERIFIED)
    dataset_id = None
    if gold_path.is_file() and hashlib.sha256(gold_path.read_bytes()).hexdigest() == summary.get('golden_sha256'):
        dataset_id = _json(gold_path).get('set_id')
        projection['dataset_id'] = Derivation(value=dataset_id, sources=['summary.json#golden_sha256', gold_path.name],
                                              basis='The current golden file bytes hash to the recorded golden_sha256.')
    else:
        unverified.append('dataset_id')
    projection['status'] = Derivation(value='FINISHED', sources=['summary.json'],
                                      basis='The legacy golden runner writes summary.json once, after every case.')
    executions, results, summaries = [], [], []
    for entry in summary.get('cases') or []:
        case_id = entry['case_id']
        result_path = run_dir / case_id / 'result.json'
        result = _json(result_path) if result_path.is_file() else entry
        record_ref = f'{case_id}/result.json' if result_path.is_file() else f'summary.json#cases[{case_id}]'
        trace_path = run_dir / case_id / 'trace.json'
        trace = _json(trace_path) if trace_path.is_file() else None
        trace_ok = isinstance(trace, dict) and 'trace_error' not in trace
        facts = {'runner_error': result.get('runner_error'), 'error_code': result.get('error_code'),
                 'engine_status': result.get('execution_status'), 'nodes': result.get('nodes'),
                 'approved_by_runner': result.get('approved_by_runner')}
        sources = {name: f'{record_ref}#{field}' for name, field in (('runner_error', 'runner_error'), ('error_code', 'error_code'),
                   ('engine_status', 'execution_status'), ('nodes', 'nodes'), ('approved_by_runner', 'approved_by_runner'))}
        sources = {name: ref for name, ref in sources.items() if facts.get(name) is not None}
        if trace_ok and (trace.get('business_lifecycle') or {}).get('status'):
            facts['lifecycle_status'] = trace['business_lifecycle']['status']
            sources['lifecycle_status'] = f'{case_id}/trace.json#business_lifecycle.status'
        found = classify(facts, sources)
        execution = CaseExecution(execution_id=None, locator=f'{run_id}/{case_id}', run_id=run_id, case_id=case_id, attempt=None,
                                  execution_status=found['execution_status'], failure_origin=found['failure_origin'],
                                  workflow_id=result.get('workflow_id'), started_at=None, finished_at=None, record_ref=record_ref,
                                  output_ref=None, trace_ref=f'{case_id}/trace.json' if trace_ok else None,
                                  error_code=result.get('error_code'), blocking_stage=found['blocking_stage'],
                                  provenance='legacy_projection', projection={'execution_status': found['derivation']},
                                  unverified=LEGACY_CASE_UNVERIFIED + ([] if trace_ok else ['trace_ref']), legacy=result)
        verdict = result.get('verdict') or {}
        refs = [f'{record_ref}#verdict']
        if verdict.get('status') == 'passed':
            oracle = _legacy_result(execution, GOLDEN_LEGACY_EVALUATOR, 'PASS', reason=verdict.get('reason'), legacy=verdict, refs=refs,
                                    basis='Legacy verdict passed against the oracle.')
        elif verdict.get('reason') == 'no_execution_result':
            oracle = _legacy_result(execution, GOLDEN_LEGACY_EVALUATOR, 'NOT_EVALUATED', reason='no_engine_result', legacy=verdict, refs=refs,
                                    basis='Legacy reason no_execution_result means no successful engine result was available. '
                                          'The stored failure code stays in legacy and is not a quality finding.')
        elif verdict.get('status') == 'failed' and verdict.get('failure'):
            oracle = _legacy_result(execution, GOLDEN_LEGACY_EVALUATOR, 'FAIL', reason=verdict.get('reason'),
                                    failure_code=verdict['failure'], legacy=verdict, refs=refs,
                                    basis='Legacy verdict failed after evaluating saved output.')
        else:
            oracle = _legacy_result(execution, GOLDEN_LEGACY_EVALUATOR, 'NOT_EVALUATED', reason='legacy_verdict_unrecognized',
                                    legacy=verdict, refs=refs, basis='Legacy verdict shape not recognized.')
        executions.append(execution)
        results.append(oracle)
        summaries.append(summarize(execution, [oracle]))
    run = EvaluationRun(run_id=run_id, run_kind='golden', provenance='legacy_projection', agent_id=None, agent_version=None,
                        dataset_id=dataset_id, dataset_version=None, dataset_hash=summary.get('golden_sha256'), evaluator_manifest=None,
                        execution_config={'model': summary.get('model'), 'source_fingerprint': summary.get('source_fingerprint'),
                                          'approval_note': summary.get('approval_note')},
                        created_at=summary.get('started_at'), finished_at=summary.get('finished_at'), status='FINISHED',
                        case_execution_refs=[e.locator for e in executions], projection=projection, unverified=unverified,
                        legacy={key: value for key, value in summary.items() if key != 'cases'})
    return RunView(run, executions, results, summaries)


def read_regression_run(run_dir: Path) -> RunView:
    if (run_dir / 'run.json').is_file():
        raw, status = _json(run_dir / 'run.json'), 'FINISHED'
        cases = raw.get('cases') or []
    elif (run_dir / 'run-start.json').is_file():
        raw, status = _json(run_dir / 'run-start.json'), 'INCOMPLETE'
        cases = [_json(path) for path in sorted((run_dir / 'cases').glob('TC*.json'))] if (run_dir / 'cases').is_dir() else []
    else:
        raise RunNotReadable('Regression run has neither run.json nor run-start.json')
    run_id = raw['run_id']
    present = {case['case_id'] for case in cases}
    missing = [case_id for case_id in raw.get('selected_cases') or [] if case_id not in present]
    trace_db = run_dir / 'data' / 'observability' / 'trace.sqlite3'
    executions, results, summaries, not_started = [], [], [], []
    for case in cases:
        case_id = case['case_id']
        if case.get('status') == 'not_run':
            not_started.append(case_id)
            continue
        record_ref = f'cases/{case_id}.json' if (run_dir / 'cases' / f'{case_id}.json').is_file() else f'run.json#cases[{case_id}]'
        fields = {'runner_error': 'runner_error', 'error_code': 'error_code', 'engine_status': 'execution_status',
                  'session_status': 'final_status', 'lifecycle_status': 'business_status', 'nodes': 'nodes',
                  'approved_by_runner': 'approved_by_runner', 'can_approve': 'can_approve'}
        facts = {name: case.get(field) for name, field in fields.items()}
        sources = {name: f'{record_ref}#{field}' for name, field in fields.items() if case.get(field) is not None}
        found = classify(facts, sources)
        expect_blocked = any(check.get('key') == 'stopped' for check in case.get('checks') or [])
        workflow_id = case.get('workflow_id')
        execution = CaseExecution(execution_id=None, locator=f'{run_id}/{case_id}', run_id=run_id, case_id=case_id, attempt=None,
                                  execution_status=found['execution_status'], failure_origin=found['failure_origin'],
                                  workflow_id=workflow_id, started_at=None, finished_at=None, record_ref=record_ref, output_ref=None,
                                  trace_ref=f'data/observability/trace.sqlite3#workflow_id={workflow_id}' if workflow_id and trace_db.is_file() else None,
                                  error_code=case.get('error_code'), blocking_stage=found['blocking_stage'], expect_blocked=expect_blocked,
                                  provenance='legacy_projection',
                                  projection={'execution_status': found['derivation'],
                                              'expect_blocked': Derivation(value=expect_blocked, sources=[f'{record_ref}#checks'],
                                                  basis='The legacy scorer adds a "stopped" check only to cases that should stop before execution.')},
                                  unverified=LEGACY_CASE_UNVERIFIED, legacy=case)
        legacy_status, refs = case.get('status'), [f'{record_ref}#status', f'{record_ref}#checks']
        failed = next((check['key'] for check in case.get('checks') or [] if check.get('status') == 'fail'), None)
        mapping = {'passed': ('PASS', None, 'legacy_passed', 'Legacy TC status passed.'),
                   'failed': ('FAIL', f'check:{failed}' if failed else None, 'legacy_failed', 'Legacy TC status failed; first failed check named.'),
                   'needs_review': ('NOT_EVALUATED', None, 'no_automatic_checks', 'Legacy TC had no automatic checks.'),
                   'blocked': ('NOT_EVALUATED', None, 'legacy_blocked', 'Legacy TC blocked by runner or model availability; not a quality verdict.')}
        verdict, code, reason, basis = mapping.get(legacy_status, ('NOT_EVALUATED', None, 'legacy_status_unrecognized', 'Unrecognized legacy status.'))
        checks = _legacy_result(execution, TC_LEGACY_EVALUATOR, verdict, reason=reason, failure_code=code, basis=basis,
                                legacy={'status': legacy_status, 'checks': case.get('checks')}, refs=refs)
        executions.append(execution)
        results.append(checks)
        summaries.append(summarize(execution, [checks]))
    suite = raw.get('suite') or {}
    run = EvaluationRun(run_id=run_id, run_kind='tc_regression', provenance='legacy_projection', agent_id=None, agent_version=None,
                        dataset_id=suite.get('version'), dataset_version=None, dataset_hash=suite.get('cases_sha256'),
                        evaluator_manifest=None,
                        execution_config={'environment': raw.get('environment'), 'source_fingerprint': raw.get('source_fingerprint'),
                                          'approval_policy': raw.get('approval_policy'), 'label': raw.get('label')},
                        created_at=raw.get('started_at'), finished_at=raw.get('finished_at'), status=status,
                        case_execution_refs=[e.locator for e in executions], missing_case_ids=missing if status == 'INCOMPLETE' else [],
                        not_started_case_ids=not_started,
                        projection={'status': Derivation(value=status, sources=['run.json' if status == 'FINISHED' else 'run-start.json'],
                                                         basis='The TC runner writes run.json once after all cases; run-start.json alone means unfinished.')},
                        unverified=LEGACY_UNVERIFIED, legacy={key: value for key, value in raw.items() if key != 'cases'})
    return RunView(run, executions, results, summaries)
