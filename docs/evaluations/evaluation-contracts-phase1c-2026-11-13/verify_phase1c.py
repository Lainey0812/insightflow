"""Phase 1-C integration acceptance for the evaluation contracts (REQ-0142).

Scripted agent only; no model calls. Runs are created in a temporary directory and copied
into ./outputs afterwards. Historical runs are only read. Production code is not modified;
monkeypatching is limited to this process.

Usage (from insightflow/):
    .venv/bin/python docs/evaluations/evaluation-contracts-phase1c-2026-11-13/verify_phase1c.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import app.evaluation.golden_fidelity as golden_fidelity  # noqa: E402
from app.evaluation.aggregate import summarize  # noqa: E402
from app.evaluation.contracts import CaseExecution, EvaluatorResult  # noqa: E402
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator  # noqa: E402
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden  # noqa: E402
from app.evaluation.golden_run import ORACLE_ID, default_evaluators, run_golden  # noqa: E402
from app.evaluation.manifest import CONFIG_FILE, MANIFEST_FILE  # noqa: E402
from app.evaluation.metrics import compute  # noqa: E402
from app.evaluation.protocol import EvaluationEvidence, run_evaluator  # noqa: E402
from app.evaluation.runs import GOLDEN_LEGACY_EVALUATOR, read_run  # noqa: E402

HISTORICAL = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs/gf_20261112-143406_cde1fd'
TC_RUN = ROOT.parent / 'var/regression/runs/rg_20261112-133157_f04289'
OUTPUTS = Path(os.environ.get('PHASE1C_OUTPUTS') or HERE / 'outputs')
TICK = iter(range(10_000))
CLOCK = lambda: f'2026-11-13T00:00:{next(TICK) % 60:02d}+00:00'
checks = []


def check(section, name, ok, evidence=None):
    """ok=None records a fact (INFO) that is neither a pass nor a failure."""
    result = 'INFO' if ok is None else 'PASS' if ok else 'FAIL'
    checks.append({'section': section, 'check': name, 'result': result, 'evidence': evidence})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_set():
    shared = {'nodes': [{'name': 'data_profiler', 'status': 'success'}, {'name': 'intent_parser', 'status': 'success'}],
              'profile': {'fields': [{'field_id': 'f1', 'display_name': '城市'}, {'field_id': 'f4', 'display_name': '岗位类型'}]}}
    waiting = {**shared, 'final_status': 'AWAITING_APPROVAL', 'can_approve': False, 'approved_by_runner': False,
               'fidelity': {'status': 'not_in_gold'}}
    rows = lambda pairs: [[{'城市': c, '岗位数量': n} for c, n in pairs]]
    done = lambda wf, pairs, fidelity, prompts: ({**shared, 'workflow_id': wf, 'final_status': 'COMPLETED', 'execution_status': 'success',
                                                  'approved_by_runner': True, 'result_tables': rows(pairs), 'fidelity': fidelity,
                                                  'plan': {'tasks': [{'steps': [{'params': {'field': 'f4'}}]}]}, 'prompt_templates': prompts},
                                                 {'business_lifecycle': {'status': 'succeeded'}})
    return {
        'RF-01': ({**waiting, 'workflow_id': 'wf_1'}, {'business_lifecycle': {'status': 'waiting_approval'}}),
        'RF-02': done('wf_2', [('上海', 4), ('深圳', 3)], {'status': 'scored', 'lost': []}, {'intent_parser': ['pt_a']}),
        'RF-03': ({**waiting, 'workflow_id': 'wf_3'}, {'business_lifecycle': {'status': 'waiting_approval'}}),
        'RF-04': ({**shared, 'workflow_id': 'wf_4', 'final_status': 'FAILED', 'error_code': 'PLANNER_BUSINESS_INVALID',
                   'fidelity': {'status': 'collector_error', 'error': 'KeyError'},
                   'nodes': shared['nodes'] + [{'name': 'analysis_planner', 'status': 'error'}]},
                  {'business_lifecycle': {'status': 'failed'}}),
        'RF-05': done('wf_5', [('深圳', 3), ('北京', 1), ('杭州', 1)], {'status': 'scored', 'lost': [{'lost_at': 'engine', 'detail': 'x'}]},
                      {'intent_parser': ['pt_a'], 'analysis_planner': ['pt_b']}),
    }


class Spy:
    """Delegates to a real evaluator and records each call, so the runner path can be proven."""

    def __init__(self, inner, calls):
        self.inner, self.calls = inner, calls
        self.evaluator_id, self.evaluator_version, self.scope = inner.evaluator_id, inner.evaluator_version, inner.scope

    def config(self):
        return self.inner.config()

    def applicable(self, evidence):
        return self.inner.applicable(evidence)

    def evaluate(self, evidence):
        self.calls.append((self.evaluator_id, evidence.case['case_id'], evidence.execution.execution_status))
        return self.inner.evaluate(evidence)


def scripted(run_dir, fail_at=None, order=None):
    observed = observed_set()

    def run_one(item):
        if order is not None:
            order.append({'case_id': item['case_id'], 'config_exists': (run_dir / CONFIG_FILE).is_file(),
                          'manifest_exists': (run_dir / MANIFEST_FILE).exists()})
        if item['case_id'] == fail_at:
            raise RuntimeError('scripted interruption')
        return observed[item['case_id']]
    return run_one


def start(run_dir, run_one, evaluators=None, on_case=None):
    return run_golden(run_dir, load_golden(), GOLD_PATH.read_bytes(), 'golden-set.json', run_one=run_one,
                      model={'name': 'scripted'}, environment={'source_fingerprint': 'phase1c'},
                      evaluators=evaluators, clock=CLOCK, on_case=on_case)


def manifest_hash_report(run_dir):
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text())
    rows = [{'ref': CONFIG_FILE, 'recorded': manifest['config_sha256'], 'actual': sha(run_dir / CONFIG_FILE)},
            {'ref': manifest['summary_ref'], 'recorded': manifest['summary_sha256'], 'actual': sha(run_dir / manifest['summary_ref'])}]
    for item in manifest['cases']:
        rows.append({'ref': item['result_ref'], 'recorded': item['result_sha256'], 'actual': sha(run_dir / item['result_ref'])})
        rows.append({'ref': item['trace_ref'], 'recorded': item['trace_sha256'], 'actual': sha(run_dir / item['trace_ref'])})
    for row in rows:
        row['match'] = row['recorded'] == row['actual']
    listed = {row['ref'] for row in rows} | {MANIFEST_FILE}
    unlisted = sorted(str(p.relative_to(run_dir)) for p in run_dir.rglob('*') if p.is_file() and str(p.relative_to(run_dir)) not in listed)
    return rows, unlisted


def integration(tmp):
    section = '1-integration'
    # A. Normal run through spy evaluators; the legacy score_case is replaced with a tripwire.
    tripwire = []
    original = golden_fidelity.score_case
    golden_fidelity.score_case = lambda *a, **k: tripwire.append(a) or (_ for _ in ()).throw(AssertionError('legacy score_case used'))
    calls, order = [], []
    normal = tmp / 'gf_20261113-000000_c1aaaa'
    try:
        summary = start(normal, scripted(normal, order=order),
                        evaluators=[(Spy(GoldenOracleEvaluator(), calls), True), (Spy(RequirementFidelityNodeEvaluator(), calls), False)])
    finally:
        golden_fidelity.score_case = original
    oracle_calls = [c for c in calls if c[0] == ORACLE_ID]
    check(section, '1. runner calls the new evaluators, not legacy score_case',
          not tripwire and len({c[1] for c in oracle_calls}) == 5,
          {'evaluate_calls': calls, 'legacy_score_case_calls': len(tripwire)})

    per_case = {}
    for case_id in ('RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05'):
        record = json.loads((normal / case_id / 'result.json').read_text())
        locator = record['execution']['locator']
        per_case[case_id] = {'execution_status': record['execution']['execution_status'], 'locator': locator,
                             'evaluators': {r['evaluator_id']: r['verdict'] for r in record['evaluator_results']},
                             'all_results_reference_this_execution': all(r['case_execution_ref'] == locator for r in record['evaluator_results']),
                             'e2e': record['e2e']['verdict'], 'e2e_reason': record['e2e']['reason']}
    check(section, '2. each case has its own execution status and evaluator results',
          len({v['locator'] for v in per_case.values()}) == 5 and all(v['all_results_reference_this_execution'] and len(v['evaluators']) == 2 for v in per_case.values()),
          per_case)
    check(section, '3. run-config.json exists before the first case and manifest does not',
          all(o['config_exists'] and not o['manifest_exists'] for o in order), order)
    rows, unlisted = manifest_hash_report(normal)
    manifest = json.loads((normal / MANIFEST_FILE).read_text())
    check(section, '4. run-manifest.json written after completion', manifest['status'] == 'FINISHED' and len(manifest['cases']) == 5,
          {'status': manifest['status'], 'cases': len(manifest['cases'])})
    check(section, '5. manifest hashes equal actual file hashes', all(r['match'] for r in rows), {'files': rows, 'not_listed_in_manifest': unlisted})

    view = read_run(normal)
    stored = [json.loads((normal / c / 'result.json').read_text()) for c in per_case]
    round_trip = ([e.model_dump(mode='json') for e in view.executions] == [s['execution'] for s in stored]
                  and [r.model_dump(mode='json') for r in view.evaluator_results] == [r for s in stored for r in s['evaluator_results']]
                  and [s.model_dump(mode='json') for s in view.e2e] == [s['e2e'] for s in stored])
    check(section, '6. read_run reads the new run completely',
          view.run.status == 'FINISHED' and view.run.provenance == 'recorded' and not view.run.missing_case_ids and round_trip
          and view.run.projection['config_integrity'].value == 'verified',
          {'status': view.run.status, 'executions': len(view.executions), 'evaluator_results': len(view.evaluator_results),
           'e2e': len(view.e2e), 'byte_identical_round_trip': round_trip,
           'evaluator_manifest': [e.model_dump() for e in view.run.evaluator_manifest]})
    recomputed = compute(view.executions, view.e2e, view.evaluator_results, oracle_evaluator_id=ORACLE_ID)
    check(section, '7. metrics recomputed from read_run equal the runner summary', recomputed == summary['metrics'],
          {'recomputed': recomputed})

    # B. Default evaluator registration, no spies.
    default = tmp / 'gf_20261113-000000_c1bbbb'
    start(default, scripted(default))
    config = json.loads((default / CONFIG_FILE).read_text())
    registered = [(e['evaluator_id'], e['required']) for e in config['evaluators']]
    check(section, 'default evaluator registration recorded in config', registered == [(ORACLE_ID, True), ('insightflow.node.requirement_fidelity', False)],
          {'registered': registered, 'default_evaluators': [(e.evaluator_id, r) for e, r in default_evaluators()]})

    # C. Interruption inside run_one at RF-03.
    cut = tmp / 'gf_20261113-000000_c1cccc'
    try:
        start(cut, scripted(cut, fail_at='RF-03'))
        raised = False
    except RuntimeError:
        raised = True
    cut_view = read_run(cut)
    check(section, '8a. interruption during a case reads as INCOMPLETE with config kept',
          raised and (cut / CONFIG_FILE).is_file() and not (cut / MANIFEST_FILE).exists() and cut_view.run.status == 'INCOMPLETE'
          and cut_view.run.missing_case_ids == ['RF-03', 'RF-04', 'RF-05'],
          {'status': cut_view.run.status, 'missing': cut_view.run.missing_case_ids, 'finished_at': cut_view.run.finished_at,
           'files': sorted(str(p.relative_to(cut)) for p in cut.rglob('*') if p.is_file())})

    # D. Interruption after every case result is written but before summary and manifest.
    late = tmp / 'gf_20261113-000000_c1dddd'

    def stop_after_last(execution, results, e2e):
        if execution.case_id == 'RF-05':
            raise KeyboardInterrupt('scripted stop after last case')
    try:
        start(late, scripted(late), on_case=stop_after_last)
        stopped = False
    except KeyboardInterrupt:
        stopped = True
    late_view = read_run(late)
    check(section, '8b. all cases written but no manifest still reads INCOMPLETE, never FINISHED',
          stopped and late_view.run.status == 'INCOMPLETE' and not late_view.run.missing_case_ids and not (late / 'summary.json').exists(),
          {'status': late_view.run.status, 'missing': late_view.run.missing_case_ids,
           'files': sorted(str(p.relative_to(late)) for p in late.rglob('*') if p.is_file())})

    # E. Observation: does read_run notice a case file changed after the manifest?
    tampered = tmp / 'gf_20261113-000000_c1eeee'
    shutil.copytree(normal, tampered)
    path = tampered / 'RF-02' / 'result.json'
    record = json.loads(path.read_text())
    record['e2e']['verdict'] = 'FAIL'
    path.write_text(json.dumps(record, ensure_ascii=False))
    t_view = read_run(tampered)
    check('5-integrity', 'read_run detects a case result edited after the manifest',
          t_view.run.status != 'FINISHED' or t_view.run.projection['config_integrity'].value != 'verified',
          {'status': t_view.run.status, 'config_integrity': t_view.run.projection['config_integrity'].value,
           'RF-02_e2e_after_edit': next(s.verdict for s in t_view.e2e if s.case_id == 'RF-02'),
           'note': 'read_run compares only config_sha256; per-case and summary hashes in the manifest are not checked on read.'})
    return {'normal': normal, 'interrupted_mid_case': cut, 'interrupted_before_manifest': late}


def execution(status, origin=None, case_id='RF-04'):
    return CaseExecution(execution_id=None, locator=f'run/{case_id}', run_id='run', case_id=case_id, attempt=1, execution_status=status,
                         failure_origin=origin, workflow_id=None, started_at=None, finished_at=None, record_ref=None, output_ref=None,
                         trace_ref=None, error_code=None, blocking_stage=None, provenance='recorded')


def verdict(evaluator_id, value, required=True, case_id='RF-04'):
    return EvaluatorResult(evaluator_id=evaluator_id, evaluator_version='v', evaluator_config_hash=None, case_execution_ref=f'run/{case_id}',
                           evaluation_scope='e2e', required=required, verdict=value, failure_code='X' if value == 'FAIL' else None,
                           evaluated_at=None, provenance='recorded')


def gates():
    section = '2-gates'
    forbid = 'hypothetical.rf04.must_forbid'
    scenarios = [
        ('oracle PASS + required forbid PASS', 'COMPLETED', [('oracle', 'PASS', True), (forbid, 'PASS', True)], 'PASS'),
        ('oracle PASS + required forbid FAIL', 'COMPLETED', [('oracle', 'PASS', True), (forbid, 'FAIL', True)], 'FAIL'),
        ('oracle PASS + required forbid NOT_EVALUATED', 'COMPLETED', [('oracle', 'PASS', True), (forbid, 'NOT_EVALUATED', True)], 'NOT_EVALUATED'),
        ('oracle PASS + required forbid EVALUATOR_ERROR', 'COMPLETED', [('oracle', 'PASS', True), (forbid, 'EVALUATOR_ERROR', True)], 'EVALUATOR_ERROR'),
        ('agent FAILED + oracle NOT_EVALUATED', 'FAILED', [('oracle', 'NOT_EVALUATED', True)], 'FAIL'),
        ('oracle PASS + optional EVALUATOR_ERROR', 'COMPLETED', [('oracle', 'PASS', True), ('node', 'EVALUATOR_ERROR', False)], 'PASS'),
    ]
    for name, status, items, expected in scenarios:
        got = summarize(execution(status, origin='agent' if status == 'FAILED' else None),
                        [verdict(e, v, r) for e, v, r in items])
        check(section, f'aggregation: {name} -> {expected}', got.verdict == expected,
              {'got': got.verdict, 'gate': got.gate, 'reason': got.reason,
               'note': 'Aggregation only. The forbid evaluator here is a stub; no such evaluator is registered in the runner.'})


def rf04():
    section = '3-rf04-must-forbid'
    gold = load_golden()
    case = next(c for c in gold['cases'] if c['case_id'] == 'RF-04')
    source = (ROOT / 'backend/app').rglob('*.py')
    readers = sorted(str(p.relative_to(ROOT)) for p in source if 'must_forbid' in p.read_text(encoding='utf-8'))
    check(section, 'production code reads the must_forbid field', bool(readers),
          {'files_reading_must_forbid': readers, 'must_forbid': case['must_forbid'],
           'note': 'An empty list means the field is never read; the RF-04 rule is hard-coded in GoldenOracleEvaluator.'})
    registered = [(e.evaluator_id, r) for e, r in default_evaluators()]
    check(section, 'a separate required must_forbid evaluator is registered',
          any('forbid' in eid for eid, required in registered if required), {'registered': registered})
    check(section, 'golden data columns (a plan step on a real salary field is impossible without a salary column)',
          None, {'columns': gold['columns'], 'has_salary_column': any('薪资' in c for c in gold['columns'])})

    oracle = GoldenOracleEvaluator()
    good = [[{'城市': '上海', '岗位数量': 3}, {'城市': '深圳', '岗位数量': 1}]]
    real_fields = [{'field_id': 'f1', 'display_name': '城市'}, {'field_id': 'f4', 'display_name': '岗位类型'}]
    probes = {
        'clean plan, correct result': ({'tasks': [{'steps': [{'params': {'field': 'f4'}}]}]}, real_fields, good, 'PASS'),
        'salary result column, correct counts': ({}, real_fields, [good[0] + [{'城市': '平均', '平均薪资': 9000}]], 'FAIL'),
        'step on a profiled field named 薪资': ({'tasks': [{'steps': [{'params': {'metrics': [{'field': 'f9'}]}}]}]},
                                              real_fields + [{'field_id': 'f9', 'display_name': '薪资'}], good, 'FAIL'),
        'no plan and no profile captured': ({}, [], good, 'NOT_EVALUATED (forbid cannot be checked)'),
        'step on an invented field id 薪资 not in profile': ({'tasks': [{'steps': [{'params': {'field': '薪资'}}]}]}, real_fields, good, 'FAIL'),
    }
    rows = {}
    for name, (plan, fields, tables, wanted) in probes.items():
        evidence = EvaluationEvidence(case=case, execution=execution('COMPLETED'),
                                      artifacts={'result_tables': tables, 'engine_execution_status': 'success', 'plan': plan,
                                                 'profile': {'fields': fields}})
        result = run_evaluator(oracle, evidence, required=True, now=CLOCK)
        e2e = summarize(execution('COMPLETED'), [result]).verdict
        rows[name] = {'oracle': result.verdict, 'failure_code': result.failure_code, 'e2e': e2e, 'expected_by_must_forbid': wanted}
        check(section, f'probe: {name}', result.verdict == wanted.split(' ')[0], rows[name])

    # Through the runner: an RF-04 completion with the right counts and no captured plan.
    tmp = Path(tempfile.mkdtemp(prefix='phase1c-rf04-'))
    run_dir = tmp / 'gf_20261113-000000_c3aaaa'
    observed = observed_set()
    observed['RF-04'] = ({'workflow_id': 'wf_4', 'final_status': 'COMPLETED', 'execution_status': 'success', 'approved_by_runner': True,
                          'result_tables': good}, {'business_lifecycle': {'status': 'succeeded'}})
    start(run_dir, lambda item: observed[item['case_id']])
    record = json.loads((run_dir / 'RF-04' / 'result.json').read_text())
    check(section, 'runner: RF-04 with correct counts but no plan/profile evidence must not be E2E PASS',
          record['e2e']['verdict'] != 'PASS',
          {'e2e': record['e2e']['verdict'], 'evaluators': {r['evaluator_id']: r['verdict'] for r in record['evaluator_results']}})
    shutil.rmtree(tmp)


def history():
    section = '4-history'
    if not HISTORICAL.is_dir():
        check(section, 'historical golden run exists', False, {'path': str(HISTORICAL)})
        return
    files = sorted([*HISTORICAL.glob('summary.json'), *HISTORICAL.glob('RF-0*/result.json'), *HISTORICAL.glob('RF-0*/trace.json'),
                    GOLD_PATH, TC_RUN / 'run.json'])
    before = {str(p): sha(p) for p in files}
    view = read_run(HISTORICAL)
    tc_view = read_run(TC_RUN)
    after = {str(p): sha(p) for p in files}
    baseline_path = Path('/tmp/insightflow-history-before.sha256')
    baseline = {}
    if baseline_path.is_file():
        for line in baseline_path.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            path = Path(name) if name.startswith('/') else ROOT / name
            baseline[str(path)] = digest
    check(section, 'historical sha256 unchanged by reading and equal to the Phase 1-B baseline',
          before == after and all(baseline.get(k) == v for k, v in after.items()) and len(baseline) == len(after),
          {'files': after, 'phase1b_baseline_entries': len(baseline)})
    expected = {'RF-01': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-03': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'),
                'RF-04': ('FAILED', 'NOT_EVALUATED', 'FAIL'), 'RF-02': ('COMPLETED', 'PASS', 'PASS'), 'RF-05': ('COMPLETED', 'PASS', 'PASS')}
    rows = {}
    for e, r, s in zip(view.executions, view.evaluator_results, view.e2e):
        rows[e.case_id] = {'execution': e.execution_status, 'blocking_stage': e.blocking_stage, 'error_code': e.error_code,
                           'oracle': r.verdict, 'oracle_failure_code': r.failure_code, 'e2e': s.verdict,
                           'legacy_failure': (e.legacy.get('verdict') or {}).get('failure'), 'legacy_reason': (e.legacy.get('verdict') or {}).get('reason'),
                           'provenance': e.provenance}
        check(section, f'{e.case_id} projection', (e.execution_status, r.verdict, s.verdict) == expected[e.case_id], rows[e.case_id])
    kept = all(rows[c]['legacy_failure'] == 'F-GOAL-SUBSTITUTED' and rows[c]['oracle_failure_code'] is None for c in ('RF-01', 'RF-03', 'RF-04'))
    check(section, 'original failure labels kept only in legacy', kept, {c: rows[c]['legacy_failure'] for c in rows})
    metrics = compute(view.executions, view.e2e, view.evaluator_results, oracle_evaluator_id=GOLDEN_LEGACY_EVALUATOR)
    check(section, 'metrics computed from the historical read', metrics['counts']['started'] == 5, metrics)
    tc = {s.case_id: s.verdict for s in tc_view.e2e}
    check(section, 'TC run read through the same interface', tc_view.run.run_kind == 'tc_regression' and tc == {'TC02': 'PASS'},
          {'e2e': tc, 'not_started': tc_view.run.not_started_case_ids, 'status': tc_view.run.status})


def main():
    if OUTPUTS.exists():
        raise SystemExit(f'{OUTPUTS} already exists; evidence is write-once. Use a new directory for a rerun.')
    tmp = Path(tempfile.mkdtemp(prefix='phase1c-'))
    runs = integration(tmp)
    gates()
    rf04()
    history()
    OUTPUTS.mkdir()
    for label, path in runs.items():
        shutil.copytree(path, OUTPUTS / 'runs' / f'{label}__{path.name}')
    shutil.rmtree(tmp)
    (OUTPUTS / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2, default=str))
    counts = {k: sum(c['result'] == k for c in checks) for k in ('PASS', 'FAIL', 'INFO')}
    for c in checks:
        print(f"{c['result']:4} {c['section']:20} {c['check']}")
    print(f"PASS {counts['PASS']}, FAIL {counts['FAIL']}, INFO {counts['INFO']}; evidence in {OUTPUTS}")


if __name__ == '__main__':
    main()
