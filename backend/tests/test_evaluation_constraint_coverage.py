"""Constraint Coverage Mapping. Evidence comes from running the registered engine kernels on the
Golden rows, so plan, step log and result tables agree; historical runs are only read."""
import hashlib
import itertools
import json

import pandas as pd
import pytest

from app.domain.dataset_profile import LogicalType
from app.evaluation import constraint_coverage as cc
from app.evaluation.aggregate import summarize
from app.evaluation.contracts import CaseExecution
from app.evaluation.evaluators import GoldenOracleEvaluator
from app.evaluation.golden_fidelity import load_golden
from app.evaluation.must_forbid import MustForbidEvaluator
from app.evaluation.protocol import EvaluationEvidence, config_hash, run_evaluator
from app.evaluation.row_set import aggregation_inputs
from app.evaluation.runs import read_run
from app.planning.capabilities import CapabilityRegistry
from test_evaluation_contracts import GOLD_PATH, HISTORICAL, NOW, history_hashes, start

GOLDEN = load_golden()
ROWS = GOLDEN['rows']
CASES = {c['case_id']: c for c in GOLDEN['cases']}
REGISTRY = CapabilityRegistry()
COLUMNS = GOLDEN['columns']
FIELD = {name: f'field_{i:04d}' for i, name in enumerate(COLUMNS, 1)}
PROFILE = {'fields': [{'field_id': FIELD[name], 'original_name': name, 'display_name': name, 'logical_type': 'text'}
                      for name in COLUMNS]}
TYPES = {fid: LogicalType.TEXT for fid in FIELD.values()}
TWO_CITIES = ('城市', 'in', ['上海', '深圳'])
BY_CITY = ('group_aggregate', {'dimensions': [FIELD['城市']], 'metrics': [{'function': 'count', 'alias': '岗位数量'}]})
BY_CITY_TYPE = ('group_aggregate', {'dimensions': [FIELD['城市'], FIELD['岗位类型']],
                                    'metrics': [{'function': 'count', 'alias': '岗位数量'}]})
ORACLE_HISTORY = {'RF-01': {'上海': 3, '深圳': 1}, 'RF-02': {'上海': 4, '深圳': 3}, 'RF-03': {'上海': 1, '深圳': 2},
                  'RF-04': {'上海': 3, '深圳': 1}, 'RF-05': {'深圳': 3, '北京': 1, '杭州': 1}}


def where(*conditions):
    return ('filter', {'conditions': [{'field': FIELD[f], 'operator': op, 'value': v} for f, op, v in conditions]})


def run_plan(*tasks):
    """Execute each task's steps with the registered kernels and record what the runner would observe."""
    base = pd.DataFrame(ROWS).rename(columns=FIELD).astype(object)
    plan, executed, tables = {'tasks': []}, [], []
    for t, steps in enumerate(tasks, 1):
        frame, task = base.copy(), {'task_id': f't{t}', 'title': '不要分析薪资', 'steps': []}
        for s, (operation, params) in enumerate(steps, 1):
            spec = REGISTRY.operations[operation]
            frame = spec.handler(frame, spec.params_model.model_validate(params), TYPES)
            task['steps'].append({'step_id': f's{s}', 'operation': operation, 'params': params})
            executed.append({'task_id': f't{t}', 'step_id': f's{s}', 'operation': operation, 'status': 'success',
                             'output_row_count': len(frame)})
        plan['tasks'].append(task)
        tables.append(json.loads(frame.to_json(orient='records', force_ascii=False)))
    return {'plan': plan, 'profile': PROFILE, 'execution_steps': executed, 'result_tables': tables,
            'engine_execution_status': 'success'}


CORRECT = {
    'RF-01': [where(TWO_CITIES, ('岗位类型', 'ne', '实习')), BY_CITY],
    'RF-02': [where(TWO_CITIES), BY_CITY],
    'RF-03': [where(TWO_CITIES, ('岗位类型', 'eq', '实习')), BY_CITY],
    'RF-04': [where(TWO_CITIES, ('岗位类型', 'ne', '实习')), BY_CITY],
    'RF-05': [where(('城市', 'ne', '上海')), BY_CITY],
}


def evidence(case, artifacts, status='COMPLETED'):
    case = CASES[case] if isinstance(case, str) else case
    execution = CaseExecution(execution_id=None, locator=f"run/{case['case_id']}", run_id='run', case_id=case['case_id'], attempt=1,
                              execution_status=status, failure_origin=None, workflow_id=None, started_at=None, finished_at=None,
                              record_ref=None, output_ref='out', trace_ref=None, error_code=None, blocking_stage=None,
                              provenance='recorded')
    artifacts = {'dataset_id': GOLDEN['set_id'], 'dataset_rows': ROWS, **artifacts}
    return EvaluationEvidence(case=case, execution=execution, artifacts=artifacts,
                              refs={'case': f"golden-set.json#cases[{case['case_id']}]", 'plan': 'p', 'engine': 'e',
                                    'result_columns': 'r', 'output': 'out'})


def judge(ev, evaluator=None):
    oracle = run_evaluator(GoldenOracleEvaluator(), ev, required='required', now=NOW)
    forbid = run_evaluator(evaluator or MustForbidEvaluator(), ev, required='required_when_applicable', now=NOW)
    return oracle, forbid, summarize(ev.execution, [oracle, forbid])


def test_1_oracle_pass_with_valid_coverage_passes_the_covered_constraints():
    expected = {'RF-01': 'row_set:1;oracle_covered:4', 'RF-02': 'oracle_covered:3', 'RF-03': 'row_set:2',
                'RF-04': 'forbid_field:plan,engine,result_columns;row_set:1', 'RF-05': 'oracle_covered:4'}
    for case_id, steps in CORRECT.items():
        oracle, forbid, summary = judge(evidence(case_id, run_plan(steps)))
        assert (oracle.verdict, forbid.verdict, forbid.reason, summary.verdict) == ('PASS', 'PASS', expected[case_id], 'PASS'), case_id


def test_2_oracle_fail_never_passes_through_the_mapping():
    for case_id, steps in (('RF-02', [where(TWO_CITIES, ('岗位类型', 'ne', '实习')), BY_CITY]),
                           ('RF-05', [where(('城市', 'ne', '上海'), ('岗位类型', 'ne', '实习')), BY_CITY])):
        oracle, forbid, summary = judge(evidence(case_id, run_plan(steps)))
        assert (oracle.verdict, oracle.failure_code) == ('FAIL', 'F-EXTRA-CONSTRAINT')
        assert forbid.verdict == 'NOT_EVALUATED' and forbid.reason.startswith('oracle_not_pass:case.must_forbid[0]')
        assert summary.verdict == 'FAIL'


def test_3_oracle_not_evaluated_leaves_covered_constraints_not_evaluated():
    artifacts = run_plan(CORRECT['RF-02'])
    for override in ({'engine_execution_status': 'failed'}, {'result_tables': []}):
        oracle, forbid, _ = judge(evidence('RF-02', {**artifacts, **override}))
        assert oracle.verdict == 'NOT_EVALUATED'
        assert (forbid.verdict, forbid.reason) == (
            'NOT_EVALUATED', 'oracle_not_evaluated:case.must_forbid[0],case.must_forbid[1],case.must_forbid[2]')


def test_4_changed_sentence_invalidates_its_mapping():
    edited = dict(CASES['RF-05'], must_forbid=['不得保留上海和北京。'] + CASES['RF-05']['must_forbid'][1:])
    _, forbid, summary = judge(evidence(edited, run_plan(CORRECT['RF-05'])))
    assert (forbid.verdict, forbid.reason, summary.verdict) == ('NOT_EVALUATED', 'coverage_stale:case.must_forbid[0]:text_hash', 'NOT_EVALUATED')


def test_5_evaluator_version_mismatch_invalidates_the_mapping(monkeypatch):
    rf02 = evidence('RF-02', run_plan(CORRECT['RF-02']))
    monkeypatch.setattr(GoldenOracleEvaluator, 'evaluator_version', 'golden-oracle-v3')
    _, forbid, _ = judge(rf02)
    assert forbid.verdict == 'NOT_EVALUATED'
    assert forbid.reason == 'coverage_stale:' + ','.join(f'case.must_forbid[{i}]:evaluator_version' for i in range(3))
    monkeypatch.undo()

    class NextChecker(MustForbidEvaluator):
        evaluator_version = 'must-forbid-v3'
    _, forbid, _ = judge(evidence('RF-04', run_plan(CORRECT['RF-04'])), NextChecker())
    assert forbid.verdict == 'NOT_EVALUATED' and 'case.must_execute[0]:evaluator_version' in forbid.reason
    assert 'case.must_forbid[4]:evaluator_version' in forbid.reason, 'non-assertions are pinned too'
    # Pinned basis: dataset rows and engine capability version.
    changed = [dict(row) for row in ROWS]
    changed[3]['岗位类型'] = '正式'
    _, forbid, _ = judge(evidence('RF-05', {**run_plan(CORRECT['RF-05']), 'dataset_rows': changed}))
    assert forbid.verdict == 'NOT_EVALUATED' and 'case.must_forbid[0]:dataset_rows' in forbid.reason
    monkeypatch.setattr(CapabilityRegistry, 'version', '2.0')
    _, forbid, _ = judge(evidence('RF-05', run_plan(CORRECT['RF-05'])))
    assert forbid.verdict == 'NOT_EVALUATED' and 'case.must_forbid[3]:capability_version' in forbid.reason


def test_6_unmapped_required_constraint_is_not_evaluated():
    extra = dict(CASES['RF-02'], must_forbid=CASES['RF-02']['must_forbid'] + ['不得输出百分比。'])
    oracle, forbid, summary = judge(evidence(extra, run_plan(CORRECT['RF-02'])))
    assert (oracle.verdict, forbid.verdict, forbid.required) == ('PASS', 'NOT_EVALUATED', True)
    assert forbid.reason == 'rule_not_adapted:case.must_forbid[3]' and summary.verdict == 'NOT_EVALUATED'
    other = evidence({'case_id': 'X-01', 'oracle': {'上海': 4, '深圳': 3}, 'must_forbid': CASES['RF-02']['must_forbid']},
                     run_plan(CORRECT['RF-02']))
    assert judge(other)[1].reason == 'rule_not_adapted:case.must_forbid[0],case.must_forbid[1],case.must_forbid[2]'


def test_7_non_assertion_is_not_an_independent_gate():
    entry = next(e for e in cc.MAPPING if (e['case_id'], e['constraint_field'], e['constraint_index']) == ('RF-04', 'must_forbid', 4))
    assert entry['verification_mode'] == 'NON_ASSERTION' and entry['check'] is None
    # Only the clarification is mapped: nothing executable, so it neither passes nor fails the case.
    only = dict(CASES['RF-04'], must_forbid=CASES['RF-04']['must_forbid'][4:], must_execute=[])
    only_mapping = [dict(entry, constraint_index=0)]
    _, forbid, _ = judge(evidence(only, run_plan(CORRECT['RF-04'])), MustForbidEvaluator(mapping=only_mapping))
    assert (forbid.verdict, forbid.reason) == ('NOT_EVALUATED', 'no_executable_rule')
    # The plan title repeats 不要分析薪资; RF-04 still passes and the clarification adds no check.
    _, forbid, _ = judge(evidence('RF-04', run_plan(CORRECT['RF-04'])))
    assert forbid.verdict == 'PASS' and 'NON_ASSERTION' not in forbid.reason


def test_8_independent_check_violation_fails_even_when_the_oracle_passes():
    cases = [('RF-01', [where(TWO_CITIES, ('岗位名称', 'eq', '产品经理')), BY_CITY], 'F-EXCLUDE-DROPPED',
              'row_set@must_execute[0]:t1:included=J04'),
             ('RF-04', [where(TWO_CITIES, ('岗位名称', 'eq', '产品经理')), BY_CITY], 'F-EXCLUDE-DROPPED',
              'row_set@must_execute[0]:t1:included=J04'),
             ('RF-03', [where(TWO_CITIES, ('岗位名称', 'eq', '分析师')), BY_CITY], 'F-EXTRA-CONSTRAINT',
              'row_set@must_forbid[0]:t1:missing=J04'),
             ('RF-03', [where(TWO_CITIES), BY_CITY_TYPE], 'F-EXCLUDE-DROPPED', 'row_set@must_forbid[1]:t1:included=J01+J02+J03+J05'),
             ('RF-01', [where(TWO_CITIES), BY_CITY_TYPE, ('sort', {'field': FIELD['岗位类型'], 'direction': 'asc'})],
              'F-EXCLUDE-DROPPED', 'row_set@must_execute[0]:t1:included=J04+J06+J07')]
    for case_id, steps, code, reason in cases:
        oracle, forbid, summary = judge(evidence(case_id, run_plan(steps)))
        assert oracle.verdict == 'PASS', (case_id, reason)
        assert (forbid.verdict, forbid.failure_code, forbid.reason) == ('FAIL', code, reason)
        assert (summary.verdict, summary.gate) == ('FAIL', 'required_evaluator')


def test_8b_repeated_oracle_label_fails_the_guard():
    tables = [[{'城市': '上海', '岗位数量': 1}, {'城市': '上海', '岗位数量': 4}, {'城市': '深圳', '岗位数量': 3}]]
    oracle, forbid, summary = judge(evidence('RF-02', {**run_plan(CORRECT['RF-02']), 'result_tables': tables}))
    assert oracle.verdict == 'PASS', 'find_mapping keeps the last row of a repeated label'
    assert (forbid.verdict, forbid.failure_code, forbid.reason) == ('FAIL', 'F-ORACLE-MISS', 'unique-oracle-labels@table[0].城市=上海')
    assert summary.verdict == 'FAIL'


def test_9_missing_execution_evidence_is_not_evaluated():
    good = run_plan(CORRECT['RF-01'])
    tampered = [dict(step, output_row_count=9) if step['step_id'] == 's1' else step for step in good['execution_steps']]
    cases = {'row_set_unverified:plan': {'plan': {}},
             'row_set_unverified:profile': {'profile': {}},
             'row_set_unverified:engine': {'execution_steps': None},
             'row_set_unverified:replay_mismatch:t1/s1': {'execution_steps': tampered},
             'row_set_unverified:replay_table_count:1!=2': {'result_tables': good['result_tables'] * 2},
             'row_set_unverified:dataset_rows;missing_evidence:dataset_rows': {'dataset_rows': None}}
    for reason, override in cases.items():
        _, forbid, summary = judge(evidence('RF-01', {**good, **override}))
        assert (forbid.verdict, forbid.reason, summary.verdict) == ('NOT_EVALUATED', reason, 'NOT_EVALUATED'), forbid.reason


def test_10_rf04_salary_rule_does_not_regress():
    salary_profile = {'fields': PROFILE['fields'] + [{'field_id': 'field_0005', 'original_name': '薪资', 'display_name': '薪资'}]}
    good = run_plan(CORRECT['RF-04'])
    salary_task = {'task_id': 't2', 'title': 'x', 'steps': [{'step_id': 's1', 'operation': 'aggregate',
                   'params': {'metrics': [{'function': 'avg', 'field': 'field_0005', 'alias': 'm'}]}}]}
    plan = {'tasks': good['plan']['tasks'] + [salary_task]}
    oracle, forbid, summary = judge(evidence('RF-04', {**good, 'plan': plan, 'profile': salary_profile}))
    assert (oracle.verdict, forbid.verdict, forbid.failure_code) == ('PASS', 'FAIL', 'F-METRIC-SUBSTITUTED')
    assert forbid.reason == 'forbid-salary-field@plan:t2/s1.metrics[0].field=field_0005(薪资)' and summary.verdict == 'FAIL'
    column = judge(evidence('RF-04', {**good, 'result_tables': [good['result_tables'][0] + [{'城市': '合计', '平均薪资': 1}]]}))[1]
    assert (column.verdict, column.reason) == ('FAIL', 'forbid-salary-field@result_columns:table[0]=平均薪资')
    assert judge(evidence('RF-04', good))[1].verdict == 'PASS'


def test_11_golden_oracles_are_unchanged_and_row_lists_follow_from_the_rows():
    assert hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest() == 'fe52a92cc77bb16fa5425f5618c7d7a9dd633f0790eaf341a3c434554a052142'
    assert {cid: c['oracle'] for cid, c in CASES.items()} == ORACLE_HISTORY
    assert GoldenOracleEvaluator.evaluator_version == cc.ORACLE_VERSION == 'golden-oracle-v2'
    assert cc.rows_sha256(ROWS) == cc.ROWS_SHA256
    ids = lambda pred: sorted(r['编号'] for r in ROWS if pred(r))
    assert cc.INTERN_ROWS == ids(lambda r: r['岗位类型'] == '实习')
    assert cc.FULL_TIME_ROWS == ids(lambda r: r['岗位类型'] == '正式')
    assert cc.TWO_CITY_INTERN_ROWS == ids(lambda r: r['岗位类型'] == '实习' and r['城市'] in {'上海', '深圳'})
    for entry in cc.MAPPING:
        texts = CASES[entry['case_id']][entry['constraint_field']]
        assert entry['constraint_text_hash'] == cc.text_sha256(texts[entry['constraint_index']])
        assert entry['dataset_id'] == GOLDEN['set_id'] and entry['mapping_version'] == cc.MAPPING_VERSION
    every = {(c, i) for c, case in CASES.items() for i in range(len(case['must_forbid']))}
    assert every == {(e['case_id'], e['constraint_index']) for e in cc.MAPPING if e['constraint_field'] == 'must_forbid'}


def test_12_history_is_not_rewritten_or_backfilled(tmp_path):
    before = history_hashes()
    view = read_run(HISTORICAL)
    assert history_hashes() == before
    assert 'insightflow.golden.must_forbid' not in {r.evaluator_id for r in view.evaluator_results}
    assert view.run.integrity.status == 'UNVERIFIED'


def candidate_plans(case_id):
    """Every plan of up to two equality/inequality filters on any column value, then a city count."""
    values = [(column, value) for column in COLUMNS[1:] for value in sorted({r[column] for r in ROWS})]
    conditions = [(c, op, v) for c, v in values for op in ('eq', 'ne')]
    for size in (1, 2):
        for combo in itertools.combinations(conditions, size):
            yield [where(*combo), BY_CITY]


def reached(steps):
    artifacts = run_plan(steps)
    inputs, gaps = aggregation_inputs(artifacts['plan'], PROFILE, artifacts['execution_steps'], ROWS, '编号')
    return artifacts, (inputs.get('t1') if not gaps else None)


def test_counterexample_correct_numbers_with_wrong_filter_are_not_oracle_covered():
    modes = {(e['case_id'], e['constraint_field'], e['constraint_index']): e['verification_mode'] for e in cc.MAPPING}
    assert modes[('RF-01', 'must_execute', 0)] == modes[('RF-04', 'must_execute', 0)] == 'INDEPENDENT_CHECK'
    assert modes[('RF-03', 'must_forbid', 0)] == modes[('RF-03', 'must_forbid', 1)] == 'INDEPENDENT_CHECK'
    oracle = GoldenOracleEvaluator()
    passing = {}
    for case_id in ('RF-01', 'RF-02', 'RF-03', 'RF-05'):
        passing[case_id] = []
        for steps in candidate_plans(case_id):
            artifacts, rows = reached(steps)
            if oracle.evaluate(evidence(case_id, artifacts)).verdict == 'PASS':
                passing[case_id].append(frozenset(rows))
    # RF-02 and RF-05: every oracle-passing plan counts exactly the same rows, interns included.
    assert set(passing['RF-02']) == {frozenset({'J01', 'J02', 'J03', 'J04', 'J05', 'J06', 'J07'})}
    assert set(passing['RF-05']) == {frozenset({'J05', 'J06', 'J07', 'J08', 'J09'})}
    # RF-01 and RF-03: some oracle-passing plan counts rows the requirement excludes.
    assert any(rows & set(cc.INTERN_ROWS) for rows in passing['RF-01'])
    assert any(rows & set(cc.FULL_TIME_ROWS) for rows in passing['RF-03'])


def test_runner_records_mapping_in_config_hash_and_fails_wrong_filter(tmp_path):
    from test_evaluation_contracts import fake_agent
    base = fake_agent()
    wrong = run_plan([where(TWO_CITIES, ('岗位名称', 'eq', '产品经理')), BY_CITY])

    def run_one(item):
        if item['case_id'] != 'RF-01':
            return base(item)
        return ({'workflow_id': 'wf_1', 'final_status': 'COMPLETED', 'execution_status': 'success', 'approved_by_runner': True,
                 **{k: v for k, v in wrong.items() if k != 'engine_execution_status'}}, {'business_lifecycle': {'status': 'succeeded'}})
    run_dir = tmp_path / 'gf_20990101-000000_c0ffee'
    summary = start(run_dir, run_one)
    config = json.loads((run_dir / 'run-config.json').read_text())
    entry = next(e for e in config['evaluators'] if e['evaluator_id'] == 'insightflow.golden.must_forbid')
    assert (entry['evaluator_version'], entry['config_sha256']) == ('must-forbid-v2', config_hash(MustForbidEvaluator()))
    assert config_hash(MustForbidEvaluator()) != config_hash(MustForbidEvaluator(mapping=cc.MAPPING[:-1]))
    rf01 = next(c for c in summary['cases'] if c['case_id'] == 'RF-01')
    assert (rf01['oracle'], rf01['e2e']) == ('PASS', 'FAIL')
    record = json.loads((run_dir / 'RF-01' / 'result.json').read_text())
    forbid = next(r for r in record['evaluator_results'] if r['evaluator_id'] == 'insightflow.golden.must_forbid')
    assert (forbid['verdict'], forbid['failure_code']) == ('FAIL', 'F-EXCLUDE-DROPPED')
