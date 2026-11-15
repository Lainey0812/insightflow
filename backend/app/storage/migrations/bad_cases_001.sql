CREATE TABLE IF NOT EXISTS bad_case_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bad_cases (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bad_cases_workflow ON bad_cases(workflow_id);
CREATE TABLE IF NOT EXISTS bad_case_events (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES bad_cases(id),
  sequence INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  record TEXT NOT NULL,
  UNIQUE(case_id, sequence)
);
CREATE TRIGGER IF NOT EXISTS bad_cases_no_update BEFORE UPDATE ON bad_cases BEGIN SELECT RAISE(ABORT,'Bad cases are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bad_cases_no_delete BEFORE DELETE ON bad_cases BEGIN SELECT RAISE(ABORT,'Bad cases are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bad_case_events_no_update BEFORE UPDATE ON bad_case_events BEGIN SELECT RAISE(ABORT,'Bad case events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bad_case_events_no_delete BEFORE DELETE ON bad_case_events BEGIN SELECT RAISE(ABORT,'Bad case events are append-only'); END;
INSERT OR IGNORE INTO bad_case_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
