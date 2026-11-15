"""Run detail, case detail, evidence and dataset detail. Temp directories and scripted agents only; no model calls.

Historical runs are only read. Their file list, mtimes and hashes are compared before and after.
"""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.evaluation.admin_views import CaseDetail, DatasetDetail, DatasetListPage, EvidenceView, RunDetail, RunListPage
from app.evaluation.datasets import DatasetSource
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden
from app.evaluation.golden_run import run_golden
from app.evaluation.run_index import EvaluationRoot
from app.evaluation.runs import read_run, trusted_metrics
from app.main import create_app
from app.services.evaluation_admin import build_evaluation_admin
from test_evaluation_contracts import NOW, Boom, fake_agent, start
from test_evaluation_discovery import GOLDEN_REF, HISTORICAL_GOLDEN, HISTORICAL_TC, REPO, TC_CASES, TC_REF, _sha, _snapshot
from test_evaluation_quality_gates import rf04_agent

AUTH = {'X-Admin-Token': 'read'}
HIST_GOLDEN_RUN = 'gf_20261112-143406_cde1fd'
HIST_TC_RUN = 'rg_20261112-133157_f04289'
ORACLE = GoldenOracleEvaluator.evaluator_id


@pytest.fixture
def no_sqlite(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError('SQLite must not be opened')
    monkeypatch.setattr(sqlite3, 'connect', refuse)


def service(*roots, sources=None):
    return build_evaluation_admin(list(roots), sources if sources is not None else [DatasetSource('golden', GOLD_PATH, GOLDEN_REF, 'golden')],
                                  GOLD_PATH)


def golden_root(tmp_path, name='golden'):
    root = tmp_path / name
    root.mkdir()
    return root, EvaluationRoot(name, root, 'golden')


def code(call):
    with pytest.raises(AppError) as error:
        call()
    return error.value.status, error.value.error.code


def edit_json(path, change):
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record, ensure_ascii=False))


def test_new_verified_run_detail_matches_read_run_for_rf01_to_rf05(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a1a1a1'
    start(run_dir, fake_agent())
    detail = service(entry).get_run(run_dir.name)
    RunDetail.model_validate(detail.model_dump())
    view = read_run(run_dir)
    assert detail.provenance == 'recorded' and detail.integrity.status == 'VERIFIED' and detail.integrity.trusted
    assert detail.agent_id == 'insightflow' and detail.agent_version is None and detail.dataset_version is None
    assert [e.evaluator_id for e in detail.evaluator_manifest] == [e.evaluator_id for e in view.run.evaluator_manifest]
    assert detail.case_counts.total == 5 and detail.case_counts.present == 5
    by_case = {c.case_id: c for c in detail.cases}
    for summary in view.e2e:
        assert by_case[summary.case_id].e2e_verdict == summary.verdict and by_case[summary.case_id].e2e_gate == summary.gate
    assert (by_case['RF-01'].execution_status, by_case['RF-01'].e2e_verdict, by_case['RF-01'].attribution.value) == ('BLOCKED', 'FAIL', 'agent_execution')
    assert (by_case['RF-03'].execution_status, by_case['RF-03'].attribution.value) == ('BLOCKED', 'agent_execution')
    assert (by_case['RF-04'].execution_status, by_case['RF-04'].failure_origin, by_case['RF-04'].attribution.value) == ('FAILED', 'agent', 'agent_execution')
    for case_id in ('RF-02', 'RF-05'):
        assert (by_case[case_id].execution_status, by_case[case_id].e2e_verdict, by_case[case_id].attribution.value) == ('COMPLETED', 'PASS', 'none')
    expected = trusted_metrics(view, oracle_evaluator_id=ORACLE)['metrics']
    metrics = detail.metrics
    assert metrics.trust == 'verified' and metrics.trusted
    assert metrics.e2e_confirmed_success_rate.rate == expected['e2e_confirmed_success_rate']
    assert metrics.decidable_pass_rate.rate == expected['decidable_pass_rate']
    assert metrics.evaluation_coverage.rate == expected['evaluation_coverage']
    assert metrics.execution_completion_rate.rate == expected['execution_completion_rate']
    assert (metrics.e2e_confirmed_success_rate.numerator, metrics.e2e_confirmed_success_rate.denominator) == (2, 5)


def test_case_detail_slots_required_optional_and_not_evaluated(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a2a2a2'
    start(run_dir, fake_agent())
    svc = service(entry)
    rf01 = svc.get_case(run_dir.name, 'RF-01')
    CaseDetail.model_validate(rf01.model_dump())
    oracle = next(e for e in rf01.evaluators if e.role == 'oracle')
    assert (oracle.required, oracle.requirement, oracle.verdict) == (True, 'required', 'NOT_EVALUATED')
    assert rf01.e2e.verdict == 'FAIL' and rf01.e2e.gate == 'task_condition' and rf01.attribution.value == 'agent_execution'
    assert oracle.failure_code is None, 'NOT_EVALUATED keeps no failure code'
    node = next(e for e in rf01.evaluators if e.role == 'node_fidelity')
    assert node.required is False and node.requirement == 'optional'
    assert {name: slot.state for name, slot in rf01.slots.items()} == {'oracle': 'recorded', 'must_forbid': 'recorded', 'node_fidelity': 'recorded'}
    assert rf01.execution_record.available and rf01.execution_record.integrity == 'ok'
    assert rf01.final_output.available is False and rf01.final_output.integrity == 'not_applicable'
    rf02 = svc.get_case(run_dir.name, 'RF-02')
    assert rf02.final_output.available and rf02.final_output.ref == 'RF-02/result.json#observed.result_tables'
    assert rf02.e2e.trusted and rf02.case_integrity == 'VERIFIED'
    pending_dir = root / 'gf_20990101-000000_a3a3a3'
    start(pending_dir, rf04_agent())
    rf04 = svc.get_case(pending_dir.name, 'RF-04')
    assert rf04.e2e.verdict == 'NOT_EVALUATED' and rf04.attribution.value == 'undetermined'
    assert rf04.slots['must_forbid'].verdict == 'NOT_EVALUATED'


def test_evaluator_error_is_its_own_attribution(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a4a4a4'
    run_golden(run_dir, load_golden(), GOLD_PATH.read_bytes(), 'golden-set.json', run_one=fake_agent(), model={'name': 'scripted'},
               environment={'source_fingerprint': 'test'}, clock=NOW,
               evaluators=[(GoldenOracleEvaluator(), 'required'), (Boom(), 'required'), (RequirementFidelityNodeEvaluator(), 'optional')])
    svc = service(entry)
    rf02 = svc.get_case(run_dir.name, 'RF-02')
    boom = next(e for e in rf02.evaluators if e.evaluator_id == 'boom')
    assert boom.verdict == 'EVALUATOR_ERROR' and boom.failure_code is None and boom.role == 'other'
    assert rf02.e2e.verdict == 'EVALUATOR_ERROR' and rf02.attribution.value == 'evaluator_error'
    assert rf02.slots['must_forbid'].state == 'not_recorded' and 'not NOT_EVALUATED' in rf02.slots['must_forbid'].notice
    detail = svc.get_run(run_dir.name)
    boom_health = next(h for h in detail.metrics.evaluators if h.evaluator_id == 'boom')
    assert boom_health.error_rate.numerator == boom_health.error_rate.denominator == 5


def test_invalid_run_excludes_tampered_case_and_is_not_trusted(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a5a5a5'
    start(run_dir, fake_agent())
    edit_json(run_dir / 'RF-02' / 'result.json', lambda r: r['e2e'].update(verdict='FAIL'))
    svc = service(entry)
    detail = svc.get_run(run_dir.name)
    assert detail.integrity.status == 'INVALID' and not detail.integrity.trusted
    assert detail.metrics.trust == 'partial_verified' and detail.metrics.trusted is False
    assert 'RF-02' not in detail.metrics.included_case_ids
    assert detail.metrics.excluded == [{'case_id': 'RF-02', 'reason': 'evidence_integrity_invalid'}]
    assert detail.metrics.counts['started'] == 4
    rf02 = next(c for c in detail.cases if c.case_id == 'RF-02')
    assert rf02.case_integrity == 'INVALID' and rf02.attribution.value == 'evidence_integrity'
    case = svc.get_case(run_dir.name, 'RF-02')
    assert case.case_integrity == 'INVALID' and case.e2e.trusted is False
    assert any(f.status == 'mismatch' for f in case.case_files)
    evidence = svc.get_evidence(run_dir.name, 'RF-02', 'result_tables')
    assert evidence.integrity.status == 'mismatch' and evidence.integrity.trusted is False
    verified = svc.get_evidence(run_dir.name, 'RF-05', 'result_tables')
    assert verified.integrity.status == 'ok' and verified.integrity.trusted


def test_incomplete_run_lists_missing_cases(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a6a6a6'
    with pytest.raises(RuntimeError):
        start(run_dir, fake_agent(fail_at='RF-03'))
    svc = service(entry)
    detail = svc.get_run(run_dir.name)
    assert detail.lifecycle_status == 'INCOMPLETE' and detail.integrity.status == 'INCOMPLETE'
    assert detail.missing_case_ids == ['RF-03', 'RF-04', 'RF-05']
    assert detail.case_counts.missing == 3 and detail.case_counts.present == 2
    assert detail.metrics.trust == 'incomplete' and detail.metrics.trusted is False
    missing = svc.get_case(run_dir.name, 'RF-04')
    assert missing.case_state == 'missing' and missing.execution is None and missing.e2e is None
    assert missing.attribution.value == 'not_executed'
    assert {item.status for item in missing.evidence} == {'NOT_RECORDED'}
    assert svc.get_evidence(run_dir.name, 'RF-04', 'trace').status == 'NOT_RECORDED'
    assert svc.get_evidence(run_dir.name, 'RF-01', 'trace').integrity.status == 'incomplete'


def leaky_agent():
    base = fake_agent()
    deep = {}
    node = deep
    for _ in range(40):
        node['n'] = {}
        node = node['n']

    def run_one(item):
        observed, trace = base(item)
        if item['case_id'] == 'RF-02':
            trace = {**trace, 'trace': {
                'llm_calls': [{'endpoint': 'https://llm.example-provider.com/v1/chat', 'api_key': 'sk-abcdefghijklmnop1234',
                               'input_tokens': 12, 'headers': {'Authorization': 'Bearer abcdefghijkl123'}}],
                'nodes': [{'intent_result': {'user_query': '对比上海和深圳的岗位数量'},
                           'note': 'see https://internal.example-provider.com/x and /Users/someone/secret/file.txt',
                           'session_token': 'tok-123456', 'base_url': 'https://other.example-provider.com'}],
                'deep': deep}}
        if item['case_id'] == 'RF-03':
            trace = {**trace, 'blob': 'y' * 1_500_000}
        if item['case_id'] == 'RF-04':
            trace = {**trace, 'many': list(range(60_000))}
        if item['case_id'] == 'RF-05':
            trace = {**trace, 'blob': 'x' * (2 * 1024 * 1024 + 10)}
        return observed, trace
    return run_one


def test_evidence_redaction_limits_and_missing(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a7a7a7'
    start(run_dir, leaky_agent())
    svc = service(entry)
    trace = svc.get_evidence(run_dir.name, 'RF-02', 'trace')
    EvidenceView.model_validate(trace.model_dump())
    text = trace.model_dump_json()
    for leaked in ('example-provider.com', 'sk-abcdefghijklmnop', 'Bearer abcdefghijkl', '/Users/someone', 'tok-123456',
                   '对比上海和深圳的岗位数量', str(tmp_path)):
        assert leaked not in text, leaked
    call = trace.content['trace']['llm_calls'][0]
    assert 'endpoint' not in call and call['api_key'] == '[redacted:credential]' and call['input_tokens'] == 12
    assert call['headers']['Authorization'] == '[redacted:credential]'
    query = trace.content['trace']['nodes'][0]['intent_result']['user_query']
    assert query['redacted'] == 'user_text' and query['chars'] == 12 and len(query['sha256']) == 64
    assert 'base_url' not in trace.content['trace']['nodes'][0]
    rules = {r['rule'] for r in trace.redactions}
    assert {'endpoint_removed', 'secret_key_replaced', 'user_text_minimized', 'url_in_text_replaced', 'local_path_replaced'} <= rules
    assert trace.depth_truncated_paths and trace.integrity.status == 'ok' and trace.integrity.trusted
    assert code(lambda: svc.get_evidence(run_dir.name, 'RF-05', 'trace')) == (413, 'EVIDENCE_TOO_LARGE')
    assert code(lambda: svc.get_evidence(run_dir.name, 'RF-04', 'trace')) == (413, 'EVIDENCE_TOO_LARGE')
    assert code(lambda: svc.get_evidence(run_dir.name, 'RF-03', 'trace')) == (413, 'EVIDENCE_TOO_LARGE')
    detail = svc.get_run(run_dir.name)
    assert detail.integrity.status == 'VERIFIED', 'an oversized evidence file does not break run detail'
    case = svc.get_case(run_dir.name, 'RF-05')
    assert next(item for item in case.evidence if item.kind == 'trace').status == 'AVAILABLE'
    missing = svc.get_evidence(run_dir.name, 'RF-01', 'result_tables')
    assert missing.status == 'NOT_RECORDED' and missing.content is None
    refs = svc.get_evidence(run_dir.name, 'RF-01', 'evaluator_refs')
    assert refs.status == 'AVAILABLE' and {item['evaluator_id'] for item in refs.content} >= {ORACLE}
    (run_dir / 'RF-01' / 'trace.json').unlink()
    gone = svc.get_evidence(run_dir.name, 'RF-01', 'trace')
    assert gone.status == 'NOT_RECORDED' and gone.reason == 'file_missing' and gone.integrity.status == 'missing'
    assert svc.get_run(run_dir.name).integrity.status == 'INVALID'


def test_tampered_trace_ref_and_symlinks_stay_inside(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    run_dir = root / 'gf_20990101-000000_a8a8a8'
    start(run_dir, fake_agent())
    (tmp_path / 'secret.json').write_text('{"value": "secret-token"}')
    edit_json(run_dir / 'RF-03' / 'result.json', lambda r: r['execution'].update(trace_ref='../../secret.json'))
    svc = service(entry)
    evidence = svc.get_evidence(run_dir.name, 'RF-03', 'trace')
    assert evidence.status == 'UNAVAILABLE' and evidence.reason == 'outside_run_directory' and evidence.content is None
    assert 'secret-token' not in evidence.model_dump_json()
    linked = root / 'gf_20990101-000000_a9a9a9'
    start(linked, fake_agent())
    target = linked / 'RF-02' / 'trace.json'
    target.unlink()
    target.symlink_to(tmp_path / 'secret.json')
    assert code(lambda: svc.get_run(linked.name)) == (404, 'EVALUATION_RUN_NOT_FOUND')
    assert code(lambda: svc.get_evidence(linked.name, 'RF-02', 'trace')) == (404, 'EVALUATION_RUN_NOT_FOUND')


def test_conflicts_unreadable_and_not_found(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    other, other_entry = golden_root(tmp_path, 'golden-copy')
    for parent in (root, other):
        start(parent / 'gf_20990101-000000_b1b1b1', fake_agent())
    broken = root / 'gf_20990101-000000_b2b2b2'
    broken.mkdir()
    (broken / 'summary.json').write_text('{')
    svc = service(entry, other_entry)
    assert code(lambda: svc.get_run('gf_20990101-000000_b1b1b1')) == (409, 'EVALUATION_RUN_ID_CONFLICT')
    assert code(lambda: svc.get_run(broken.name)) == (409, 'EVALUATION_RUN_UNREADABLE')
    assert code(lambda: svc.get_run('gf_20990101-000000_ffffff')) == (404, 'EVALUATION_RUN_NOT_FOUND')
    single = service(entry)
    start(root / 'gf_20990101-000000_b3b3b3', fake_agent())
    assert code(lambda: single.get_case('gf_20990101-000000_b3b3b3', 'RF-99')) == (404, 'EVALUATION_CASE_NOT_FOUND')
    assert code(lambda: single.get_dataset('missing-set')) == (404, 'EVALUATION_DATASET_NOT_FOUND')


def test_dataset_detail_relations_and_hash_conflict(tmp_path, no_sqlite):
    root, entry = golden_root(tmp_path)
    start(root / 'gf_20990101-000000_c1c1c1', fake_agent())
    legacy = root / 'gf_20990101-000000_c2c2c2'
    legacy.mkdir()
    (legacy / 'summary.json').write_text(json.dumps({
        'run_id': legacy.name, 'started_at': '2026-01-01T00:00:00+00:00', 'golden_sha256': '0' * 64,
        'cases': [{'case_id': 'RF-01', 'verdict': {'status': 'passed'}, 'execution_status': 'success'}]}))
    svc = service(entry)
    detail = svc.get_dataset('requirement-fidelity-golden-v1')
    DatasetDetail.model_validate(detail.model_dump())
    assert detail.dataset_version is None and detail.freeze_status == 'UNDECLARED' and detail.dataset_hash == _sha(GOLD_PATH)
    relations = {r.run_id: r.relation for r in detail.related_runs}
    assert relations == {'gf_20990101-000000_c1c1c1': 'hash_match', legacy.name: 'hash_mismatch'}
    variants = {v.dataset_hash: (v.matches_current_source, v.run_count) for v in detail.hash_variants}
    assert variants == {_sha(GOLD_PATH): (True, 1), '0' * 64: (False, 1)}
    listed = svc.list_datasets(page=1, page_size=20, dataset_type=None, sort='dataset_id').items[0]
    assert (listed.related_run_count, listed.hash_matched_run_count, listed.hash_mismatch_run_count) == (1, 1, 1)
    changed = tmp_path / 'golden-changed.json'
    document = json.loads(GOLD_PATH.read_text())
    document['cases'] = document['cases'][:2]
    changed.write_text(json.dumps(document, ensure_ascii=False))
    conflicted = service(entry, sources=[DatasetSource('golden', GOLD_PATH, GOLDEN_REF, 'golden'),
                                         DatasetSource('golden', changed, 'fixtures/golden-changed.json', 'golden')])
    status, error = code(lambda: conflicted.get_dataset('requirement-fidelity-golden-v1'))
    assert (status, error) == (409, 'EVALUATION_DATASET_ID_CONFLICT')
    page = conflicted.list_datasets(page=1, page_size=20, dataset_type=None, sort='dataset_id')
    assert page.total == 0 and any(w.code == 'duplicate_dataset_id' for w in page.discovery_warnings)


def test_http_routes_auth_validation_and_b1_lists(tmp_path):
    golden = tmp_path / 'golden'
    golden.mkdir()
    run_dir = golden / 'gf_20990101-000000_d1d1d1'
    start(run_dir, leaky_agent())
    app = create_app(Settings(tmp_path / 'data', admin_read_token='read', evaluation_golden_runs=golden,
                              evaluation_tc_runs=tmp_path / 'no-tc', evaluation_golden_dataset=GOLD_PATH,
                              evaluation_tc_dataset=TC_CASES))
    base = '/api/v1/admin/evaluations'
    with TestClient(app) as client:
        assert client.get(f'{base}/runs/{run_dir.name}').status_code == 403
        detail = client.get(f'{base}/runs/{run_dir.name}', headers=AUTH)
        assert detail.status_code == 200 and detail.headers['cache-control'] == 'no-store'
        RunDetail.model_validate(detail.json())
        assert client.get(f'/admin/evaluations/runs/{run_dir.name}', headers=AUTH).json() == detail.json()
        case = client.get(f'{base}/runs/{run_dir.name}/cases/RF-02', headers=AUTH)
        CaseDetail.model_validate(case.json())
        evidence = client.get(f'{base}/runs/{run_dir.name}/cases/RF-02/evidence', headers=AUTH, params={'kind': 'trace'})
        EvidenceView.model_validate(evidence.json())
        assert 'example-provider.com' not in evidence.text and str(tmp_path) not in evidence.text
        dataset = client.get(f'{base}/datasets/requirement-fidelity-golden-v1', headers=AUTH)
        DatasetDetail.model_validate(dataset.json())
        too_large = client.get(f'{base}/runs/{run_dir.name}/cases/RF-05/evidence', headers=AUTH, params={'kind': 'trace'})
        assert too_large.status_code == 413 and too_large.json()['error']['code'] == 'EVIDENCE_TOO_LARGE'
        for url, params in ((f'{base}/runs/not-a-run', None), (f'{base}/runs/{run_dir.name}/cases/RF..01', None),
                            (f'{base}/runs/{run_dir.name}/cases/RF-01/evidence', {'kind': 'sqlite'}),
                            (f'{base}/runs/{run_dir.name}/cases/RF-01/evidence', None),
                            (f'{base}/datasets/bad%20id', None), (f'{base}/runs', {'page_size': 0})):
            response = client.get(url, headers=AUTH, params=params)
            assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR', url
        assert client.get(f'{base}/runs/{run_dir.name}/cases/..%2F..%2Fetc/evidence', headers=AUTH, params={'kind': 'trace'}).status_code in (404, 422)
        assert client.get(f'{base}/runs/gf_20990101-000000_ffffff', headers=AUTH).status_code == 404
        assert client.get(f'{base}/datasets/unknown-set', headers=AUTH).status_code == 404
        runs = client.get(f'{base}/runs', headers=AUTH)
        datasets = client.get(f'{base}/datasets', headers=AUTH)
        RunListPage.model_validate(runs.json())
        DatasetListPage.model_validate(datasets.json())
        assert runs.json()['items'][0]['run_id'] == run_dir.name
        assert runs.json() == client.get('/admin/evaluations/runs', headers=AUTH).json()
        assert client.get('/admin/runs', headers=AUTH).status_code == 200
        assert client.get('/api/v1/admin/regression-runs', headers=AUTH).status_code == 200


def test_historical_runs_through_every_endpoint_are_unchanged(no_sqlite):
    before = (_snapshot(HISTORICAL_GOLDEN), _snapshot(HISTORICAL_TC), _sha(GOLD_PATH), _sha(TC_CASES))
    svc = build_evaluation_admin(
        [EvaluationRoot('golden', HISTORICAL_GOLDEN, 'golden'), EvaluationRoot('tc', HISTORICAL_TC, 'tc_regression')],
        [DatasetSource('golden', GOLD_PATH, GOLDEN_REF, 'golden'), DatasetSource('tc', TC_CASES, TC_REF, 'tc')], GOLD_PATH)
    golden = svc.get_run(HIST_GOLDEN_RUN)
    assert golden.provenance == 'legacy_projection' and golden.integrity.status == 'UNVERIFIED' and not golden.integrity.trusted
    assert golden.metrics.trust == 'unverified' and golden.metrics.trusted is False
    assert golden.evaluator_manifest is None and golden.evaluator_manifest_notice
    assert 'agent_version' in golden.unverified_fields
    states = {c.case_id: (c.execution_status, c.e2e_verdict, c.attribution.value) for c in golden.cases}
    assert states == {'RF-01': ('BLOCKED', 'FAIL', 'agent_execution'), 'RF-02': ('COMPLETED', 'PASS', 'none'),
                      'RF-03': ('BLOCKED', 'FAIL', 'agent_execution'), 'RF-04': ('FAILED', 'FAIL', 'agent_execution'),
                      'RF-05': ('COMPLETED', 'PASS', 'none')}
    rf01 = svc.get_case(HIST_GOLDEN_RUN, 'RF-01')
    oracle = rf01.evaluators[0]
    assert (oracle.role, oracle.verdict, oracle.evaluator_version, oracle.provenance) == ('legacy_oracle', 'NOT_EVALUATED', None, 'legacy_projection')
    assert rf01.legacy_labels['verdict']['failure'] == 'F-GOAL-SUBSTITUTED' and oracle.failure_code is None
    assert rf01.slots['must_forbid'].state == 'not_recorded' and rf01.slots['node_fidelity'].state == 'not_recorded'
    assert rf01.final_output.available is False
    assert rf01.case_integrity == 'UNVERIFIED' and rf01.e2e.trusted is False
    assert {c.case_integrity for c in golden.cases} == {'UNVERIFIED'}
    for case_id in ('RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05'):
        svc.get_case(HIST_GOLDEN_RUN, case_id)
        for kind in ('trace', 'plan', 'profile', 'engine', 'result_tables', 'evaluator_refs'):
            item = svc.get_evidence(HIST_GOLDEN_RUN, case_id, kind)
            text = item.model_dump_json()
            assert 'aliyuncs' not in text and 'http://' not in text and 'https://' not in text and str(REPO) not in text
            if kind in ('plan', 'profile', 'engine', 'result_tables'):
                assert item.status == 'NOT_RECORDED'
    trace = svc.get_evidence(HIST_GOLDEN_RUN, 'RF-02', 'trace')
    assert trace.status == 'AVAILABLE' and trace.integrity.status == 'unverified' and trace.integrity.trusted is False
    assert any(r['rule'] == 'endpoint_removed' for r in trace.redactions)
    assert any(r['rule'] == 'user_text_minimized' for r in trace.redactions)
    tc = svc.get_run(HIST_TC_RUN)
    assert tc.integrity.status == 'UNVERIFIED' and tc.case_counts.present == 1 and tc.case_counts.not_started == 14
    tc02 = svc.get_case(HIST_TC_RUN, 'TC02')
    assert {name: slot.state for name, slot in tc02.slots.items()} == {name: 'not_applicable' for name in ('oracle', 'must_forbid', 'node_fidelity')}
    assert tc02.evaluators[0].role == 'tc_checks'
    assert svc.get_evidence(HIST_TC_RUN, 'TC02', 'trace').status == 'UNAVAILABLE'
    assert svc.get_evidence(HIST_TC_RUN, 'TC02', 'plan').status == 'AVAILABLE'
    assert svc.get_case(HIST_TC_RUN, 'TC05').case_state == 'not_started'
    dataset = svc.get_dataset('typical-suite-v1')
    assert dataset.freeze_status == 'UNDECLARED' and [r.relation for r in dataset.related_runs] == ['hash_match']
    assert svc.get_dataset('requirement-fidelity-golden-v1').dataset_version is None
    after = (_snapshot(HISTORICAL_GOLDEN), _snapshot(HISTORICAL_TC), _sha(GOLD_PATH), _sha(TC_CASES))
    assert after == before
