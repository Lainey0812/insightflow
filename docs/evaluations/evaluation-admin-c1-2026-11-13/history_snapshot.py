"""Snapshot path, size, mtime and SHA-256 of the historical evaluation runs and datasets.

Usage (from the insightflow directory): python3 docs/evaluations/evaluation-admin-c1-2026-11-13/history_snapshot.py OUT.json
Paths in the output are relative to the workspace root so no host path is recorded.
"""
import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
WORKSPACE = PROJECT.parent
TARGETS = [
    PROJECT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs',
    PROJECT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json',
    PROJECT / 'docs/testing/typical-suite-v1-2026-11-09/cases.json',
    WORKSPACE / 'var/regression/runs/rg_20261112-133157_f04289',
]


def files():
    for target in TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from sorted(p for p in target.rglob('*') if p.is_file() and not p.is_symlink())


def main(out: str) -> None:
    rows = {}
    for path in files():
        stat = path.stat()
        rows[str(path.relative_to(WORKSPACE))] = {
            'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    Path(out).write_text(json.dumps(rows, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'{len(rows)} files -> {Path(out).name}')


if __name__ == '__main__':
    main(sys.argv[1])
