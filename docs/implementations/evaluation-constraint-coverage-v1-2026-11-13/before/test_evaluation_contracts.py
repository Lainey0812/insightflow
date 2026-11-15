"""Unified evaluation contracts. No model calls; historical runs are only read."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.evaluation.aggregate import summarize
from app.evaluation.contracts import CaseExecution, EvaluatorResult
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden
from app.evaluation.golden_run import run_golden
from app.evaluation.manifest import CONFIG_FILE, MANIFEST_FILE, write_once
from app.evaluation.metrics import compute
from app.evaluation.protocol import EvaluationEvidence, Outcome, config_hash, run_evaluator
from app.evaluation.runs import GOLDEN_LEGACY_EVALUATOR, read_run

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs/gf_20261112-143406_cde1fd'
NOW = lambda: '2026-11-13T00:00:00+00:00'


def history_hashes():
    files = sorted(p for p in HISTORICAL.rglob('*.json') if 'data' not in p.relative_to(HISTORICAL).parts)
    return {str(p.relative_to(HISTORICAL)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def execution(status, *, origin=None, expect_blocked=False, locator='run/C1'):
    return CaseExecution(execution_id=None, locator=locator, run_id='run', case_id='C1', attempt=1, execution_status=status,
                         failure_origin=origin, workflow_id=None, started_at=None, finished_at=None, record_ref=None,
                         output_ref=None, trace_ref=None, error_code=None, blocking_stage=None, expect_blocked=expect_blocked,
                         provenance='recorded')


def result(verdict, *, required=True, evaluator_id='oracle', code=None, locator='run/C1'):
    return EvaluatorResult(evaluator_id=evaluator_id, evaluator_version='v1', evaluator_config_hash=None, case_execution_ref=locator,
                           evaluation_scope='e2e', required=required, verdict=verdict, failure_code=code, evaluated_at=None,
                           provenance='recorded')


def test_legacy_golden_projection_keeps_raw_labels_and_files_unchanged():
    before = history_hashes()
    view = read_run(HISTORICAL)
    after = history_hashes()
    assert before == after and len(before) == 11
    assert view.run.provenance == 'legacy_projection' and view.run.status == 'FINISHED'
    assert view.run.agent_version is None and view.run.evaluator_manifest is None
    assert view.run.dataset_id == 'requirement-fidelity-golden-v1'
    by_case = {e.case_id: (e, r, s) for e, r, s in zip(view.executions, view.evaluator_results, view.e2e)}
    for case_id in ('RF-01', 'RF-03'):
        e, r, s = by_case[case_id]
        assert (e.execution_status, e.blocking_stage, r.verdict, s.verdict) == ('BLOCKED', 'hitl_approval', 'NOT_EVALUATED', 'FAIL')
        assert f'{case_id}/trace.json#business_lifecycle.status' in e.projection['execution_status'].sources
        assert e.legacy['verdict']['failure'] == 'F-GOAL-SUBSTITUTED' and r.failure_code is None
    e, r, s = by_case['RF-04']
    assert (e.execution_status, e.blocking_stage, e.error_code) == ('FAILED', 'analysis_planner', 'PLANNER_BUSINESS_INVALID')
    assert (r.verdict, s.verdict, e.legacy['verdict']['failure']) == ('NOT_EVALUATED', 'FAIL', 'F-GOAL-SUBSTITUTED')
    for case_id in ('RF-02', 'RF-05'):
        e, r, s = by_case[case_id]
        assert (e.execution_status, r.verdict, s.verdict) == ('COMPLETED', 'PASS', 'PASS')
    assert all(r.evaluator_version is None and r.provenance == 'legacy_projection' for r in view.evaluator_results)


def test_missing_trace_does_not_fabricate_blocked(tmp_path):
    run_dir = tmp_path / 'gf_20990101-000000_aaaaaa'
    (run_dir / 'RF-01').mkdir(parents=True)
    summary = json.loads((HISTORICAL / 'summary.json').read_text())
    summary['cases'] = [c for c in summary['cases'] if c['case_id'] == 'RF-01']
    (run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False))
    shutil.copy(HISTORICAL / 'RF-01/result.json', run_dir / 'RF-01/result.json')
    (run_dir / 'RF-01/trace.json').write_text('{"trace_error": "no_workflow"}')
    view = read_run(run_dir)
    e, s = view.executions[0], view.e2e[0]
    assert e.execution_status is None and e.trace_ref is None and 'trace_ref' in e.unverified
    assert (s.verdict, s.reason) == ('NOT_EVALUATED', 'execution_status_unknown')


def test_hard_gates():
    assert summarize(execution('COMPLETED'), [result('PASS')]).verdict == 'PASS'
    assert summarize(execution('COMPLETED'), [result('NOT_EVALUATED')]).verdict == 'NOT_EVALUATED'
    assert summarize(execution('COMPLETED'), []).verdict == 'NOT_EVALUATED'
    assert summarize(execution('COMPLETED'), [result('FAIL', code='F-ORACLE-MISS')]).verdict == 'FAIL'
    assert summarize(execution('COMPLETED'), [result('EVALUATOR_ERROR')]).verdict == 'EVALUATOR_ERROR'
    blocked = summarize(execution('BLOCKED'), [result('NOT_EVALUATED')])
    assert (blocked.verdict, blocked.gate, blocked.required_verdicts) == ('FAIL', 'task_condition', {'oracle': 'NOT_EVALUATED'})
    assert summarize(execution('BLOCKED', expect_blocked=True), [result('PASS')]).verdict == 'PASS'
    assert summarize(execution('COMPLETED', expect_blocked=True), [result('PASS')]).verdict == 'FAIL'
    assert summarize(execution('WAITING_APPROVAL'), [result('PASS')]).verdict == 'NOT_EVALUATED'
    assert summarize(execution('FAILED', origin='infrastructure'), [result('NOT_EVALUATED')]).verdict == 'INFRA_ERROR'
    optional = summarize(execution('COMPLETED'), [result('PASS'), result('EVALUATOR_ERROR', required=False, evaluator_id='node')])
    assert (optional.verdict, optional.optional_verdicts) == ('PASS', {'node': 'EVALUATOR_ERROR'})


class Boom:
    evaluator_id, evaluator_version, scope = 'boom', 'v1', 'e2e'

    def config(self):
        return {}

    def applicable(self, evidence):
        return True, None

    def evaluate(self, evidence):
        raise RuntimeError('evaluator bug')


class LeakyCode(Boom):
    def evaluate(self, evidence):
        return Outcome('NOT_EVALUATED', 'F-GOAL-SUBSTITUTED', 'no data')


def test_evaluator_exception_is_evaluator_error_not_business_failure():
    evidence = EvaluationEvidence(case={'case_id': 'C1'}, execution=execution('COMPLETED'))
    broken = run_evaluator(Boom(), evidence, required=True, now=NOW)
    assert (broken.verdict, broken.failure_code, broken.reason) == ('EVALUATOR_ERROR', None, 'RuntimeError')
    assert run_evaluator(LeakyCode(), evidence, required=True, now=NOW).failure_code is None
    assert summarize(evidence.execution, [broken]).verdict == 'EVALUATOR_ERROR'
    optional = run_evaluator(Boom(), evidence, required=False, now=NOW)
    assert summarize(evidence.execution, [result('PASS'), optional]).verdict == 'PASS'


def test_golden_oracle_keeps_rules_but_does_not_label_missing_results():
    cases = {c['case_id']: c for c in load_golden()['cases']}
    oracle = GoldenOracleEvaluator()

    def judge(case_id, status, tables=(), engine=None, plan=None, profile=None):
        evidence = EvaluationEvidence(case=cases[case_id], execution=execution(status),
                                      artifacts={'result_tables': list(tables), 'engine_execution_status': engine,
                                                 'plan': plan or {}, 'profile': profile or {}})
        return run_evaluator(oracle, evidence, required=True, now=NOW)

    for status in ('BLOCKED', 'FAILED'):
        r = judge('RF-01', status)
        assert (r.verdict, r.failure_code, r.reason) == ('NOT_EVALUATED', None, 'no_engine_result')
    assert judge('RF-01', 'COMPLETED', [[{'城市': '上海', 'n': 3}, {'城市': '深圳', 'n': 1}]], 'success').verdict == 'PASS'
    dropped = judge('RF-01', 'COMPLETED', [[{'城市': '上海', 'n': 4}, {'城市': '深圳', 'n': 3}]], 'success')
    assert (dropped.verdict, dropped.failure_code) == ('FAIL', 'F-EXCLUDE-DROPPED')
    salary_plan = {'plan': {'tasks': [{'steps': [{'params': {'field': 'f9'}}]}]},
                   'profile': {'fields': [{'field_id': 'f9', 'display_name': '薪资'}]}}
    salary = judge('RF-04', 'FAILED', **salary_plan)
    assert (salary.verdict, salary.failure_code) == ('NOT_EVALUATED', None)
    counted = judge('RF-04', 'COMPLETED', [[{'城市': '上海', 'n': 3}, {'城市': '深圳', 'n': 1}]], 'success', **salary_plan)
    assert counted.verdict == 'PASS', 'salary use is judged by the must_forbid evaluator, not the oracle'
    assert config_hash(oracle) == config_hash(GoldenOracleEvaluator())


def fake_agent(fail_at=None):
    shared = {'nodes': [{'name': 'data_profiler', 'status': 'success'}, {'name': 'intent_parser', 'status': 'success'}],
              'fidelity': {'scorer_version': 'requirement-fidelity-v1', 'status': 'not_in_gold'}}
    waiting = {**shared, 'final_status': 'AWAITING_APPROVAL', 'can_approve': False, 'approved_by_runner': False}
    table = lambda pairs: [[{'城市': city, '岗位数量': n} for city, n in pairs]]
    observed = {
        'RF-01': ({**waiting, 'workflow_id': 'wf_1'}, {'business_lifecycle': {'status': 'waiting_approval'}}),
        'RF-02': ({**shared, 'workflow_id': 'wf_2', 'final_status': 'COMPLETED', 'execution_status': 'success', 'approved_by_runner': True,
                   'result_tables': table([('上海', 4), ('深圳', 3)]), 'prompt_templates': {'intent_parser': ['pt_a']}},
                  {'business_lifecycle': {'status': 'succeeded'}}),
        'RF-03': ({**waiting, 'workflow_id': 'wf_3'}, {'business_lifecycle': {'status': 'waiting_approval'}}),
        'RF-04': ({**shared, 'workflow_id': 'wf_4', 'final_status': 'FAILED', 'error_code': 'PLANNER_BUSINESS_INVALID',
                   'nodes': shared['nodes'] + [{'name': 'analysis_planner', 'status': 'error'}]}, {'business_lifecycle': {'status': 'failed'}}),
        'RF-05': ({**shared, 'workflow_id': 'wf_5', 'final_status': 'COMPLETED', 'execution_status': 'success', 'approved_by_runner': True,
                   'result_tables': table([('深圳', 3), ('北京', 1), ('杭州', 1)]), 'prompt_templates': {'intent_parser': ['pt_a'], 'analysis_planner': ['pt_b']}},
                  {'business_lifecycle': {'status': 'succeeded'}}),
    }

    def run_one(item):
        if item['case_id'] == fail_at:
            raise RuntimeError('runner interrupted')
        return observed[item['case_id']]
    return run_one


def start(run_dir, run_one):
    return run_golden(run_dir, load_golden(), GOLD_PATH.read_bytes(), 'golden-set.json', run_one=run_one,
                      model={'name': 'scripted'}, environment={'source_fingerprint': 'test'}, clock=NOW)


def test_new_run_writes_config_and_final_manifest(tmp_path):
    run_dir = tmp_path / 'gf_20990101-000000_bbbbbb'
    summary = start(run_dir, fake_agent())
    config = json.loads((run_dir / CONFIG_FILE).read_text())
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text())
    assert config['dataset']['sha256'] == hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest()
    assert config['agent'] == {'id': 'insightflow', 'version': None}
    assert [(e['evaluator_id'], e['requirement']) for e in config['evaluators']] == [
        ('insightflow.golden.oracle', 'required'), ('insightflow.golden.must_forbid', 'required_when_applicable'),
        ('insightflow.node.requirement_fidelity', 'optional')]
    assert manifest['config_sha256'] == hashlib.sha256((run_dir / CONFIG_FILE).read_bytes()).hexdigest()
    assert manifest['status'] == 'FINISHED' and len(manifest['cases']) == 5
    assert manifest['observed_prompt_snapshots'] == {'analysis_planner': ['pt_b'], 'intent_parser': ['pt_a']}
    for item in manifest['cases']:
        assert hashlib.sha256((run_dir / item['result_ref']).read_bytes()).hexdigest() == item['result_sha256']
    written = ''.join(p.read_text() for p in run_dir.rglob('*.json'))
    assert 'F-GOAL-SUBSTITUTED' not in written
    rows = {c['case_id']: (c['execution_status'], c['oracle'], c['e2e']) for c in summary['cases']}
    # RF-02 and RF-05 declare natural-language must_forbid items that have no verified adaptation,
    # so the required must_forbid check cannot pass and E2E stays NOT_EVALUATED.
    assert rows == {'RF-01': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-02': ('COMPLETED', 'PASS', 'NOT_EVALUATED'),
                    'RF-03': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-04': ('FAILED', 'NOT_EVALUATED', 'FAIL'),
                    'RF-05': ('COMPLETED', 'PASS', 'NOT_EVALUATED')}
    view = read_run(run_dir)
    assert view.run.provenance == 'recorded' and view.run.status == 'FINISHED'
    assert view.run.projection['config_integrity'].value == 'verified'
    assert all(e.attempt == 1 and e.execution_id for e in view.executions)
    assert {r.evaluator_id: r.verdict for r in view.evaluator_results if r.case_execution_ref.endswith('RF-02')} == {
        'insightflow.golden.oracle': 'PASS', 'insightflow.golden.must_forbid': 'NOT_EVALUATED',
        'insightflow.node.requirement_fidelity': 'NOT_EVALUATED'}
    with pytest.raises(FileExistsError):
        write_once(run_dir / CONFIG_FILE, {})


def test_interrupted_run_keeps_config_and_reads_as_incomplete(tmp_path):
    run_dir = tmp_path / 'gf_20990101-000000_cccccc'
    with pytest.raises(RuntimeError):
        start(run_dir, fake_agent(fail_at='RF-03'))
    assert (run_dir / CONFIG_FILE).is_file() and not (run_dir / MANIFEST_FILE).exists()
    view = read_run(run_dir)
    assert view.run.status == 'INCOMPLETE' and view.run.finished_at is None
    assert view.run.missing_case_ids == ['RF-03', 'RF-04', 'RF-05']
    assert [e.case_id for e in view.executions] == ['RF-01', 'RF-02']
    assert not list(run_dir.rglob('.*.tmp'))


def regression_case(case_id, status, **fields):
    return {'case_id': case_id, 'title': case_id, 'status': status, 'checks': fields.pop('checks', []), 'manual_review': [], **fields}


def test_tc_runs_read_through_the_same_interface(tmp_path):
    finished = tmp_path / 'rg_20990101-000000_dddddd'
    finished.mkdir()
    suite = {'version': 'typical-suite-v1', 'path': 'x', 'cases_sha256': 'abc'}
    cases = [regression_case('TC01', 'not_run', reason='未选入本次运行。'),
             regression_case('TC02', 'passed', execution_status='success', final_status='COMPLETED', business_status='succeeded',
                             workflow_id='wf_2', checks=[{'key': 'executed', 'status': 'pass'}]),
             regression_case('TC08', 'passed', final_status='AWAITING_APPROVAL', business_status='waiting_approval',
                             checks=[{'key': 'stopped', 'status': 'pass'}, {'key': 'not_executed', 'status': 'pass'}]),
             regression_case('TC03', 'blocked', runner_error='ConnectError'),
             regression_case('TC04', 'failed', execution_status='success', final_status='COMPLETED',
                             checks=[{'key': 'values_result', 'status': 'fail'}])]
    (finished / 'run.json').write_text(json.dumps({'schema_version': 'regression-run-v1', 'run_id': finished.name, 'suite': suite,
                                                   'selected_cases': ['TC02', 'TC03', 'TC04', 'TC08'], 'cases': cases,
                                                   'started_at': 'a', 'finished_at': 'b'}))
    view = read_run(finished)
    assert view.run.run_kind == 'tc_regression' and view.run.not_started_case_ids == ['TC01']
    assert (view.run.dataset_id, view.run.dataset_hash, view.run.dataset_version) == ('typical-suite-v1', 'abc', None)
    e2e = {s.case_id: s.verdict for s in view.e2e}
    assert e2e == {'TC02': 'PASS', 'TC08': 'PASS', 'TC03': 'INFRA_ERROR', 'TC04': 'FAIL'}
    tc04 = next(r for r in view.evaluator_results if r.case_execution_ref.endswith('TC04'))
    assert tc04.failure_code == 'check:values_result' and tc04.legacy['status'] == 'failed'

    partial = tmp_path / 'rg_20990101-000000_eeeeee'
    (partial / 'cases').mkdir(parents=True)
    (partial / 'run-start.json').write_text(json.dumps({'run_id': partial.name, 'suite': suite, 'selected_cases': ['TC02', 'TC03']}))
    (partial / 'cases/TC02.json').write_text(json.dumps(cases[1]))
    incomplete = read_run(partial)
    assert incomplete.run.status == 'INCOMPLETE' and incomplete.run.missing_case_ids == ['TC03']


def test_metrics_use_separate_denominators_and_null_for_zero():
    empty = compute([], [], [], not_started=3)
    assert empty['e2e_confirmed_success_rate'] is None and empty['execution_completion_rate'] is None
    assert empty['counts']['not_started'] == 3
    view = read_run(HISTORICAL)
    metrics = compute(view.executions, view.e2e, view.evaluator_results, not_started=2, oracle_evaluator_id=GOLDEN_LEGACY_EVALUATOR)
    assert metrics['counts']['started'] == 5 and metrics['counts']['not_started'] == 2
    assert metrics['e2e_confirmed_success_rate'] == 2 / 5 and metrics['decidable_pass_rate'] == 2 / 5
    assert metrics['evaluation_coverage'] == 1.0
    assert metrics['execution_completion_rate'] == 2 / 5 and metrics['block_rate'] == 2 / 5 and metrics['run_failure_rate'] == 1 / 5
    assert metrics['executed_result_correct_rate'] == 1.0
    assert metrics['evaluators'][GOLDEN_LEGACY_EVALUATOR]['error_rate'] == 0
    assert metrics['evaluators'][GOLDEN_LEGACY_EVALUATOR]['not_evaluated_rate'] == 3 / 5


def test_node_fidelity_adapter_is_optional_and_maps_collector_errors():
    node = RequirementFidelityNodeEvaluator()
    evidence = EvaluationEvidence(case={}, execution=execution('COMPLETED'),
                                  artifacts={'fidelity': {'status': 'collector_error', 'error': 'KeyError'}})
    assert run_evaluator(node, evidence, required=False, now=NOW).verdict == 'EVALUATOR_ERROR'
    lost = EvaluationEvidence(case={}, execution=execution('COMPLETED'),
                              artifacts={'fidelity': {'status': 'scored', 'lost': [{'lost_at': 'engine', 'detail': 'step_not_run'}]}})
    failed = run_evaluator(node, lost, required=False, now=NOW)
    assert (failed.verdict, failed.failure_code, failed.evaluation_scope) == ('FAIL', 'lost_at:engine', 'node')
    assert summarize(execution('COMPLETED'), [result('PASS'), failed]).verdict == 'PASS'
