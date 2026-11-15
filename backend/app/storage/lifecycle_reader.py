"""Snapshot reader with no initialization, recovery, schema migration or write path."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from app.domain.errors import AppError

@dataclass
class LifecycleSnapshot:
    session: dict | None = None
    profiles: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    executions: list[dict] = field(default_factory=list)
    generations: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    spans: list[dict] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    missing_tables: set[str] = field(default_factory=set)
    business_available: bool = True
    trace_available: bool = True
    trace_invalid: bool = False
    revision_rechecked: bool = False
    changed: bool = False

@contextmanager
def readonly(path: Path):
    # mode=ro refuses absent databases; query_only prevents accidental mutations.
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        yield conn
    finally:
        conn.close()

class LifecycleReader:
    def __init__(self, business_path: Path, trace_path: Path):
        self.business_path, self.trace_path = business_path, trace_path

    def read(self, session_id: str, *, business_only: bool = False) -> LifecycleSnapshot:
        snap = LifecycleSnapshot()
        try:
            with readonly(self.business_path) as conn:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                expected = {'sessions','dataset_profiles','datasets','plan_versions','plan_approvals',
                            'executions','report_generations','analysis_reports'}
                snap.missing_tables = expected - tables
                if 'sessions' not in tables:
                    snap.business_available = False
                    return snap
                row = conn.execute('SELECT state FROM sessions WHERE id=?', (session_id,)).fetchone()
                if row is None:
                    raise AppError('SESSION_NOT_FOUND','会话不存在。',404)
                snap.session = json.loads(row['state'])
                def records(table, condition, args):
                    if table not in tables:
                        return []
                    return [dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE {condition}', args)]
                def bound_records(table, keys):
                    result=[]
                    for row in records(table,'session_id=?',(session_id,)):
                        item=json.loads(row['record'])
                        if any(row[key]!=item.get(key) for key in keys):
                            raise ValueError('Stored index and record disagree')
                        result.append(item)
                    return result
                snap.plans = bound_records('plan_versions',('session_id','plan_id','plan_version'))
                snap.approvals = bound_records('plan_approvals',('session_id','approval_id'))
                snap.executions = records('executions','session_id=?',(session_id,))
                for r in snap.executions:
                    for key in ('request','approval','result'):
                        r[key] = json.loads(r[key]) if r[key] else None
                    r.pop('progress', None)  # task contents are not part of this projection
                snap.generations = bound_records('report_generations',('execution_id','session_id','status'))
                ref = snap.session.get('dataset_ref') or {}
                if ref:
                    snap.profiles = [json.loads(r['profile']) for r in records('dataset_profiles',
                        'dataset_id=? AND dataset_version=?',(ref.get('dataset_id'),ref.get('dataset_version')))]
                    snap.files = [json.loads(r['file_info']) for r in records('datasets','id=?',(ref.get('dataset_id'),))]
                # Only metadata, never report prose, evidence values or result rows.
                if 'analysis_reports' in tables:
                    for generation in snap.generations:
                        if not generation.get('report_id'):
                            continue
                        row = conn.execute('''SELECT id, audit,
                            json_extract(report,'$.report_id') AS report_id,
                            json_extract(report,'$.execution_id') AS execution_id,
                            json_extract(report,'$.dataset_id') AS dataset_id,
                            json_extract(report,'$.dataset_version') AS dataset_version,
                            json_extract(report,'$.plan_version') AS plan_version,
                            json_extract(report,'$.execution_source') AS execution_source,
                            json_extract(report,'$.report_status') AS report_status,
                            json_extract(report,'$.goal_coverage') AS goal_coverage
                            FROM analysis_reports WHERE id=?''',(generation['report_id'],)).fetchone()
                        if row:
                            item = dict(row)
                            item['audit'] = json.loads(item['audit'])
                            snap.reports.append(item)
        except AppError:
            raise
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            snap.business_available = False
            return snap
        if business_only:
            snap.trace_available = False
            return snap
        try:
            with readonly(self.trace_path) as conn:
                for row in conn.execute("SELECT id, record FROM trace_runs WHERE json_extract(record,'$.session_id')=?",(session_id,)):
                    record=json.loads(row['record'])
                    if record.get('run_id')!=row['id']:
                        raise ValueError('Trace identity disagrees with stored index')
                    snap.runs.append(record)
                for run in snap.runs:
                    snap.spans.extend(json.loads(r[0]) for r in conn.execute(
                        'SELECT record FROM trace_spans WHERE run_id=?',(run['run_id'],)))
                    snap.event_counts[run['run_id']] = conn.execute(
                        'SELECT COUNT(*) FROM trace_events WHERE run_id=?',(run['run_id'],)).fetchone()[0]
        except (ValueError, TypeError, KeyError):
            snap.trace_invalid = True
            snap.trace_available = False
            snap.runs, snap.spans, snap.event_counts = [], [], {}
        except sqlite3.Error:
            snap.trace_available = False
            snap.runs, snap.spans, snap.event_counts = [], [], {}
        # Cross-database reads are NOT atomic. Detect a business change during collection.
        try:
            with readonly(self.business_path) as conn:
                row = conn.execute('SELECT state FROM sessions WHERE id=?',(session_id,)).fetchone()
                snap.revision_rechecked = True
                snap.changed = row is None or json.loads(row[0]) != snap.session
        except (sqlite3.Error, ValueError, TypeError):
            snap.changed = True
        return snap
