"""Compatible V0.3.1 migration; preserve report rows, manifests and child records."""


def migrate_workflow_roots(conn):
    required = next(row for row in conn.execute('PRAGMA table_info(trace_runs)') if row['name'] == 'execution_id')['notnull']
    if required:
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''CREATE TABLE trace_runs_v031 (
                id TEXT PRIMARY KEY, execution_id TEXT, attempt INTEGER NOT NULL,
                queued_at TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(execution_id, attempt))''')
            conn.execute('INSERT INTO trace_runs_v031 SELECT * FROM trace_runs')
            conn.execute('DROP TABLE trace_runs')
            conn.execute('ALTER TABLE trace_runs_v031 RENAME TO trace_runs')
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Trace migration foreign key check failed')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute('PRAGMA foreign_keys=ON')
    with conn:
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS workflow_session_unique
            ON trace_runs(json_extract(record,'$.session_id'))
            WHERE json_extract(record,'$.kind')='workflow' ''')
        conn.execute('CREATE TABLE IF NOT EXISTS trace_migrations (version TEXT PRIMARY KEY)')
        conn.execute("INSERT OR IGNORE INTO trace_migrations VALUES ('0.3.1')")
