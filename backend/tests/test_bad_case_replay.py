"""Bad Case replay: read the original file without writing it back, and do not store the query."""
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.observability.provenance import digest
from app.regression.runner import write_new
from app.replay.judge import judge
from app.replay.runner import replay, summarize
from app.replay.source import load_cases, prepare
from app.storage.bad_cases import BadCaseRepository
from test_bad_cases import WRITE, body
from test_report_workflow import Provider, QUERY, run
from test_trace_closure_c2 import AUTH, http_provider


def test_judge_compares_saved_failure_and_leaves_expected_text_alone():
    frozen = {'failure_code': 'REPORT_NO_VALID_INSIGHTS', 'attention': ['insight_rejected'], 'business_status': 'failed'}
    assert judge(frozen, {'failure': {'code': 'REPORT_NO_VALID_INSIGHTS'}})[0] == 'recurred'
    assert judge(frozen, {'failure': None, 'quality': {'signals': []}})[0] == 'cleared'
    assert judge(frozen, {'error_code': 'LLM_TIMEOUT'})[0] == 'blocked'
    assert judge(frozen, {'failure': {'code': 'REPORT_UNVERIFIED_FACT'}})[0] == 'changed'
    assert judge({'failure_code': None, 'attention': ['insight_rejected'], 'business_status': 'succeeded'},
                 {'quality': {'signals': [{'key': 'insight_rejected', 'level': 'attention'}]}, 'business_status': 'succeeded'})[0] == 'recurred'
    cleared, reason = judge({'failure_code': None, 'attention': ['insight_rejected'], 'business_status': 'succeeded'},
                            {'quality': {'signals': [{'key': 'insight_rejected', 'level': 'normal'}]}, 'business_status': 'succeeded'})
    assert cleared == 'cleared' and '期望' not in reason
    assert judge({'failure_code': None, 'attention': [], 'business_status': 'succeeded'},
                 {'business_status': 'succeeded', 'quality': {'signals': []}})[0] == 'unchanged'


def _case(case_id, evidence, status='open'):
    return {'schema_version': 'bad-case-v1', 'case_id': case_id, 'created_at': 't', 'workflow_id': 'wf_daily', 'title': '结论不符',
            'category': 'insight', 'severity': 'high', 'observed': '报告称华东增长最快', 'expected': '应指出华南更高',
            'evidence': evidence, 'evidence_sha256': digest(evidence)}, {'status': status}


def _store(path, *pairs):
    repo = BadCaseRepository(path / 'bad_cases')
    for case, latest in pairs:
        repo.create(case, {'event_id': 'bce_' + case['case_id'][3:], 'case_id': case['case_id'], 'sequence': 1,
                           'created_at': 't', 'kind': 'created', 'status': latest['status'], 'note': '', 'annotator': 'a'})


def test_missing_session_changed_file_and_closed_case_are_not_replayed(tmp_path):
    file_id = 'ab' * 16
    content = b'city,n\nA,1\n'
    info = {'id': file_id, 'name': 'secret.csv', 'size': len(content), 'extension': '.csv',
            'content_sha256': hashlib.sha256(content).hexdigest()}
    evidence = {'business_lifecycle': {'status': 'failed'}, 'failure': {'code': 'REPORT_NO_VALID_INSIGHTS'},
                'quality': {'signals': []}, 'replay_refs': {'session_id': 'sess_1', 'dataset_id': file_id, 'dataset_version': 'dv1'}}
    case, latest = _case('bc_' + 'cd' * 16, evidence)
    _store(tmp_path, (case, latest), _case('bc_' + 'ef' * 16, evidence, 'fixed'))
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (uploads / f'{file_id}.csv').write_bytes(content)
    state = {'id': 'sess_1', 'data_source': 'uploaded', 'workflow_kind': 'real_v1', 'user_goal': '秘密目标取前三名',
             'file': info, 'profile_options': {'header_row': 2}, 'clarification_answers': ['只要已完成']}
    db = tmp_path / 'insightflow.sqlite3'
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, state TEXT NOT NULL)')
        conn.execute('INSERT INTO sessions VALUES (?,?,?)', ('sess_1', 't', json.dumps(state)))

    found = {item['case_id']: item for item, _ in load_cases(tmp_path)}
    assert prepare(tmp_path, found['bc_' + 'cd' * 16], {'status': 'open'}, forced=False)['source']['header_row'] == 2
    gone = prepare(tmp_path / 'empty', found['bc_' + 'cd' * 16], {'status': 'open'}, forced=False)
    assert gone['outcome'] == 'source_missing' and '原会话' in gone['reason']
    (uploads / f'{file_id}.csv').write_bytes(b'city,n\nA,9\n')
    changed = prepare(tmp_path, found['bc_' + 'cd' * 16], {'status': 'open'}, forced=False)
    assert changed['outcome'] == 'source_missing' and '已改变' in changed['reason']
    skipped = prepare(tmp_path, found['bc_' + 'ef' * 16], {'status': 'fixed'}, forced=False)
    assert skipped['outcome'] == 'not_run' and '已修复' in skipped['reason']
    assert '秘密目标' not in json.dumps(skipped, ensure_ascii=False)


def _fingerprint(root: Path):
    names = ['insightflow.sqlite3', 'insightflow.sqlite3-wal', 'insightflow.sqlite3-shm', 'bad_cases/bad_cases.sqlite3']
    paths = [root / name for name in names]
    if (root / 'uploads').is_dir():
        paths.extend(sorted((root / 'uploads').iterdir()))
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}


def test_replay_keeps_the_daily_database_and_omits_the_query(tmp_path):
    provider, _ = http_provider(Provider())
    app = create_app(Settings(tmp_path, admin_read_token='read', admin_annotation_token='note'), provider)
    with TestClient(app) as client:
        _, _, session = run(client)
        created = client.post('/admin/bad-cases', headers=WRITE, json=body(session['workflow_id'])).json()
    before = _fingerprint(tmp_path)
    stored = {case['case_id']: (case, latest) for case, latest in load_cases(tmp_path)}
    prepared = [prepare(tmp_path, *stored[created['case_id']], forced=False)]
    assert prepared[0]['source']['goal'] == QUERY
    replay_app = create_app(Settings(tmp_path / 'isolated'), http_provider(Provider())[0])
    with TestClient(replay_app) as client:
        results = replay(client, replay_app, prepared, 'rp_test')
    assert _fingerprint(tmp_path) == before
    result = results[0]
    assert result['outcome'] in {'recurred', 'unchanged', 'cleared', 'changed'}
    assert result['workflow_id'] and result['workflow_id'] != session['workflow_id']
    assert result['approved_by_runner'] is True
    dumped = json.dumps(result, ensure_ascii=False)
    assert '取前三名' not in dumped and '21250' not in dumped and 'secret' not in dumped
    assert result['expected'] == '应指出华南增长最快。' and result['source_ref']['file_sha256']
    assert summarize(results)['auto_total'] == 1


def test_admin_lists_finished_and_incomplete_replays_read_only(tmp_path):
    runs = tmp_path / 'replay' / 'runs'
    finished = runs / 'rp_20261110-010000_aaaaaa'
    (finished / 'cases').mkdir(parents=True)
    case = {'case_id': 'bc_' + 'ab' * 16, 'title': '结论不符', 'outcome': 'cleared', 'reason': '原错误代码已不在。',
            'expected': '应指出华南更高', 'observed': '报告称增长最快', 'original_workflow_id': 'wf_daily',
            'workflow_id': 'wf_isolated', 'annotation_status': 'open', 'duration_ms': 12, 'llm': {'calls': 4}}
    start = {'schema_version': 'replay-run-v1', 'run_id': finished.name, 'label': '修校验后', 'started_at': 't',
             'environment': {'model': 'qwen'}, 'source_fingerprint': 'f' * 64, 'selected_cases': [case['case_id']]}
    write_new(finished / 'run.json', {**start, 'finished_at': 'u', 'summary': summarize([case]), 'cases': [case]})
    partial = runs / 'rp_20261110-020000_bbbbbb'
    (partial / 'cases').mkdir(parents=True)
    write_new(partial / 'run-start.json', {**start, 'run_id': partial.name, 'label': '进行中'})
    write_new(partial / 'cases' / (case['case_id'] + '.json'), {**case, 'outcome': 'recurred'})
    (runs / '..evil').mkdir()
    (finished / 'cases-extra-ignored.json').write_text('{}')
    app = create_app(Settings(tmp_path, admin_read_token='read'))
    with TestClient(app) as client:
        page = client.get('/admin/replay-runs', headers=AUTH).json()
        assert [item['run_id'] for item in page['items']] == [partial.name, finished.name]
        assert [item['state'] for item in page['items']] == ['incomplete', 'finished']
        assert page['items'][0]['summary']['counts'] == {'recurred': 1}
        detail = client.get('/admin/replay-runs/' + finished.name, headers=AUTH).json()
        assert detail['cases'][0]['outcome'] == 'cleared' and detail['cases'][0]['workflow_id'] == 'wf_isolated'
        assert client.get('/admin/replay-runs/..evil', headers=AUTH).status_code == 404
        assert client.get('/admin/replay-runs/rp_20261110-030000_cccccc', headers=AUTH).status_code == 404
        assert client.post('/admin/replay-runs', headers=AUTH).status_code == 405
        assert client.get('/admin/replay-runs').status_code == 403
