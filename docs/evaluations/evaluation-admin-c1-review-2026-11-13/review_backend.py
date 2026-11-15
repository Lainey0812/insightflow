"""Phase 2-C1 review harness (REQ-0154). Scripted agents only; no model calls.

Builds scenario runs in a scratch directory, then either dumps real B1/B2 HTTP responses
or serves a separate backend instance for the Admin dev server. Historical runs are only read.

Usage (from insightflow/backend):
  ../.venv/bin/python ../docs/evaluations/evaluation-admin-c1-review-2026-11-13/review_backend.py dump
  ../.venv/bin/python ../docs/evaluations/evaluation-admin-c1-review-2026-11-13/review_backend.py serve 8011 [conflict]
"""
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / 'backend'
sys.path[:0] = [str(BACKEND), str(BACKEND / 'tests')]

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator  # noqa: E402
from app.evaluation.golden_fidelity import GOLD_PATH, load_golden  # noqa: E402
from app.evaluation.golden_run import run_golden  # noqa: E402
from app.main import create_app  # noqa: E402
from test_evaluation_contracts import NOW, Boom, fake_agent, start  # noqa: E402
from test_evaluation_discovery import TC_CASES  # noqa: E402
from test_evaluation_quality_gates import rf04_agent  # noqa: E402

SCRATCH = Path('/tmp/c1-review')
GOLDEN = SCRATCH / 'golden'
TC_RUNS = BACKEND.parents[1] / 'var/regression/runs'
CONFLICT_TC = SCRATCH / 'tc-conflict-cases.json'
OUT = Path(__file__).resolve().parent / 'responses'
RUNS = {
    'verified': 'gf_20990101-000000_a1a1a1', 'invalid': 'gf_20990101-000000_a2a2a2', 'incomplete': 'gf_20990101-000000_a3a3a3',
    'empty': 'gf_20990101-000000_a4a4a4', 'evaluator_error': 'gf_20990101-000000_a5a5a5', 'rf04_pending': 'gf_20990101-000000_a6a6a6',
    'invalid_all': 'gf_20990101-000000_a7a7a7', 'legacy_mismatch': 'gf_20990101-000000_c2c2c2',
}
TC_RUN = 'rg_20261112-133157_f04289'
AUTH = {'X-Admin-Token': 'review-read'}


def edit_json(path, change):
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record, ensure_ascii=False))


def build():
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    GOLDEN.mkdir(parents=True)
    start(GOLDEN / RUNS['verified'], fake_agent())
    start(GOLDEN / RUNS['invalid'], fake_agent())
    edit_json(GOLDEN / RUNS['invalid'] / 'RF-02' / 'result.json', lambda r: r['e2e'].update(verdict='FAIL'))
    for name, fail_at in (('incomplete', 'RF-03'), ('empty', 'RF-01')):
        try:
            start(GOLDEN / RUNS[name], fake_agent(fail_at=fail_at))
        except RuntimeError:
            pass
    run_golden(GOLDEN / RUNS['evaluator_error'], load_golden(), GOLD_PATH.read_bytes(), 'golden-set.json', run_one=fake_agent(),
               model={'name': 'scripted'}, environment={'source_fingerprint': 'review'}, clock=NOW,
               evaluators=[(GoldenOracleEvaluator(), 'required'), (Boom(), 'required'), (RequirementFidelityNodeEvaluator(), 'optional')])
    start(GOLDEN / RUNS['rf04_pending'], rf04_agent())
    start(GOLDEN / RUNS['invalid_all'], fake_agent())
    for case in ('RF-01', 'RF-02', 'RF-03', 'RF-04', 'RF-05'):
        edit_json(GOLDEN / RUNS['invalid_all'] / case / 'result.json', lambda r: r['e2e'].update(reason='tampered'))
    legacy = GOLDEN / RUNS['legacy_mismatch']
    legacy.mkdir()
    (legacy / 'summary.json').write_text(json.dumps({
        'run_id': legacy.name, 'started_at': '2026-01-01T00:00:00+00:00', 'golden_sha256': '0' * 64,
        'cases': [{'case_id': 'RF-01', 'verdict': {'status': 'passed'}, 'execution_status': 'success'}]}))
    for i in range(16):
        start(GOLDEN / f'gf_20990102-0000{i:02d}_b{i:05x}', fake_agent())
    document = json.loads(TC_CASES.read_text())
    document['suite_version'] = 'requirement-fidelity-golden-v1'
    CONFLICT_TC.write_text(json.dumps(document, ensure_ascii=False))


def app(conflict=False, local=False):
    access = {'admin_local_test_mode': True} if local else {'admin_read_token': 'review-read'}
    return create_app(Settings(SCRATCH / 'data', **access, evaluation_golden_runs=GOLDEN,
                               evaluation_tc_runs=TC_RUNS, evaluation_golden_dataset=GOLD_PATH,
                               evaluation_tc_dataset=CONFLICT_TC if conflict else TC_CASES))


def dump():
    build()
    OUT.mkdir(exist_ok=True)
    base = '/api/v1/admin/evaluations'
    requests = {'runs-page-1': f'{base}/runs', 'runs-page-2': f'{base}/runs?page=2', 'runs-tc-filter': f'{base}/runs?run_type=tc_regression',
                'datasets-page': f'{base}/datasets', 'dataset-golden': f'{base}/datasets/requirement-fidelity-golden-v1',
                'dataset-tc': f'{base}/datasets/typical-suite-v1', f'run-{TC_RUN}': f'{base}/runs/{TC_RUN}'}
    requests.update({f'run-{name}': f'{base}/runs/{run_id}' for name, run_id in RUNS.items()})
    with TestClient(app(), headers=AUTH) as client:
        for label, url in requests.items():
            response = client.get(url)
            (OUT / f'{label}.json').write_text(json.dumps({'request': url, 'status': response.status_code, 'body': response.json()},
                                                          ensure_ascii=False, indent=2) + '\n')
    with TestClient(app(conflict=True), headers=AUTH) as client:
        for label, url in {'conflict-dataset-detail': f'{base}/datasets/requirement-fidelity-golden-v1',
                           'conflict-datasets-page': f'{base}/datasets'}.items():
            response = client.get(url)
            (OUT / f'{label}.json').write_text(json.dumps({'request': url, 'status': response.status_code, 'body': response.json()},
                                                          ensure_ascii=False, indent=2) + '\n')
    text = ''.join(p.read_text() for p in OUT.glob('*.json'))
    assert '/Users/' not in text and str(SCRATCH) not in text, 'host path in response'
    print(f'{len(list(OUT.glob("*.json")))} responses written')


def serve(port, conflict=False):
    import uvicorn
    if not GOLDEN.exists():
        build()
    uvicorn.run(app(conflict, local=True), host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    if sys.argv[1] == 'dump':
        dump()
    else:
        serve(int(sys.argv[2]), conflict=len(sys.argv) > 3 and sys.argv[3] == 'conflict')
