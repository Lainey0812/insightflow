"""Golden Set run that saves unified records. The agent is driven through an injected callable.

Files in the run directory are created once: run-config.json before the first case,
<case>/trace.json and <case>/result.json after each case, then summary.json and run-manifest.json.
"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .aggregate import summarize
from .contracts import CaseExecution
from .evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator
from .manifest import CONFIG_FILE, CONFIG_SCHEMA, MANIFEST_FILE, MANIFEST_SCHEMA, write_once
from .metrics import compute
from .must_forbid import MustForbidEvaluator
from .projection import classify
from .protocol import EvaluationEvidence, config_hash, requirement_policy, run_evaluator

CASE_SCHEMA = 'golden-fidelity-case-v2'
SUMMARY_SCHEMA = 'golden-fidelity-run-v2'
AGENT_ID = 'insightflow'
ORACLE_ID = GoldenOracleEvaluator.evaluator_id
OBSERVED_KEYS = ('final_status', 'error_code', 'execution_status', 'approved_by_runner', 'can_approve', 'runner_error',
                 'workflow_id', 'business_status', 'result_tables', 'plan', 'profile', 'execution_steps', 'duration_ms',
                 'prompt_templates', 'nodes', 'fidelity')
FACT_FIELDS = {'runner_error': 'runner_error', 'error_code': 'error_code', 'engine_status': 'execution_status',
               'session_status': 'final_status', 'nodes': 'nodes', 'approved_by_runner': 'approved_by_runner',
               'can_approve': 'can_approve'}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_evaluators():
    return [(GoldenOracleEvaluator(), 'required'), (MustForbidEvaluator(), 'required_when_applicable'),
            (RequirementFidelityNodeEvaluator(), 'optional')]


def build_config(run_id, document, gold_bytes, gold_ref, evaluators, *, model, environment, created_at):
    return {'schema_version': CONFIG_SCHEMA, 'run_id': run_id, 'run_kind': 'golden', 'created_at': created_at,
            'dataset': {'id': document.get('set_id'), 'version': document.get('version'), 'ref': gold_ref,
                        'sha256': hashlib.sha256(gold_bytes).hexdigest()},
            'case_ids': [case['case_id'] for case in document['cases']],
            'evaluators': [{'evaluator_id': e.evaluator_id, 'evaluator_version': e.evaluator_version,
                            'config_sha256': config_hash(e), 'required': {'required': True, 'optional': False}.get(policy),
                            'requirement': policy, 'scope': e.scope}
                           for e, policy in ((e, requirement_policy(r)) for e, r in evaluators)],
            'agent': {'id': AGENT_ID, 'version': None},
            'model': model, 'environment': environment,
            'policy': {'approval': 'The runner approves only when the review reports can_approve; otherwise it stops.',
                       'attempts_per_case': 1, 'timeout': 'The existing runner wait deadline; unchanged.'}}


def build_execution(run_id, case_id, observed, trace, started_at, finished_at) -> CaseExecution:
    trace_ok = isinstance(trace, dict) and 'trace_error' not in trace
    facts = {name: observed.get(field) for name, field in FACT_FIELDS.items()}
    sources = {name: f'{case_id}/result.json#observed.{field}' for name, field in FACT_FIELDS.items() if observed.get(field) is not None}
    if trace_ok and (trace.get('business_lifecycle') or {}).get('status'):
        facts['lifecycle_status'] = trace['business_lifecycle']['status']
        sources['lifecycle_status'] = f'{case_id}/trace.json#business_lifecycle.status'
    found = classify(facts, sources)
    tables = observed.get('result_tables') or []
    return CaseExecution(execution_id=f'{run_id}:{case_id}:1', locator=f'{run_id}/{case_id}', run_id=run_id, case_id=case_id,
                         attempt=1, execution_status=found['execution_status'], failure_origin=found['failure_origin'],
                         workflow_id=observed.get('workflow_id'), started_at=started_at, finished_at=finished_at,
                         record_ref=f'{case_id}/result.json',
                         output_ref=f'{case_id}/result.json#observed.result_tables' if any(tables) else None,
                         trace_ref=f'{case_id}/trace.json' if trace_ok else None, error_code=observed.get('error_code'),
                         blocking_stage=found['blocking_stage'], provenance='recorded',
                         projection={'execution_status': found['derivation']})


def run_golden(run_dir: Path, document, gold_bytes: bytes, gold_ref: str, *, run_one: Callable, model: dict,
               environment: dict, evaluators=None, clock: Callable[[], str] = utc_now, on_case: Callable | None = None):
    """run_one(case) -> (observed, trace). An exception from run_one leaves an incomplete run on disk."""
    evaluators = evaluators or default_evaluators()
    run_id = run_dir.name
    created_at = clock()
    config = build_config(run_id, document, gold_bytes, gold_ref, evaluators, model=model, environment=environment, created_at=created_at)
    config_sha = write_once(run_dir / CONFIG_FILE, config)
    executions, results, summaries, files, prompts = [], [], [], [], {}
    for item in document['cases']:
        case_id = item['case_id']
        started_at = clock()
        observed, trace = run_one(item)
        finished_at = clock()
        execution = build_execution(run_id, case_id, observed, trace, started_at, finished_at)
        artifacts = {'result_tables': observed.get('result_tables') or [], 'plan': observed.get('plan') or {},
                     'profile': observed.get('profile') or {}, 'engine_execution_status': observed.get('execution_status'),
                     'execution_steps': observed.get('execution_steps'), 'fidelity': observed.get('fidelity'),
                     'dataset_id': document.get('set_id'), 'dataset_rows': document.get('rows')}
        refs = {'output': execution.output_ref, 'plan': f'{case_id}/result.json#observed.plan',
                'engine': f'{case_id}/result.json#observed.execution_steps',
                'result_columns': f'{case_id}/result.json#observed.result_tables',
                'fidelity': f'{case_id}/result.json#observed.fidelity', 'case': f'{gold_ref}#cases[{case_id}]'}
        evidence = EvaluationEvidence(case=item, execution=execution, artifacts=artifacts, refs=refs)
        case_results = [run_evaluator(evaluator, evidence, required=required, now=clock) for evaluator, required in evaluators]
        e2e = summarize(execution, case_results)
        trace_sha = write_once(run_dir / case_id / 'trace.json', trace if trace is not None else {'trace_error': 'no_workflow'})
        record = {'schema_version': CASE_SCHEMA, 'case_id': case_id, 'execution': execution.model_dump(mode='json'),
                  'evaluator_results': [r.model_dump(mode='json') for r in case_results], 'e2e': e2e.model_dump(mode='json'),
                  'observed': {key: observed.get(key) for key in OBSERVED_KEYS}}
        result_sha = write_once(run_dir / case_id / 'result.json', record)
        for node, ids in (observed.get('prompt_templates') or {}).items():
            prompts.setdefault(node, set()).update(ids)
        executions.append(execution)
        results += case_results
        summaries.append(e2e)
        files.append({'case_id': case_id, 'result_ref': f'{case_id}/result.json', 'result_sha256': result_sha,
                      'trace_ref': f'{case_id}/trace.json', 'trace_sha256': trace_sha})
        if on_case:
            on_case(execution, case_results, e2e)
    finished_at = clock()
    summary = {'schema_version': SUMMARY_SCHEMA, 'run_id': run_id, 'started_at': created_at, 'finished_at': finished_at,
               'dataset_sha256': config['dataset']['sha256'], 'model': model.get('name'),
               'source_fingerprint': environment.get('source_fingerprint'),
               'metrics': compute(executions, summaries, results, oracle_evaluator_id=ORACLE_ID),
               'cases': [{'case_id': e.case_id, 'execution_status': e.execution_status, 'blocking_stage': e.blocking_stage,
                          'error_code': e.error_code, 'workflow_id': e.workflow_id, 'e2e': s.verdict, 'e2e_reason': s.reason,
                          'oracle': next((r.verdict for r in results if r.case_execution_ref == e.locator and r.evaluator_id == ORACLE_ID), None)}
                         for e, s in zip(executions, summaries)]}
    summary_sha = write_once(run_dir / 'summary.json', summary)
    write_once(run_dir / MANIFEST_FILE, {
        'schema_version': MANIFEST_SCHEMA, 'run_id': run_id, 'status': 'FINISHED', 'finished_at': finished_at,
        'config_ref': CONFIG_FILE, 'config_sha256': config_sha, 'summary_ref': 'summary.json', 'summary_sha256': summary_sha,
        'cases': files, 'observed_prompt_snapshots': {node: sorted(ids) for node, ids in sorted(prompts.items())}})
    return summary
