CREATE INDEX events_span ON trace_events(span_id, sequence);

CREATE INDEX spans_run ON trace_spans(run_id);

CREATE UNIQUE INDEX workflow_session_unique
            ON trace_runs(json_extract(record,'$.session_id'))
            WHERE json_extract(record,'$.kind')='workflow' ;

CREATE TABLE trace_events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id),
                    span_id TEXT REFERENCES trace_spans(id), sequence INTEGER NOT NULL, record TEXT NOT NULL,
                    UNIQUE(run_id, sequence));

CREATE TABLE trace_migrations (version TEXT PRIMARY KEY);

CREATE TABLE "trace_runs" (
                id TEXT PRIMARY KEY, execution_id TEXT, attempt INTEGER NOT NULL,
                queued_at TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(execution_id, attempt));

CREATE TABLE trace_snapshots (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id),
                    span_id TEXT REFERENCES trace_spans(id), kind TEXT NOT NULL, record TEXT NOT NULL,
                    UNIQUE(run_id,kind));

CREATE TABLE trace_spans (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES trace_runs(id), record TEXT NOT NULL);
