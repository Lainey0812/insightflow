"""Snapshot every file under the historical run roots: relative path, size, mtime_ns and SHA-256.

Usage: history_snapshot.py OUT.json
Paths in the output are relative to each root; the roots are named by label only.
Files are read as plain bytes; no SQLite connection is opened.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = {
    'golden_runs': REPO / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs',
    'tc_regression_runs': REPO.parent / 'var/regression/runs',
    'golden_set': REPO / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12',
    'tc_suite': REPO / 'docs/testing/typical-suite-v1-2026-11-09',
}


def snapshot():
    result = {}
    for label, root in ROOTS.items():
        files = {}
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if label == 'golden_set' and Path(dirpath) == root:
                dirnames[:] = [d for d in dirnames if d != 'runs']
            for name in filenames:
                path = Path(dirpath) / name
                stat = os.lstat(path)
                files[path.relative_to(root).as_posix()] = {
                    'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        result[label] = dict(sorted(files.items()))
    return result


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
