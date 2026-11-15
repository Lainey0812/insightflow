CREATE INDEX llm_calls_run ON llm_calls(run_id);

CREATE INDEX llm_calls_span ON llm_calls(span_id);

CREATE TABLE llm_calls (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, sequence INTEGER NOT NULL,
 run_id TEXT, span_id TEXT, status TEXT NOT NULL, record TEXT NOT NULL,
 request_id TEXT NOT NULL UNIQUE REFERENCES llm_request_snapshots(id), UNIQUE(operation_id,sequence));

CREATE TABLE llm_request_payloads (
 snapshot_id TEXT PRIMARY KEY REFERENCES llm_request_snapshots(id), payload TEXT NOT NULL, expires_at TEXT);

CREATE TABLE llm_request_snapshots (
 id TEXT PRIMARY KEY, template_id TEXT NOT NULL REFERENCES prompt_templates(id), record TEXT NOT NULL);

CREATE TABLE prompt_templates (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL, version TEXT NOT NULL,
 content_hash TEXT NOT NULL, record TEXT NOT NULL, UNIQUE(node_id,version));

CREATE TABLE registry_migrations (version INTEGER PRIMARY KEY);

CREATE TRIGGER calls_no_delete BEFORE DELETE ON llm_calls BEGIN SELECT RAISE(ABORT,'Preserve calls'); END;

CREATE TRIGGER calls_terminal BEFORE UPDATE ON llm_calls WHEN OLD.status != 'running' BEGIN SELECT RAISE(ABORT,'Terminal call'); END;

CREATE TRIGGER payload_no_update BEFORE UPDATE ON llm_request_payloads BEGIN SELECT RAISE(ABORT,'Immutable payload'); END;

CREATE TRIGGER requests_no_delete BEFORE DELETE ON llm_request_snapshots BEGIN SELECT RAISE(ABORT,'Immutable request'); END;

CREATE TRIGGER requests_no_update BEFORE UPDATE ON llm_request_snapshots BEGIN SELECT RAISE(ABORT,'Immutable request'); END;

CREATE TRIGGER templates_no_delete BEFORE DELETE ON prompt_templates BEGIN SELECT RAISE(ABORT,'Immutable template'); END;

CREATE TRIGGER templates_no_update BEFORE UPDATE ON prompt_templates BEGIN SELECT RAISE(ABORT,'Immutable template'); END;
