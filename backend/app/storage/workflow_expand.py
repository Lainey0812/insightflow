"""Explicit Expand-only DDL. No startup hook, backfill or business writers."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import re
import sqlite3
from pathlib import Path

VERSION = 'phase02a-expand-001'
KINDS = ('business', 'trace', 'registry')
REQUIRED = {
    'business': {'sessions': ('id',), 'datasets': ('id',),
        'dataset_profiles': ('dataset_id', 'dataset_version'),
        'plan_versions': ('session_id', 'plan_version'), 'plan_approvals': ('approval_id',),
        'executions': ('id',), 'analysis_reports': ('id',)},
    'trace': {'trace_runs': ('id',), 'trace_spans': ('id',), 'trace_events': ('id',)},
    'registry': {'llm_calls': ('id',), 'llm_request_snapshots': ('id',), 'prompt_templates': ('id',)},
}


class ExpandError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def connect(path: Path, *, readonly=False):
    """Never silently create an empty database or initialize application tables."""
    conn = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                           uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        conn.close()
        raise ExpandError('EXPAND_FK_DISABLED', 'SQLite foreign keys must be enabled')
    if readonly:
        conn.execute('PRAGMA query_only=ON')
    return conn


def statements(text):
    buffer = ''
    for char in text:
        buffer += char
        if char == ';' and sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ''
    if re.sub(r'--[^\n]*', '', buffer).strip():
        raise ExpandError('EXPAND_SQL_INCOMPLETE', 'Incomplete migration statement')


def schema(conn):
    return {(r['type'], r['name'], r['tbl_name']): re.sub(r'\s+', ' ', r['sql'].strip()).rstrip(';')
            for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL")}


def specification(kind):
    if kind not in KINDS:
        raise ValueError('Unknown database kind')
    source = Path(__file__).with_name('migrations').joinpath(f'workflow_expand_{kind}_001.sql').read_text()
    with closing(sqlite3.connect(':memory:')) as reference:
        reference.row_factory = sqlite3.Row
        # Only stubs needed to compile new indexes; they are not migration DDL.
        if kind == 'business':
            reference.execute('CREATE TABLE plan_approvals(approval_id TEXT PRIMARY KEY, session_id TEXT)')
            reference.execute('CREATE TABLE executions(id TEXT PRIMARY KEY, session_id TEXT)')
        baseline = schema(reference)
        for statement in statements(source):
            reference.execute(statement)
        expected = {key: sql for key, sql in schema(reference).items() if key not in baseline}
    checksum = hashlib.sha256((VERSION + '\n' + kind + '\n' + source).encode()).hexdigest()
    return source, expected, checksum


def _prerequisites(conn, kind):
    for table, primary_key in REQUIRED[kind].items():
        columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        actual = tuple(r['name'] for r in sorted(columns, key=lambda r: r['pk']) if r['pk'])
        if actual != primary_key:
            raise ExpandError('EXPAND_BASELINE_MISMATCH', f'Missing or incompatible primary key: {table}')
    if kind == 'trace':
        indexes = {r['name']: r for r in conn.execute('PRAGMA index_list(trace_runs)')}
        index = indexes.get('workflow_session_unique')
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='workflow_session_unique'").fetchone()
        if not index or not index['unique'] or not index['partial'] or not sql or \
                "json_extract(record,'$.session_id')" not in re.sub(r'\s+', '', sql[0]) or \
                "json_extract(record,'$.kind')='workflow'" not in re.sub(r'\s+', '', sql[0]):
            raise ExpandError('EXPAND_ROOT_INDEX_REQUIRED', 'Existing Session unique Root index must remain')


def _state(conn, kind, expected, checksum):
    _prerequisites(conn, kind)
    existing = schema(conn)
    present = set(expected) & set(existing)
    owned_tables = {name for typ, name, _ in expected if typ == 'table'}
    if not present:
        return 'pending'
    if present != set(expected):
        raise ExpandError('EXPAND_PARTIAL_SCHEMA', 'Some Expand objects exist without a complete schema')
    if any(existing[key] != sql for key, sql in expected.items()) or any(
            key not in expected for key in existing if key[2] in owned_tables):
        raise ExpandError('EXPAND_SCHEMA_MISMATCH', 'Expand schema differs from the registered contract')
    versions = conn.execute('SELECT * FROM workflow_expand_migrations').fetchall()
    if not versions:
        raise ExpandError('EXPAND_PARTIAL_SCHEMA', 'Schema has no committed migration version')
    if len(versions) != 1 or versions[0]['version'] != VERSION:
        raise ExpandError('EXPAND_VERSION_MISMATCH', 'Unknown Expand migration version')
    if versions[0]['database_kind'] != kind or versions[0]['checksum'] != checksum:
        raise ExpandError('EXPAND_CHECKSUM_MISMATCH', 'Migration checksum or database identity differs')
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise ExpandError('EXPAND_FK_VIOLATION', 'Foreign key validation failed')
    return 'applied'


def inspect_expand(path: Path, kind):
    _, expected, checksum = specification(kind)
    with closing(connect(path, readonly=True)) as conn:
        conn.execute('BEGIN')
        state = _state(conn, kind, expected, checksum)
        return {'database_kind': kind, 'version': VERSION, 'status': state, 'checksum': checksum,
                'foreign_keys': 1, 'objects': len(expected)}


def apply_expand(path: Path, kind):
    source, expected, checksum = specification(kind)
    with closing(connect(path)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        before = schema(conn)
        if _state(conn, kind, expected, checksum) == 'applied':
            return {'database_kind': kind, 'version': VERSION, 'status': 'already_applied', 'checksum': checksum}
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ExpandError('EXPAND_FK_VIOLATION', 'Existing foreign key violations require review')
        # execute(), not executescript(): DDL and version row commit together.
        for statement in statements(source):
            conn.execute(statement)
        conn.execute('INSERT INTO workflow_expand_migrations VALUES (?,?,?,?)',
            (VERSION, kind, checksum, datetime.now(timezone.utc).isoformat()))
        after = schema(conn)
        if any(after.get(key) != value for key, value in before.items()):
            raise ExpandError('EXPAND_LEGACY_SCHEMA_CHANGED', 'A legacy schema object changed')
        _state(conn, kind, expected, checksum)
    return {'database_kind': kind, 'version': VERSION, 'status': 'applied', 'checksum': checksum}
