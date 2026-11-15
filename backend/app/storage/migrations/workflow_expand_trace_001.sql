CREATE TABLE workflow_expand_migrations (
    version TEXT NOT NULL PRIMARY KEY, database_kind TEXT NOT NULL,
    checksum TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TRIGGER workflow_expand_version_no_update BEFORE UPDATE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Immutable expand migration'); END;
CREATE TRIGGER workflow_expand_version_no_delete BEFORE DELETE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Preserve expand migration'); END;
CREATE TABLE trace_workflow_links (
    run_id TEXT NOT NULL PRIMARY KEY REFERENCES trace_runs(id), workflow_id TEXT NOT NULL,
    session_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('workflow','report_generation')),
    evidence TEXT NOT NULL CHECK(json_valid(evidence)), registered_at TEXT NOT NULL
);
CREATE UNIQUE INDEX expand_workflow_root_identity ON trace_workflow_links(workflow_id) WHERE kind='workflow';
CREATE INDEX expand_trace_workflow_lookup ON trace_workflow_links(workflow_id, kind);
CREATE TRIGGER trace_workflow_source_guard BEFORE INSERT ON trace_workflow_links
WHEN NOT EXISTS (SELECT 1 FROM trace_runs r WHERE r.id=NEW.run_id
    AND json_extract(r.record,'$.session_id') IS NEW.session_id
    AND COALESCE(json_extract(r.record,'$.kind'),'report_generation') IS NEW.kind)
    OR EXISTS (SELECT 1 FROM trace_workflow_links l WHERE l.workflow_id=NEW.workflow_id AND l.session_id<>NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'Trace workflow ownership conflict'); END;
CREATE TRIGGER trace_workflow_no_update BEFORE UPDATE ON trace_workflow_links
BEGIN SELECT RAISE(ABORT, 'Immutable trace workflow binding'); END;
CREATE TRIGGER trace_workflow_no_delete BEFORE DELETE ON trace_workflow_links
BEGIN SELECT RAISE(ABORT, 'Preserve trace workflow binding'); END;
