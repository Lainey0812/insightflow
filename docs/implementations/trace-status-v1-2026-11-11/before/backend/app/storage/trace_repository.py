"""Existing SQLite sidecar: observations and controlled projections, never authoritative business records."""
from contextlib import closing
from pathlib import Path
import sqlite3
import json
from app.domain.tracing import TraceRun, TraceSpan, TraceEvent, TraceSnapshot
from app.domain.models import now

class TraceRepository:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'trace.sqlite3'
        with closing(self.connect()) as conn, conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS trace_runs (
                    id TEXT PRIMARY KEY, execution_id TEXT, attempt INTEGER NOT NULL,
                    queued_at TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL,
                    UNIQUE(execution_id, attempt));
                CREATE TABLE IF NOT EXISTS trace_spans (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id), record TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS spans_run ON trace_spans(run_id);
                CREATE TABLE IF NOT EXISTS trace_events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id),
                    span_id TEXT REFERENCES trace_spans(id), sequence INTEGER NOT NULL, record TEXT NOT NULL,
                    UNIQUE(run_id, sequence));
                CREATE INDEX IF NOT EXISTS events_span ON trace_events(span_id, sequence);
                CREATE TABLE IF NOT EXISTS trace_snapshots (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id),
                    span_id TEXT REFERENCES trace_spans(id), kind TEXT NOT NULL, record TEXT NOT NULL,
                    UNIQUE(run_id,kind));
            ''')
            from .trace_migrations import migrate_workflow_roots
            migrate_workflow_roots(conn)
        self.path.chmod(0o600)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=0.025)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def attempt(self, execution_id, attempt):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT record FROM trace_runs WHERE execution_id=? AND attempt=?', (execution_id,attempt)).fetchone()
        return TraceRun.model_validate_json(row['record']) if row else None

    def create(self, run):
        run = TraceRun.model_validate(run.model_dump())
        with closing(self.connect()) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO trace_runs VALUES (?, ?, ?, ?, ?, ?)',
                (run.run_id,run.execution_id,run.attempt,run.queued_at,run.status,run.model_dump_json()))
        return self.workflow(run.session_id) if run.kind == 'workflow' else self.attempt(run.execution_id,run.attempt)

    def create_registered_root(self, run, identity):
        """Exact reserved ID only; never resolve a different Root through Session."""
        if (run.run_id, run.session_id, run.manifest.bindings.get('workflow_id')) != (identity.root_run_id, identity.session_id, identity.workflow_id):
            raise ValueError('Reserved Root identity mismatch')
        from .workflow_expand import apply_expand
        apply_expand(self.path, 'trace')
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM trace_runs WHERE id=?', (identity.root_run_id,)).fetchone()
            if row:
                stored = TraceRun.model_validate_json(row['record'])
                if (stored.kind != 'workflow' or stored.session_id != identity.session_id or
                    stored.manifest.bindings.get('workflow_id') != identity.workflow_id):
                    raise ValueError('Registered Root identity mismatch')
            else:
                # The preserved legacy Session unique index rejects competing physical Roots.
                conn.execute('INSERT INTO trace_runs VALUES (?,?,?,?,?,?)',
                    (run.run_id,None,run.attempt,run.queued_at,run.status,run.model_dump_json()))
                stored = run
            link = conn.execute('SELECT * FROM trace_workflow_links WHERE run_id=?', (identity.root_run_id,)).fetchone()
            if link:
                if (link['workflow_id'],link['session_id'],link['kind']) != (identity.workflow_id,identity.session_id,'workflow'):
                    raise ValueError('Registered Root link mismatch')
            else:
                conn.execute('INSERT INTO trace_workflow_links VALUES (?,?,?,?,?,?)',
                    (identity.root_run_id,identity.workflow_id,identity.session_id,'workflow',
                     json.dumps({'source':'business_workflows','root_run_id':identity.root_run_id}),now()))
            return stored

    def workflow(self, session_id):
        with closing(self.connect()) as conn:
            row=conn.execute("SELECT record FROM trace_runs WHERE json_extract(record,'$.kind')='workflow' AND json_extract(record,'$.session_id')=?",(session_id,)).fetchone()
        return TraceRun.model_validate_json(row['record']) if row else None

    def update_run(self, run):
        with closing(self.connect()) as conn, conn:
            # Read, compare and write under one lock. The JSON token also fences
            # separate callbacks which carry the same business revision.
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT record FROM trace_runs WHERE id=?',(run.run_id,)).fetchone()
            if row is None: raise ValueError('Trace run missing')
            previous=TraceRun.model_validate_json(row['record'])
            if previous.manifest != run.manifest: raise ValueError('Manifest is immutable')
            if any(getattr(run,key)!=getattr(previous,key) for key in
                   ('kind','session_id','execution_id','attempt','retry_of_run_id','owner_instance','queued_at','workflow_run_id')):
                raise ValueError('Run identity is immutable')
            if run.observation_revision != previous.observation_revision:
                return False
            if previous.kind == 'workflow':
                if run.kind != 'workflow' or run.status not in {'queued','running','waiting_input','waiting_approval','failed','interrupted'}:
                    raise ValueError('Unsupported preparation root transition')
                if (previous.business_revision is not None
                        and (run.business_revision is None or run.business_revision < previous.business_revision)): return False
                allowed_root = {
                    'queued': {'running', 'interrupted'},
                    'running': {'running', 'waiting_input', 'waiting_approval', 'failed', 'interrupted'},
                    'waiting_input': {'running'}, 'waiting_approval': set(),
                    'failed': {'running'}, 'interrupted': {'running'},
                }
                if run.status not in allowed_root.get(previous.status, set()):
                    return False
                if previous.status in {'waiting_input','failed','interrupted'} and (
                        run.business_revision is None or
                        run.business_revision <= (previous.business_revision if previous.business_revision is not None else -1)):
                    return False
                if previous.integrity == 'incomplete': run.integrity = 'incomplete'
            elif previous.status not in {'queued','running'}: return False
            allowed={'queued':{'queued','running','interrupted'},
                     'running':{'running','complete','partial','failed','unavailable','interrupted'}}
            if previous.kind != 'workflow' and run.status not in allowed[previous.status]: raise ValueError('Invalid observation transition')
            saved = run.model_copy(update={'observation_revision': previous.observation_revision + 1})
            conn.execute('UPDATE trace_runs SET status=?,record=? WHERE id=?',(saved.status,saved.model_dump_json(),saved.run_id))
        # Advance the caller's token only after a successful database commit.
        run.observation_revision = saved.observation_revision
        return True

    def reserve_workflow_span(self, span):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            run=conn.execute('SELECT record FROM trace_runs WHERE id=?',(span.run_id,)).fetchone()
            if not run or json.loads(run['record']).get('kind')!='workflow' or not span.node_key:
                raise ValueError('Workflow span requires a real root and node key')
            if span.parent_span_id:
                parent=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(span.parent_span_id,)).fetchone()
                if not parent or parent['run_id'] != span.run_id: raise ValueError('Cross-run parent')
            attempt=conn.execute("SELECT COALESCE(MAX(json_extract(record,'$.node_attempt')),0)+1 FROM trace_spans WHERE run_id=? AND json_extract(record,'$.node_key')=?",(span.run_id,span.node_key)).fetchone()[0]
            span.node_attempt=attempt
            conn.execute('INSERT INTO trace_spans VALUES (?,?,?)',(span.span_id,span.run_id,span.model_dump_json()))
        return span

    def save_span(self, span):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if span.parent_span_id:
                parent=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(span.parent_span_id,)).fetchone()
                if not parent or parent['run_id']!=span.run_id: raise ValueError('Cross-run parent')
            previous=conn.execute('SELECT run_id,record FROM trace_spans WHERE id=?',(span.span_id,)).fetchone()
            if previous and (previous['run_id'] != span.run_id or TraceSpan.model_validate_json(previous['record']).status != 'running'):
                raise ValueError('Span is immutable after completion')
            if previous:
                old = TraceSpan.model_validate_json(previous['record'])
                if any(getattr(old,k) != getattr(span,k) for k in ('name','parent_span_id','node_key','node_attempt')):
                    raise ValueError('Span identity is immutable')
            conn.execute('INSERT INTO trace_spans VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                         (span.span_id,span.run_id,span.model_dump_json()))
        return True

    def event(self, event):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if event.span_id:
                row=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(event.span_id,)).fetchone()
                if not row or row['run_id']!=event.run_id: raise ValueError('Cross-run event')
            existing=conn.execute('SELECT record FROM trace_events WHERE id=?',(event.event_id,)).fetchone()
            if existing:
                if existing['record'] != event.model_dump_json(): raise ValueError('Conflicting event identity')
                return
            run=conn.execute('SELECT record FROM trace_runs WHERE id=?',(event.run_id,)).fetchone()
            if run and json.loads(run['record']).get('kind') == 'workflow':
                sequence=conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM trace_events WHERE run_id=?',(event.run_id,)).fetchone()[0]
                if sequence > 256: raise ValueError('Workflow event limit reached')
                event.sequence=sequence
            conn.execute('INSERT INTO trace_events VALUES (?,?,?,?,?)',
                (event.event_id,event.run_id,event.span_id,event.sequence,event.model_dump_json()))

    def get(self, run_id):
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT record FROM trace_runs WHERE id=?',(run_id,)).fetchone()
        return TraceRun.model_validate_json(row['record']) if row else None

    def span(self, span_id):
        with closing(self.connect()) as conn:
            row=conn.execute('SELECT record FROM trace_spans WHERE id=?',(span_id,)).fetchone()
        return TraceSpan.model_validate_json(row['record']) if row else None

    def runs(self, limit=50, offset=0, status=None, *, from_time=None, to_time=None, node=None, version=None, kind=None):
        clauses,args=[],[]
        if kind:
            clauses.append("COALESCE(json_extract(r.record,'$.kind'),'report_generation')=?");args.append(kind)
        if status:
            clauses.append('r.status=?');args.append(status)
        if from_time:
            clauses.append('julianday(r.queued_at)>=julianday(?)');args.append(from_time)
        if to_time:
            clauses.append('julianday(r.queued_at)<=julianday(?)');args.append(to_time)
        if node:
            clauses.append("EXISTS (SELECT 1 FROM trace_spans s WHERE s.run_id=r.id AND json_extract(s.record,'$.name')=?)")
            args.append(node)
        if version:
            keys=['prompt_version','generation_version','schema_version','validation_version','registry_version']
            clauses.append('('+' OR '.join("json_extract(r.record,'$.manifest.versions."+key+"')=?" for key in keys)+')')
            args.extend([version]*len(keys))
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        with closing(self.connect()) as conn:
            conn.execute('BEGIN')  # count and page refer to the same read snapshot
            total=conn.execute('SELECT COUNT(*) FROM trace_runs r'+where,args).fetchone()[0]
            rows=conn.execute('SELECT r.record FROM trace_runs r'+where+' ORDER BY r.queued_at DESC,r.id DESC LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
        return [TraceRun.model_validate_json(row['record']) for row in rows],total

    def related_reports(self, root_run_id):
        with closing(self.connect()) as conn:
            rows=conn.execute("SELECT record FROM trace_runs WHERE json_extract(record,'$.kind')='report_generation' AND json_extract(record,'$.workflow_run_id')=? ORDER BY queued_at,id",(root_run_id,)).fetchall()
        return [TraceRun.model_validate_json(r['record']) for r in rows]

    def spans(self, run_id):
        with closing(self.connect()) as conn:
            rows=conn.execute('SELECT record FROM trace_spans WHERE run_id=? ORDER BY rowid',(run_id,)).fetchall()
            if not rows:
                # Compatibility projection: preserve actual Span IDs and owning Root IDs.
                source=conn.execute('SELECT record FROM trace_runs WHERE id=?',(run_id,)).fetchone()
                run=TraceRun.model_validate_json(source['record']) if source else None
                if run and run.kind=='report_generation' and run.manifest.bindings.get('workflow_id'):
                    rows=conn.execute("SELECT record FROM trace_spans WHERE run_id=? AND json_extract(record,'$.attributes.execution_id')=? AND json_extract(record,'$.attributes.report_attempt')=? ORDER BY rowid",
                        (run.workflow_run_id,run.execution_id,run.attempt)).fetchall()
        return [TraceSpan.model_validate_json(r['record']) for r in rows]

    def events(self, span_id, limit=100, offset=0):
        with closing(self.connect()) as conn:
            rows=conn.execute('SELECT record FROM trace_events WHERE span_id=? ORDER BY sequence LIMIT ? OFFSET ?',
                             (span_id,limit,offset)).fetchall()
        return [TraceEvent.model_validate_json(r['record']) for r in rows]

    def mark_collection_gap(self,root_run_id):
        # Integrity is monotone. update_run already preserves incomplete under its CAS transaction.
        # No lifecycle field or CAS token is changed by this narrow atomic metadata write.
        with closing(self.connect()) as conn,conn:
            conn.execute("UPDATE trace_runs SET record=json_set(record,'$.integrity','incomplete') WHERE id=? AND json_extract(record,'$.kind')='workflow'",(root_run_id,))

    def recover(self):
        # Same single-process deployment boundary as the business recovery code.
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in conn.execute("SELECT record FROM trace_runs WHERE status IN ('queued','running')").fetchall():
                run=TraceRun.model_validate_json(row['record'])
                run.status,run.error_code,run.integrity='interrupted','TRACE_PROCESS_INTERRUPTED','incomplete'
                run.observation_revision += 1
                run.recovered_at=now()
                run.duration_ms=None
                conn.execute('UPDATE trace_runs SET status=?,record=? WHERE id=?',(run.status,run.model_dump_json(),run.run_id))
                for spanrow in conn.execute('SELECT record FROM trace_spans WHERE run_id=?',(run.run_id,)).fetchall():
                    span=TraceSpan.model_validate_json(spanrow['record'])
                    if span.status=='running':
                        span.status,span.error_code='interrupted','TRACE_PROCESS_INTERRUPTED'
                        span.recovered_at=run.recovered_at
                        span.duration_ms=None
                        conn.execute('UPDATE trace_spans SET record=? WHERE id=?',(span.model_dump_json(),span.span_id))

            for row in conn.execute("SELECT id,record FROM trace_spans WHERE json_extract(record,'$.status')='running'").fetchall():
                span=TraceSpan.model_validate_json(row['record'])
                span.status,span.error_code='interrupted','TRACE_PROCESS_INTERRUPTED'
                span.recovered_at=now()
                span.duration_ms=None
                conn.execute('UPDATE trace_spans SET record=? WHERE id=?',(span.model_dump_json(),span.span_id))
                conn.execute("UPDATE trace_runs SET record=json_set(record,'$.integrity','incomplete') WHERE id=? AND json_extract(record,'$.kind')='workflow'",(span.run_id,))

    def save_snapshot(self, snapshot):
        if len(snapshot.model_dump_json().encode()) > 256*1024:
            raise ValueError('Controlled snapshot too large')
        with closing(self.connect()) as conn, conn:
            if snapshot.span_id:
                row=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(snapshot.span_id,)).fetchone()
                if not row or row['run_id'] != snapshot.run_id: raise ValueError('Cross-run snapshot')
            old=conn.execute('SELECT record FROM trace_snapshots WHERE run_id=? AND kind=?',
                             (snapshot.run_id,snapshot.kind)).fetchone()
            if old:
                if old['record'] != snapshot.model_dump_json(): raise ValueError('Snapshot is immutable')
                return
            conn.execute('INSERT INTO trace_snapshots VALUES (?,?,?,?,?)',
                (snapshot.snapshot_id,snapshot.run_id,snapshot.span_id,snapshot.kind,snapshot.model_dump_json()))

    def snapshots(self, run_id):
        with closing(self.connect()) as conn:
            rows=conn.execute('SELECT record FROM trace_snapshots WHERE run_id=? ORDER BY kind',(run_id,)).fetchall()
        return [TraceSnapshot.model_validate_json(r['record']) for r in rows]

    def run_events(self, run_id):
        with closing(self.connect()) as conn:
            rows=conn.execute('SELECT record FROM trace_events WHERE run_id=? ORDER BY sequence',(run_id,)).fetchall()
        return [TraceEvent.model_validate_json(r['record']) for r in rows]
