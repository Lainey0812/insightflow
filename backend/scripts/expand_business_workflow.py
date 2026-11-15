"""Explicit Phase 02-A maintenance command; no business Workflow creation."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.storage.workflow_expand import KINDS, ExpandError, apply_expand, inspect_expand, connect

DATABASES = {'business': 'insightflow.sqlite3', 'trace': 'observability/trace.sqlite3',
             'registry': 'prompt_registry/registry.sqlite3'}


def active_work(data_dir):
    counts = {}
    with closing(connect(data_dir / DATABASES['business'], readonly=True)) as c:
        counts['sessions'] = c.execute("""SELECT COUNT(*) FROM sessions WHERE
            json_extract(state,'$.status') IN ('CREATED','PREPARING','PROFILING','PARSING_INTENT','PLANNING','VALIDATING','RUNNING')
            OR json_extract(state,'$.review_status') IN ('validating','executing')""").fetchone()[0]
        counts['executions'] = c.execute("SELECT COUNT(*) FROM executions WHERE status='running'").fetchone()[0]
        counts['reports'] = c.execute("SELECT COUNT(*) FROM report_generations WHERE status IN ('queued','generating')").fetchone()[0]
    with closing(connect(data_dir / DATABASES['trace'], readonly=True)) as c:
        counts['trace_runs'] = c.execute("SELECT COUNT(*) FROM trace_runs WHERE status IN ('queued','running')").fetchone()[0]
    with closing(connect(data_dir / DATABASES['registry'], readonly=True)) as c:
        counts['llm_calls'] = c.execute("SELECT COUNT(*) FROM llm_calls WHERE status='running'").fetchone()[0]
    return counts


def backup_database(source, destination):
    """SQLite's backup API includes committed WAL pages; never copy live files."""
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(connect(source, readonly=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        dst.execute('PRAGMA foreign_keys=ON')
        if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or dst.execute('PRAGMA foreign_key_check').fetchone():
            raise ExpandError('EXPAND_BACKUP_INVALID', 'Backup validation failed; migration was not started')
    return {'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'verified': True}


def run(data_dir, *, apply=False, backup_dir=None, maintenance=False, kinds=KINDS):
    result = {'phase': '02-A Expand only', 'backfill': False, 'switch': False, 'databases': {}, 'backups': {}}
    for kind in kinds:
        result['databases'][kind] = inspect_expand(data_dir / DATABASES[kind], kind)
    if not apply:
        return result
    if not maintenance or backup_dir is None:
        raise ExpandError('EXPAND_MAINTENANCE_REQUIRED', 'Stop all writers and confirm a maintenance window plus backup directory')
    counts = active_work(data_dir)
    result['active_work'] = counts
    if any(counts.values()):
        raise ExpandError('EXPAND_ACTIVE_WORK', 'Active or unclosed work requires review before maintenance')
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    # All selected backups precede the first DDL commit. The caller must have
    # stopped all writers; this command does not claim a cross-file transaction.
    for kind in kinds:
        result['backups'][kind] = backup_database(data_dir / DATABASES[kind], backup_dir / f'{kind}.sqlite3')
    for kind in kinds:
        try:
            result['databases'][kind] = apply_expand(data_dir / DATABASES[kind], kind)
        except Exception as exc:
            result['databases'][kind] = {'status': 'failed', 'code': getattr(exc, 'code', type(exc).__name__)}
            result['complete'] = False
            break
    else:
        result['complete'] = True
    (backup_dir / 'maintenance-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (backup_dir / 'maintenance-result.json').chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--maintenance-window-confirmed', action='store_true')
    parser.add_argument('--kind', choices=KINDS, action='append')
    args = parser.parse_args()
    try:
        result = run(args.data_dir.resolve(), apply=args.apply, backup_dir=args.backup_dir,
                     maintenance=args.maintenance_window_confirmed, kinds=args.kind or KINDS)
    except Exception as exc:
        print(json.dumps({'complete': False, 'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('complete', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
