"""Must-forbid evaluator and manifest integrity. Scripted evidence only; historical runs are only read."""
import hashlib
import json
import os
import shutil

import pytest

from app.evaluation.aggregate import summarize
from app.evaluation.contracts import CaseExecution
from app.evaluation.evaluators import GoldenOracleEvaluator
from app.evaluation.constraint_coverage import MAPPING_VERSION, mapping_sha256
from app.evaluation.golden_fidelity import load_golden
from app.evaluation.golden_run import ORACLE_ID
from app.evaluation.manifest import CONFIG_FILE, MANIFEST_FILE
from app.evaluation.must_forbid import MustForbidEvaluator
from app.evaluation.protocol import EvaluationEvidence, config_hash, run_evaluator
from app.evaluation.runs import read_run, trusted_metrics
from test_evaluation_contracts import HISTORICAL, NOW, fake_agent, history_hashes, start

CASES = {c['case_id']: c for c in load_golden()['cases']}
ROWS = load_golden()['rows']
FIELDS = [{'field_id': 'f1', 'display_name': '编号'}, {'field_id': 'f2', 'display_name': '城市'},
          {'field_id': 'f3', 'display_name': '岗位名称'}, {'field_id': 'f4', 'display_name': '岗位类型'}]
GOOD = [[{'城市': '上海', '岗位数量': 3}, {'城市': '深圳', '岗位数量': 1}]]


def clean_plan(*extra_tasks):
    return {'tasks': [{'task_id': 't1', 'title': '不要分析薪资，只统计岗位数量', 'business_question': '不分析薪资',
                       'steps': [{'step_id': 's1', 'operation': 'filter',
                                  'params': {'conditions': [{'field': 'f4', 'operator': 'ne', 'value': '实习'}]}},
                                 {'step_id': 's2', 'operation': 'group_aggregate',
                                  'params': {'dimensions': ['f2'], 'metrics': [{'function': 'count', 'field': None, 'alias': '岗位数量'}]}}]},
                      *extra_tasks]}


ENGINE = [{'task_id': 't1', 'step_id': 's1', 'operation': 'filter', 'status': 'success'},
          {'task_id': 't1', 'step_id': 's2', 'operation': 'group_aggregate', 'status': 'success'}]


def execution(status='COMPLETED', case_id='RF-04'):
    return CaseExecution(execution_id=None, locator=f'run/{case_id}', run_id='run', case_id=case_id, attempt=1, execution_status=status,
                         failure_origin=None, workflow_id=None, started_at=None, finished_at=None, record_ref=None, output_ref=None,
                         trace_ref=None, error_code=None, blocking_stage=None, provenance='recorded')


def evidence(case='RF-04', status='COMPLETED', **override):
    case = CASES[case] if isinstance(case, str) else case
    artifacts = {'plan': clean_plan(), 'profile': {'fields': FIELDS}, 'execution_steps': ENGINE, 'result_tables': GOOD,
                 'engine_execution_status': 'success' if status == 'COMPLETED' else None,
                 'dataset_id': 'requirement-fidelity-golden-v1', 'dataset_rows': ROWS, **override}
    return EvaluationEvidence(case=case, execution=execution(status, case['case_id']), artifacts=artifacts,
                              refs={'case': f"golden-set.json#cases[{case['case_id']}]", 'plan': 'p', 'engine': 'e', 'result_columns': 'r'})


def forbid(ev, evaluator=None):
    return run_evaluator(evaluator or MustForbidEvaluator(), ev, required='required_when_applicable', now=NOW)


def e2e(ev, evaluator=None):
    oracle = run_evaluator(GoldenOracleEvaluator(), ev, required='required', now=NOW)
    result = forbid(ev, evaluator)
    return oracle, result, summarize(ev.execution, [oracle, result])


def test_oracle_pass_and_forbid_pass_is_e2e_pass():
    oracle, result, summary = e2e(evidence())
    assert (oracle.verdict, result.verdict, summary.verdict) == ('PASS', 'PASS', 'PASS')
    assert result.reason == 'forbid_field:plan,engine,result_columns;row_set:1'
    assert 'golden-set.json#cases[RF-04].must_forbid[0]' in result.evidence_refs


def test_oracle_pass_and_forbid_fail_is_e2e_fail():
    plan = clean_plan({'task_id': 't2', 'title': 'x', 'business_question': 'x',
                       'steps': [{'step_id': 's9', 'operation': 'aggregate', 'params': {'metrics': [{'function': 'avg', 'field': 'f9', 'alias': 'm'}]}}]})
    oracle, result, summary = e2e(evidence(plan=plan, profile={'fields': FIELDS + [{'field_id': 'f9', 'display_name': '薪资'}]}))
    assert (oracle.verdict, result.verdict, result.failure_code) == ('PASS', 'FAIL', 'F-METRIC-SUBSTITUTED')
    assert result.reason == 'forbid-salary-field@plan:t2/s9.metrics[0].field=f9(薪资)'
    assert (summary.verdict, summary.gate) == ('FAIL', 'required_evaluator')


def test_oracle_pass_and_forbid_not_evaluated_is_e2e_not_evaluated():
    oracle, result, summary = e2e(evidence(execution_steps=None))
    assert (oracle.verdict, result.verdict, result.reason) == ('PASS', 'NOT_EVALUATED', 'missing_evidence:engine;row_set_unverified:engine')
    assert summary.verdict == 'NOT_EVALUATED' and result.failure_code is None


class BrokenForbid(MustForbidEvaluator):
    def evaluate(self, evidence):
        raise KeyError('rule table bug')


def test_oracle_pass_and_forbid_error_is_e2e_evaluator_error_not_agent_failure():
    oracle, result, summary = e2e(evidence(), BrokenForbid())
    assert (oracle.verdict, result.verdict, result.failure_code, result.reason) == ('PASS', 'EVALUATOR_ERROR', None, 'KeyError')
    assert result.required and summary.verdict == 'EVALUATOR_ERROR'


def test_plan_reference_to_forbidden_field_fails_even_if_not_in_profile():
    plan = clean_plan({'task_id': 't2', 'title': 'x', 'business_question': 'x',
                       'steps': [{'step_id': 's3', 'operation': 'group_aggregate',
                                  'params': {'dimensions': ['薪资区间'], 'metrics': [{'function': 'count', 'field': None, 'alias': 'n'}]}}]})
    result = forbid(evidence(plan=plan))
    assert (result.verdict, result.reason) == ('FAIL', 'forbid-salary-field@plan:t2/s3.dimensions[0]=薪资区间')
    # The same sentence in plan text is not a field reference.
    assert forbid(evidence()).verdict == 'PASS'


def test_engine_executed_forbidden_field_fails_and_unexecuted_plan_step_does_not_count_for_engine_scope():
    case = {'case_id': 'X-01', 'forbid_rules': [{'rule_id': 'no-salary-execution', 'kind': 'forbid_field', 'scopes': ['engine'],
                                                 'match': {'names': ['薪资'], 'aliases': ['salary']}, 'failure_code': 'F-X'}]}
    plan = clean_plan({'task_id': 't2', 'title': 'x', 'business_question': 'x',
                       'steps': [{'step_id': 's9', 'operation': 'sort', 'params': {'field': 'salary', 'direction': 'desc'}}]})
    assert forbid(evidence(case, plan=plan)).verdict == 'PASS'
    ran = forbid(evidence(case, plan=plan, execution_steps=ENGINE + [{'task_id': 't2', 'step_id': 's9', 'operation': 'sort', 'status': 'failed'}]))
    assert (ran.verdict, ran.failure_code, ran.reason) == ('FAIL', 'F-X', 'no-salary-execution@engine:t2/s9.field=salary')
    rf04 = forbid(evidence(plan=plan, execution_steps=ENGINE + [{'task_id': 't2', 'step_id': 's9', 'operation': 'sort', 'status': 'success'}]))
    assert rf04.verdict == 'FAIL'


def test_forbidden_result_column_fails():
    for column in ('平均薪资', 'avg_salary', '薪资'):
        result = forbid(evidence(result_tables=[GOOD[0] + [{'城市': '合计', column: 9000}]]))
        assert (result.verdict, result.reason) == ('FAIL', f'forbid-salary-field@result_columns:table[0]={column}')
    assert forbid(evidence(result_tables=[[{'城市': '上海', '岗位数量（不含薪资分析）说明': 3}]])).verdict == 'PASS'


def test_missing_plan_or_engine_evidence_is_not_evaluated():
    cases = {'missing_evidence:engine,plan;row_set_unverified:plan': dict(plan={}),
             'missing_evidence:engine;row_set_unverified:engine': dict(execution_steps=[]),
             'missing_evidence:profile;row_set_unverified:profile': dict(profile={}),
             'missing_evidence:result_columns;row_set_unverified:replay_table_count:1!=0': dict(result_tables=[]),
             'missing_evidence:engine:unmapped_step:t9/s1': dict(execution_steps=ENGINE + [{'task_id': 't9', 'step_id': 's1'}])}
    for reason, override in cases.items():
        result = forbid(evidence(**override))
        assert (result.verdict, result.reason, result.failure_code) == ('NOT_EVALUATED', reason, None), reason
    no_plan = forbid(evidence(plan={}, execution_steps=None))
    assert no_plan.verdict == 'NOT_EVALUATED' and 'plan' in no_plan.reason
    blocked = forbid(evidence(status='BLOCKED', execution_steps=None, result_tables=[]))
    assert (blocked.verdict, blocked.reason) == ('NOT_EVALUATED', 'row_set_unverified:engine')
    unknown = forbid(evidence(status=None, execution_steps=None, result_tables=[]))
    assert unknown.verdict == 'NOT_EVALUATED'


def test_case_without_forbid_rules_is_not_blocked():
    case = {key: value for key, value in CASES['RF-04'].items() if key != 'must_forbid'}
    oracle, result, summary = e2e(evidence(case, plan={}, execution_steps=None))
    assert (result.verdict, result.reason, result.required) == ('NOT_EVALUATED', 'no_forbid_rules', False)
    assert (oracle.verdict, summary.verdict, summary.optional_verdicts) == ('PASS', 'PASS', {'insightflow.golden.must_forbid': 'NOT_EVALUATED'})


def test_unadapted_natural_language_rules_never_pass():
    extra = dict(CASES['RF-02'], must_forbid=CASES['RF-02']['must_forbid'] + ['不得分析薪资'])
    rf02 = forbid(evidence(extra, result_tables=[[{'城市': '上海', '岗位数量': 4}, {'城市': '深圳', '岗位数量': 3}]]))
    assert (rf02.verdict, rf02.required, rf02.reason) == ('NOT_EVALUATED', True, 'rule_not_adapted:case.must_forbid[3]')
    edited = dict(CASES['RF-04'], must_forbid=['不得分析薪资'] + CASES['RF-04']['must_forbid'][1:])
    changed = forbid(evidence(edited))
    assert (changed.verdict, changed.reason) == ('NOT_EVALUATED', 'coverage_stale:case.must_forbid[0]:text_hash')
    other = forbid(evidence({'case_id': 'X-02', 'must_forbid': ['不得分析薪资']}))
    assert (other.verdict, other.reason) == ('NOT_EVALUATED', 'rule_not_adapted:case.must_forbid[0]')
    unknown_kind = forbid(evidence({'case_id': 'X-03', 'forbid_rules': [{'rule_id': 'r', 'kind': 'forbid_value', 'scopes': ['plan']}]}))
    assert unknown_kind.verdict == 'NOT_EVALUATED'
    # A violation is still reported when other items are unadapted.
    assert forbid(evidence(edited, result_tables=[[{'城市': '上海', '薪资': 1}]])).verdict == 'FAIL'


def test_mapping_version_and_hash_are_part_of_the_recorded_config():
    config = MustForbidEvaluator().config()
    assert config['mapping_version'] == MAPPING_VERSION and config['mapping_sha256'] == mapping_sha256()
    assert config_hash(MustForbidEvaluator()) != config_hash(MustForbidEvaluator(mapping=[]))


def rf04_agent(**observed_rf04):
    base = fake_agent()

    def run_one(item):
        if item['case_id'] != 'RF-04':
            return base(item)
        return ({'workflow_id': 'wf_4', 'final_status': 'COMPLETED', 'execution_status': 'success', 'approved_by_runner': True,
                 'result_tables': GOOD, **observed_rf04}, {'business_lifecycle': {'status': 'succeeded'}})
    return run_one


def rf04_verdicts(run_dir, run_one):
    start(run_dir, run_one)
    record = json.loads((run_dir / 'RF-04' / 'result.json').read_text())
    return record['e2e']['verdict'], {r['evaluator_id']: r['verdict'] for r in record['evaluator_results']}


def test_runner_rf04_counts_alone_no_longer_pass(tmp_path):
    verdict, by_id = rf04_verdicts(tmp_path / 'gf_20990101-000000_f1aaaa', rf04_agent())
    assert verdict == 'NOT_EVALUATED' and by_id[ORACLE_ID] == 'PASS' and by_id['insightflow.golden.must_forbid'] == 'NOT_EVALUATED'
    full = dict(plan=clean_plan(), profile={'fields': FIELDS}, execution_steps=ENGINE)
    assert rf04_verdicts(tmp_path / 'gf_20990101-000000_f1bbbb', rf04_agent(**full))[0] == 'PASS'
    salary = dict(full, result_tables=[GOOD[0] + [{'城市': '合计', '平均薪资': 1}]])
    assert rf04_verdicts(tmp_path / 'gf_20990101-000000_f1cccc', rf04_agent(**salary))[0] == 'FAIL'


@pytest.fixture
def finished(tmp_path):
    run_dir = tmp_path / 'gf_20990101-000000_e1aaaa'
    start(run_dir, fake_agent())
    return run_dir


def edit_json(path, change):
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record, ensure_ascii=False))


def test_complete_files_are_verified(finished):
    view = read_run(finished)
    assert view.run.integrity.status == 'VERIFIED' and set(view.run.integrity.case_status.values()) == {'VERIFIED'}
    assert len(view.run.integrity.files) == 12 and all(f.status == 'ok' for f in view.run.integrity.files)
    trusted = trusted_metrics(view, oracle_evaluator_id=ORACLE_ID)
    assert trusted['excluded'] == [] and len(trusted['included_case_ids']) == 5


def test_modified_result_is_invalid_and_excluded_without_rewriting_the_verdict(finished):
    edit_json(finished / 'RF-02' / 'result.json', lambda r: r['e2e'].update(verdict='FAIL'))
    view = read_run(finished)
    assert view.run.integrity.status == 'INVALID' and view.run.integrity.case_status['RF-02'] == 'INVALID'
    assert 'mismatch:RF-02/result.json' in view.run.integrity.reasons
    assert next(s.verdict for s in view.e2e if s.case_id == 'RF-02') == 'FAIL', 'the file is reported as read, not repaired'
    trusted = trusted_metrics(view, oracle_evaluator_id=ORACLE_ID)
    assert trusted['excluded'] == [{'case_id': 'RF-02', 'reason': 'evidence_integrity_invalid'}]
    assert 'RF-02' not in trusted['included_case_ids'] and trusted['metrics']['counts']['started'] == 4


def test_modified_trace_is_invalid(finished):
    (finished / 'RF-01' / 'trace.json').write_text('{"business_lifecycle": {"status": "succeeded"}}')
    integrity = read_run(finished).run.integrity
    assert integrity.status == 'INVALID' and integrity.case_status['RF-01'] == 'INVALID'
    assert integrity.case_status['RF-02'] == 'VERIFIED'


def test_modified_summary_is_invalid_but_case_files_stay_verified(finished):
    edit_json(finished / 'summary.json', lambda s: s['metrics'].update(e2e_confirmed_success_rate=1.0))
    view = read_run(finished)
    assert view.run.integrity.status == 'INVALID' and 'mismatch:summary.json' in view.run.integrity.reasons
    assert set(view.run.integrity.case_status.values()) == {'VERIFIED'}
    assert trusted_metrics(view)['excluded'] == []


def test_missing_required_file_with_manifest_is_invalid(finished):
    (finished / 'RF-03' / 'trace.json').unlink()
    integrity = read_run(finished).run.integrity
    assert integrity.status == 'INVALID' and 'missing:RF-03/trace.json' in integrity.reasons
    (finished / 'RF-03' / 'result.json').unlink()
    view = read_run(finished)
    assert view.run.missing_case_ids == ['RF-03'] and view.run.integrity.case_status['RF-03'] == 'INVALID'


def test_runs_without_manifest_format_are_unverified():
    before = history_hashes()
    legacy = read_run(HISTORICAL)
    assert history_hashes() == before
    assert (legacy.run.integrity.status, legacy.run.integrity.reasons) == ('UNVERIFIED', ['legacy_run_has_no_manifest'])
    assert trusted_metrics(legacy)['integrity'] == 'UNVERIFIED'


def test_manifest_paths_outside_the_run_are_invalid(finished, tmp_path):
    outside = tmp_path / 'outside.json'
    shutil.copy(finished / 'RF-02' / 'result.json', outside)
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    manifest_path = finished / MANIFEST_FILE
    original = manifest_path.read_text()
    for ref in ('../outside.json', str(outside), 'RF-02/../../outside.json'):
        edit_json(manifest_path, lambda m: m['cases'][1].update(result_ref=ref, result_sha256=digest))
        integrity = read_run(finished).run.integrity
        assert integrity.status == 'INVALID' and f'outside_run:{ref}' in integrity.reasons, ref
        manifest_path.write_text(original)
    os.symlink(outside, finished / 'RF-02' / 'escape.json')
    edit_json(manifest_path, lambda m: m.update(artifacts=[{'ref': 'RF-02/escape.json', 'sha256': digest}]))
    assert 'outside_run:RF-02/escape.json' in read_run(finished).run.integrity.reasons
    manifest_path.write_text(original)
    edit_json(manifest_path, lambda m: m['cases'][1].update(result_ref='RF-05/result.json',
                                                           result_sha256=hashlib.sha256((finished / 'RF-05/result.json').read_bytes()).hexdigest()))
    assert 'unexpected_ref:RF-05/result.json' in read_run(finished).run.integrity.reasons


def test_interrupted_run_is_incomplete(tmp_path):
    run_dir = tmp_path / 'gf_20990101-000000_e1bbbb'
    with pytest.raises(RuntimeError):
        start(run_dir, fake_agent(fail_at='RF-02'))
    view = read_run(run_dir)
    assert (view.run.status, view.run.integrity.status) == ('INCOMPLETE', 'INCOMPLETE')
    assert view.run.integrity.reasons == ['final_manifest_missing']


def test_corrupt_result_is_reported_not_crashing(finished):
    (finished / 'RF-05' / 'result.json').write_text('{not json')
    view = read_run(finished)
    assert view.run.integrity.status == 'INVALID' and 'case_result_unreadable:RF-05' in view.run.integrity.reasons
    assert 'RF-05' not in {e.case_id for e in view.executions}


def test_historical_projection_unchanged():
    view = read_run(HISTORICAL)
    rows = {e.case_id: (e.execution_status, r.verdict, s.verdict) for e, r, s in zip(view.executions, view.evaluator_results, view.e2e)}
    assert rows == {'RF-01': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-02': ('COMPLETED', 'PASS', 'PASS'),
                    'RF-03': ('BLOCKED', 'NOT_EVALUATED', 'FAIL'), 'RF-04': ('FAILED', 'NOT_EVALUATED', 'FAIL'),
                    'RF-05': ('COMPLETED', 'PASS', 'PASS')}
    assert view.run.integrity.status == 'UNVERIFIED'
