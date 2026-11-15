"""Phase 1-D acceptance (REQ-0143): the Phase 1-C flow re-run against the must_forbid evaluator
and manifest integrity checks, with expectations updated to the corrected behaviour.

The Phase 1-C script and its evidence in ../evaluation-contracts-phase1c-2026-11-13 are not touched.
Scripted agent only; no model calls. Runs are built in a temporary directory and copied into
./outputs afterwards. Historical runs are only read.

Usage (from insightflow/):
    .venv/bin/python docs/evaluations/evaluation-quality-gates-phase1d-2026-11-13/verify_phase1d.py
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
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator  # noqa: E402
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden  # noqa: E402
from app.evaluation.golden_run import ORACLE_ID, default_evaluators, run_golden  # noqa: E402
from app.evaluation.manifest import CONFIG_FILE, MANIFEST_FILE  # noqa: E402
from app.evaluation.metrics import compute  # noqa: E402
from app.evaluation.must_forbid import MustForbidEvaluator  # noqa: E402
from app.evaluation.protocol import EvaluationEvidence, run_evaluator  # noqa: E402
from app.evaluation.runs import GOLDEN_LEGACY_EVALUATOR, read_run, trusted_metrics  # noqa: E402

HISTORICAL = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs/gf_20261112-143406_cde1fd'
TC_RUN = ROOT.parent / 'var/regression/runs/rg_20261112-133157_f04289'
OUTPUTS = Path(os.environ.get('PHASE1D_OUTPUTS') or HERE / 'outputs')
FORBID_ID = MustForbidEvaluator.evaluator_id
TICK = iter(range(100_000))
CLOCK = lambda: f'2026-11-13T00:00:{next(TICK) % 60:02d}+00:00'
FIELDS = [{'field_id': 'f1', 'display_name': '编号'}, {'field_id': 'f2', 'display_name': '城市'},
          {'field_id': 'f3', 'display_name': '岗位名称'}, {'field_id': 'f4', 'display_name': '岗位类型'}]
checks = []


def check(section, name, ok, evidence=None):
    result = 'INFO' if ok is None else 'PASS' if ok else 'FAIL'
    checks.append({'section': section, 'check': name, 'result': result, 'evidence': evidence})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan(*extra):
    return {'tasks': [{'task_id': 't1', 'title': '不要分析薪资', 'business_question': '统计岗位数量，不分析薪资',
                       'steps': [{'step_id': 's1', 'operation': 'filter',
                                  'params': {'conditions': [{'field': 'f4', 'operator': 'ne', 'value': '实习'}]}},
                                 {'step_id': 's2', 'operation': 'group_aggregate',
                                  'params': {'dimensions': ['f2'], 'metrics': [{'function': 'count', 'field': None, 'alias': '岗位数量'}]}}]},
                      *extra]}


ENGINE = [{'task_id': 't1', 'step_id': 's1', 'operation': 'filter', 'status': 'success'},
          {'task_id': 't1', 'step_id': 's2', 'operation': 'group_aggregate', 'status': 'success'}]
FULL = {'plan': plan(), 'profile': {'fields': FIELDS}, 'execution_steps': ENGINE}


def rows(pairs):
    return [[{'城市': c, '岗位数量': n} for c, n in pairs]]


def observed_set(rf04=None):
    shared = {'nodes': [{'name': 'data_profiler', 'status': 'success'}, {'name': 'intent_parser', 'status': 'success'}]}
    waiting = {**shared, 'final_status': 'AWAITING_APPROVAL', 'can_approve': False, 'approved_by_runner': False,
               'fidelity': {'status': 'not_in_gold'}, 'plan': plan(), 'profile': {'fields': FIELDS}}
    done = lambda wf, pairs, fidelity, prompts: ({**shared, **FULL, 'workflow_id': wf, 'final_status': 'COMPLETED',
                                                  'execution_status': 'success', 'approved_by_runner': True,
                                                  'result_tables': rows(pairs), 'fidelity': fidelity, 'prompt_templates': prompts},
                                                 {'business_lifecycle': {'status': 'succeeded'}})
    observed = {
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
    if rf04 is not None:
        observed['RF-04'] = ({**shared, 'workflow_id': 'wf_4', 'final_status': 'COMPLETED', 'execution_status': 'success',
                              'approved_by_runner': True, 'result_tables': rows([('上海', 3), ('深圳', 1)]), **rf04},
                             {'business_lifecycle': {'status': 'succeeded'}})
    return observed


class Spy:
    def __init__(self, inner, calls):
        self.inner, self.calls = inner, calls
        self.evaluator_id, self.evaluator_version, self.scope = inner.evaluator_id, inner.evaluator_version, inner.scope

    def config(self):
        return self.inner.config()

    def applicable(self, evidence):
        return self.inner.applicable(evidence)

    def evaluate(self, evidence):
        self.calls.append((self.evaluator_id, evidence.case['case_id']))
        return self.inner.evaluate(evidence)


def scripted(run_dir, observed=None, fail_at=None, order=None):
    observed = observed or observed_set()

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
                      model={'name': 'scripted'}, environment={'source_fingerprint': 'phase1d'},
                      evaluators=evaluators, clock=CLOCK, on_case=on_case)


def case_rows(run_dir):
    out = {}
    for case_id in ('RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05'):
        path = run_dir / case_id / 'result.json'
        if path.is_file():
            record = json.loads(path.read_text())
            out[case_id] = {'execution': record['execution']['execution_status'],
                            'evaluators': {r['evaluator_id']: [r['verdict'], r['required'], r['reason']] for r in record['evaluator_results']},
                            'e2e': [record['e2e']['verdict'], record['e2e']['reason']]}
    return out


def integration(tmp):
    section = '1-integration'
    tripwire, calls, order = [], [], []
    original = golden_fidelity.score_case
    golden_fidelity.score_case = lambda *a, **k: tripwire.append(a) or (_ for _ in ()).throw(AssertionError('legacy score_case used'))
    normal = tmp / 'gf_20261113-000000_d1aaaa'
    try:
        summary = start(normal, scripted(normal, order=order),
                        evaluators=[(Spy(e, calls), policy) for e, policy in default_evaluators()])
    finally:
        golden_fidelity.score_case = original
    called = {(eid, case) for eid, case in calls}
    check(section, '1. runner calls oracle and must_forbid evaluators, never legacy score_case',
          not tripwire and all((ORACLE_ID, c) in called and (FORBID_ID, c) in called for c in ('RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05')),
          {'evaluate_calls': calls, 'legacy_score_case_calls': len(tripwire)})
    per_case = case_rows(normal)
    locators = {json.loads((normal / c / 'result.json').read_text())['execution']['locator'] for c in per_case}
    check(section, '2. each case has its own execution and three evaluator results', len(locators) == 5 and all(len(v['evaluators']) == 3 for v in per_case.values()), per_case)
    check(section, 'normal run: RF-02 and RF-05 stay NOT_EVALUATED because their must_forbid items are not adapted', None,
          {c: per_case[c]['e2e'] for c in per_case})
    check(section, '3. run-config.json exists before each case, manifest does not', all(o['config_exists'] and not o['manifest_exists'] for o in order), order)
    manifest = json.loads((normal / MANIFEST_FILE).read_text())
    check(section, '4. run-manifest.json written after completion', manifest['status'] == 'FINISHED' and len(manifest['cases']) == 5,
          {'status': manifest['status'], 'cases': len(manifest['cases'])})
    view = read_run(normal)
    integrity = view.run.integrity
    check(section, '5. read_run verifies every manifest hash (VERIFIED)',
          integrity.status == 'VERIFIED' and len(integrity.files) == 12 and all(f.status == 'ok' for f in integrity.files),
          integrity.model_dump())
    stored = [json.loads((normal / c / 'result.json').read_text()) for c in per_case]
    round_trip = ([e.model_dump(mode='json') for e in view.executions] == [s['execution'] for s in stored]
                  and [r.model_dump(mode='json') for r in view.evaluator_results] == [r for s in stored for r in s['evaluator_results']])
    check(section, '6. read_run reads the new run completely', view.run.status == 'FINISHED' and round_trip,
          {'evaluator_manifest': [e.model_dump() for e in view.run.evaluator_manifest]})
    recomputed = compute(view.executions, view.e2e, view.evaluator_results, oracle_evaluator_id=ORACLE_ID)
    trusted = trusted_metrics(view, oracle_evaluator_id=ORACLE_ID)
    check(section, '7. metrics from read_run equal the runner summary; trusted metrics exclude nothing',
          recomputed == summary['metrics'] and trusted['metrics'] == recomputed and trusted['excluded'] == [], trusted)

    cut = tmp / 'gf_20261113-000000_d1cccc'
    try:
        start(cut, scripted(cut, fail_at='RF-03'))
    except RuntimeError:
        pass
    cut_view = read_run(cut)
    check(section, '8a. interruption during a case: run INCOMPLETE, integrity INCOMPLETE',
          (cut_view.run.status, cut_view.run.integrity.status) == ('INCOMPLETE', 'INCOMPLETE') and cut_view.run.missing_case_ids == ['RF-03', 'RF-04', 'RF-05'],
          {'status': cut_view.run.status, 'integrity': cut_view.run.integrity.model_dump(), 'missing': cut_view.run.missing_case_ids})
    late = tmp / 'gf_20261113-000000_d1dddd'

    def stop(execution, results, e2e):
        if execution.case_id == 'RF-05':
            raise KeyboardInterrupt
    try:
        start(late, scripted(late), on_case=stop)
    except KeyboardInterrupt:
        pass
    late_view = read_run(late)
    check(section, '8b. all cases written, no manifest: INCOMPLETE, never FINISHED or VERIFIED',
          (late_view.run.status, late_view.run.integrity.status) == ('INCOMPLETE', 'INCOMPLETE'),
          {'status': late_view.run.status, 'integrity': late_view.run.integrity.status})
    return normal, {'normal': normal, 'interrupted_mid_case': cut, 'interrupted_before_manifest': late}


def tamper(tmp, normal):
    section = '5-integrity'
    results = {}

    def variant(name, change):
        target = tmp / f'gf_20261113-000000_t{len(results):05d}'
        shutil.copytree(normal, target)
        change(target)
        view = read_run(target)
        results[name] = {'integrity': view.run.integrity.status, 'reasons': view.run.integrity.reasons,
                         'case_status': view.run.integrity.case_status,
                         'trusted_excluded': trusted_metrics(view, oracle_evaluator_id=ORACLE_ID)['excluded']}
        return view

    def edit(path, change):
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record, ensure_ascii=False))

    v = variant('result edited', lambda d: edit(d / 'RF-02/result.json', lambda r: r['e2e'].update(verdict='FAIL')))
    check(section, 'edited result.json is INVALID, case excluded from trusted metrics, verdict not rewritten',
          v.run.integrity.status == 'INVALID' and results['result edited']['trusted_excluded'] == [{'case_id': 'RF-02', 'reason': 'evidence_integrity_invalid'}]
          and next(s.verdict for s in v.e2e if s.case_id == 'RF-02') == 'FAIL', results['result edited'])
    v = variant('trace edited', lambda d: (d / 'RF-01/trace.json').write_text('{}'))
    check(section, 'edited trace.json is INVALID', v.run.integrity.status == 'INVALID' and v.run.integrity.case_status['RF-01'] == 'INVALID', results['trace edited'])
    v = variant('summary edited', lambda d: edit(d / 'summary.json', lambda s: s.update(model='other')))
    check(section, 'edited summary.json is INVALID; case files stay VERIFIED', v.run.integrity.status == 'INVALID'
          and set(v.run.integrity.case_status.values()) == {'VERIFIED'}, results['summary edited'])
    v = variant('config edited', lambda d: edit(d / CONFIG_FILE, lambda c: c.update(model={'name': 'other'})))
    check(section, 'edited run-config.json is INVALID and every case untrusted', v.run.integrity.status == 'INVALID'
          and set(v.run.integrity.case_status.values()) == {'INVALID'}, results['config edited'])
    v = variant('trace deleted', lambda d: (d / 'RF-03/trace.json').unlink())
    check(section, 'missing file named in the manifest is INVALID', v.run.integrity.status == 'INVALID'
          and 'missing:RF-03/trace.json' in v.run.integrity.reasons, results['trace deleted'])

    def escape(d):
        outside = d.parent / 'outside.json'
        shutil.copy(d / 'RF-02/result.json', outside)
        edit(d / MANIFEST_FILE, lambda m: m['cases'][1].update(result_ref='../outside.json', result_sha256=sha(outside)))
    v = variant('manifest points outside the run', escape)
    check(section, 'manifest path outside the run directory is INVALID', v.run.integrity.status == 'INVALID'
          and 'outside_run:../outside.json' in v.run.integrity.reasons, results['manifest points outside the run'])
    return results


def gates_and_rf04(tmp):
    section = '2-gates'
    case = next(c for c in load_golden()['cases'] if c['case_id'] == 'RF-04')

    def execution(status):
        from app.evaluation.contracts import CaseExecution
        return CaseExecution(execution_id=None, locator='run/RF-04', run_id='run', case_id='RF-04', attempt=1, execution_status=status,
                             failure_origin='agent' if status == 'FAILED' else None, workflow_id=None, started_at=None, finished_at=None,
                             record_ref=None, output_ref=None, trace_ref=None, error_code=None, blocking_stage=None, provenance='recorded')

    def judge(status='COMPLETED', forbid=None, **artifacts):
        base = {**FULL, 'result_tables': rows([('上海', 3), ('深圳', 1)]), 'engine_execution_status': 'success' if status == 'COMPLETED' else None,
                'dataset_id': 'requirement-fidelity-golden-v1', **artifacts}
        ev = EvaluationEvidence(case=case, execution=execution(status), artifacts=base, refs={'case': 'golden-set.json#cases[RF-04]'})
        oracle = run_evaluator(GoldenOracleEvaluator(), ev, required='required', now=CLOCK)
        result = run_evaluator(forbid or MustForbidEvaluator(), ev, required='required_when_applicable', now=CLOCK)
        node = run_evaluator(RequirementFidelityNodeEvaluator(), ev, required='optional', now=CLOCK)
        return oracle, result, summarize(ev.execution, [oracle, result, node])

    class Broken(MustForbidEvaluator):
        def evaluate(self, evidence):
            raise RuntimeError('bug')

    salary_plan = plan({'task_id': 't2', 'title': 'x', 'business_question': 'x',
                        'steps': [{'step_id': 's9', 'operation': 'aggregate', 'params': {'metrics': [{'function': 'avg', 'field': '薪资', 'alias': 'm'}]}}]})
    scenarios = {
        'oracle PASS + forbid PASS -> PASS': (judge(), 'PASS'),
        'oracle PASS + forbid FAIL -> FAIL': (judge(plan=salary_plan), 'FAIL'),
        'oracle PASS + forbid NOT_EVALUATED -> NOT_EVALUATED': (judge(execution_steps=None), 'NOT_EVALUATED'),
        'oracle PASS + forbid EVALUATOR_ERROR -> EVALUATOR_ERROR': (judge(forbid=Broken()), 'EVALUATOR_ERROR'),
        'agent FAILED + oracle NOT_EVALUATED -> FAIL': (judge('FAILED', plan={}, execution_steps=None, result_tables=[]), 'FAIL'),
        'optional node EVALUATOR_ERROR does not change PASS': (judge(fidelity={'status': 'collector_error', 'error': 'X'}), 'PASS'),
    }
    for name, ((oracle, forbid, summary), expected) in scenarios.items():
        check(section, name, summary.verdict == expected,
              {'oracle': oracle.verdict, 'must_forbid': [forbid.verdict, forbid.failure_code, forbid.reason], 'e2e': [summary.verdict, summary.reason],
               'optional': summary.optional_verdicts})

    section = '3-rf04'
    readers = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'backend/app').rglob('*.py') if "'must_forbid'" in p.read_text(encoding='utf-8'))
    check(section, 'production code reads must_forbid', readers == ['backend/app/evaluation/must_forbid.py'], readers)
    registered = [(e.evaluator_id, policy) for e, policy in default_evaluators()]
    check(section, 'must_forbid registered as required_when_applicable; oracle required; node optional',
          registered == [(ORACLE_ID, 'required'), (FORBID_ID, 'required_when_applicable'), ('insightflow.node.requirement_fidelity', 'optional')], registered)
    oracle_source = (ROOT / 'backend/app/evaluation/evaluators.py').read_text()
    check(section, 'oracle no longer contains an RF-04 branch or salary check', "'RF-04'" not in oracle_source and 'salary' not in oracle_source, None)
    probes = {
        'no plan and no profile captured': (dict(plan={}, profile={}), 'NOT_EVALUATED'),
        'step on invented field 薪资 not in profile': (dict(plan=salary_plan), 'FAIL'),
        'salary result column 平均薪资': (dict(result_tables=[rows([('上海', 3), ('深圳', 1)])[0] + [{'城市': '合计', '平均薪资': 1}]]), 'FAIL'),
        'profiled field displayed as 薪资': (dict(plan=plan({'task_id': 't2', 'title': 'x', 'business_question': 'x',
                                                           'steps': [{'step_id': 's9', 'operation': 'sort', 'params': {'field': 'f9', 'direction': 'desc'}}]}),
                                              profile={'fields': FIELDS + [{'field_id': 'f9', 'display_name': '薪资'}]}), 'FAIL'),
        'clean evidence, 薪资 only in plan text': (dict(), 'PASS'),
    }
    for name, (override, expected) in probes.items():
        oracle, forbid, summary = judge(**override)
        check(section, f'probe: {name} -> must_forbid {expected}', forbid.verdict == expected,
              {'must_forbid': [forbid.verdict, forbid.failure_code, forbid.reason], 'e2e': summary.verdict})

    runner = {}
    for label, rf04 in (('counts only, no evidence', {}), ('full clean evidence', dict(FULL)),
                        ('salary column', dict(FULL, result_tables=[rows([('上海', 3), ('深圳', 1)])[0] + [{'城市': '合计', '平均薪资': 1}]]))):
        run_dir = tmp / f'gf_20261113-000000_r{len(runner):05d}'
        start(run_dir, scripted(run_dir, observed_set(rf04)))
        runner[label] = case_rows(run_dir)['RF-04']
    check(section, 'runner: RF-04 correct counts without forbid evidence is not E2E PASS', runner['counts only, no evidence']['e2e'][0] == 'NOT_EVALUATED', runner['counts only, no evidence'])
    check(section, 'runner: RF-04 correct counts with complete clean evidence is E2E PASS', runner['full clean evidence']['e2e'][0] == 'PASS', runner['full clean evidence'])
    check(section, 'runner: RF-04 forbidden field use is E2E FAIL', runner['salary column']['e2e'][0] == 'FAIL', runner['salary column'])


def history():
    section = '4-history'
    files = sorted([*HISTORICAL.glob('summary.json'), *HISTORICAL.glob('RF-0*/result.json'), *HISTORICAL.glob('RF-0*/trace.json'),
                    GOLD_PATH, TC_RUN / 'run.json'])
    before = {str(p): sha(p) for p in files}
    view, tc_view = read_run(HISTORICAL), read_run(TC_RUN)
    after = {str(p): sha(p) for p in files}
    baseline = {}
    for line in Path('/tmp/insightflow-history-before.sha256').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        baseline[str(Path(name) if name.startswith('/') else ROOT / name)] = digest
    check(section, 'historical sha256 unchanged and equal to the Phase 1-B baseline',
          before == after and baseline == after, {'files': after})
    expected = {'RF-01': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-03': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'),
                'RF-04': ('FAILED', 'NOT_EVALUATED', 'FAIL'), 'RF-02': ('COMPLETED', 'PASS', 'PASS'), 'RF-05': ('COMPLETED', 'PASS', 'PASS')}
    got = {e.case_id: (e.execution_status, r.verdict, s.verdict) for e, r, s in zip(view.executions, view.evaluator_results, view.e2e)}
    legacy = {e.case_id: (e.legacy.get('verdict') or {}).get('failure') for e in view.executions}
    check(section, 'historical golden projection unchanged; legacy labels kept', got == expected
          and all(legacy[c] == 'F-GOAL-SUBSTITUTED' for c in ('RF-01', 'RF-03', 'RF-04')), {'projection': got, 'legacy_failure': legacy})
    check(section, 'historical golden and TC runs are UNVERIFIED, not VERIFIED',
          view.run.integrity.status == 'UNVERIFIED' and tc_view.run.integrity.status == 'UNVERIFIED',
          {'golden': view.run.integrity.model_dump(), 'tc': tc_view.run.integrity.model_dump()})
    check(section, 'TC read through the same interface', {s.case_id: s.verdict for s in tc_view.e2e} == {'TC02': 'PASS'},
          {'not_started': len(tc_view.run.not_started_case_ids)})
    metrics = compute(view.executions, view.e2e, view.evaluator_results, oracle_evaluator_id=GOLDEN_LEGACY_EVALUATOR)
    check(section, 'historical metrics still computable', metrics['counts']['started'] == 5 and metrics['e2e_confirmed_success_rate'] == 0.4, metrics)


def main():
    if OUTPUTS.exists():
        raise SystemExit(f'{OUTPUTS} already exists; evidence is write-once. Use a new directory for a rerun.')
    tmp = Path(tempfile.mkdtemp(prefix='phase1d-'))
    normal, runs = integration(tmp)
    tamper_results = tamper(tmp, normal)
    gates_and_rf04(tmp)
    history()
    OUTPUTS.mkdir(parents=True)
    for label, path in runs.items():
        shutil.copytree(path, OUTPUTS / 'runs' / f'{label}__{path.name}')
    (OUTPUTS / 'tamper-results.json').write_text(json.dumps(tamper_results, ensure_ascii=False, indent=2))
    shutil.rmtree(tmp)
    (OUTPUTS / 'checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2, default=str))
    counts = {k: sum(c['result'] == k for c in checks) for k in ('PASS', 'FAIL', 'INFO')}
    for c in checks:
        print(f"{c['result']:4} {c['section']:14} {c['check']}")
    print(f"PASS {counts['PASS']}, FAIL {counts['FAIL']}, INFO {counts['INFO']}; evidence in {OUTPUTS}")


if __name__ == '__main__':
    main()
