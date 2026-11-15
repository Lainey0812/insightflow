"""Call the B2 and B1 evaluation endpoints over HTTP against the historical roots and save the responses.

Run from backend/: ../.venv/bin/python ../docs/evaluations/evaluation-admin-b2-2026-11-13/collect_responses.py
The app uses a temporary data directory. Historical directories are snapshotted before and after.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[2]
GOLDEN_RUNS = REPO / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs'
TC_RUNS = REPO.parent / 'var/regression/runs'
GOLDEN_SET = REPO / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'
TC_CASES = REPO / 'docs/testing/typical-suite-v1-2026-11-09/cases.json'
BASE = '/api/v1/admin/evaluations'
REQUESTS = {
    'run-detail-gf_20261112-143406_cde1fd.json': f'{BASE}/runs/gf_20261112-143406_cde1fd',
    'run-detail-rg_20261112-133157_f04289.json': f'{BASE}/runs/rg_20261112-133157_f04289',
    'case-detail-gf_143406-RF-01.json': f'{BASE}/runs/gf_20261112-143406_cde1fd/cases/RF-01',
    'case-detail-rg-TC02.json': f'{BASE}/runs/rg_20261112-133157_f04289/cases/TC02',
    'evidence-gf_143406-RF-02-trace.json': f'{BASE}/runs/gf_20261112-143406_cde1fd/cases/RF-02/evidence?kind=trace',
    'evidence-gf_143406-RF-02-plan.json': f'{BASE}/runs/gf_20261112-143406_cde1fd/cases/RF-02/evidence?kind=plan',
    'evidence-rg-TC02-trace.json': f'{BASE}/runs/rg_20261112-133157_f04289/cases/TC02/evidence?kind=trace',
    'evidence-rg-TC02-plan.json': f'{BASE}/runs/rg_20261112-133157_f04289/cases/TC02/evidence?kind=plan',
    'dataset-detail-golden.json': f'{BASE}/datasets/requirement-fidelity-golden-v1',
    'dataset-detail-tc.json': f'{BASE}/datasets/typical-suite-v1',
    'error-404-run.json': f'{BASE}/runs/gf_20991212-000000_aaaaaa',
    'error-404-case.json': f'{BASE}/runs/gf_20261112-143406_cde1fd/cases/RF-99',
    'error-422-kind.json': f'{BASE}/runs/gf_20261112-143406_cde1fd/cases/RF-02/evidence?kind=sqlite',
    'b1-runs.json': f'{BASE}/runs?sort=run_id',
    'b1-datasets.json': f'{BASE}/datasets',
}


def snapshot(root: Path):
    rows = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(directory) / name
            stat = os.lstat(path)
            digest = None if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size, digest))
    return rows


def state():
    return (snapshot(GOLDEN_RUNS), snapshot(TC_RUNS), hashlib.sha256(GOLDEN_SET.read_bytes()).hexdigest(),
            hashlib.sha256(TC_CASES.read_bytes()).hexdigest())


def main():
    before = state()
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(Path(tmp) / 'data', admin_read_token='read', evaluation_golden_runs=GOLDEN_RUNS,
                                  evaluation_tc_runs=TC_RUNS, evaluation_golden_dataset=GOLDEN_SET, evaluation_tc_dataset=TC_CASES))
        with TestClient(app) as client:
            for name, url in REQUESTS.items():
                response = client.get(url, headers={'X-Admin-Token': 'read'})
                for forbidden in (str(REPO), '/Users/', 'aliyuncs'):
                    assert forbidden not in response.text, (name, forbidden)
                body = response.json()
                if name == 'evidence-gf_143406-RF-02-trace.json' and response.status_code == 200:
                    # The redacted trace is 170 KB; the archive keeps its top-level keys only.
                    body = {**body, 'content': {'archived_keys_only': sorted(body['content'])}}
                (OUT / name).write_text(json.dumps({'request': url, 'status': response.status_code, 'body': body},
                                                   ensure_ascii=False, indent=2) + '\n')
                lines.append(f'{response.status_code} {url}')
    after = state()
    wal = [row[0] for row in before[0] + before[1] if row[0].endswith(('-wal', '-shm'))]
    (OUT / 'history-check.txt').write_text(
        'B2 and B1 endpoints called over HTTP against the historical roots.\n' + '\n'.join(lines) + '\n\n'
        f'golden run files {len(before[0])}, tc run files {len(before[1])}\n'
        f'path, mtime_ns, size, sha256 equal before/after: {before == after}\n'
        f'pre-existing wal/shm files (unchanged, none added): {len(wal)}\n'
        f'golden-set.json sha256 {before[2]}\ncases.json sha256 {before[3]}\n'
        'No response contains the repository path, /Users/, or the provider host.\n')
    assert before == after
    print((OUT / 'history-check.txt').read_text())


if __name__ == '__main__':
    main()
