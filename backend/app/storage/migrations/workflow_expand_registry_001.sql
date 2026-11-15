CREATE TABLE workflow_expand_migrations (
    version TEXT NOT NULL PRIMARY KEY, database_kind TEXT NOT NULL,
    checksum TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE TRIGGER workflow_expand_version_no_update BEFORE UPDATE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Immutable expand migration'); END;
CREATE TRIGGER workflow_expand_version_no_delete BEFORE DELETE ON workflow_expand_migrations
BEGIN SELECT RAISE(ABORT, 'Preserve expand migration'); END;
CREATE TABLE llm_call_workflow_links (
    call_id TEXT NOT NULL PRIMARY KEY REFERENCES llm_calls(id), workflow_id TEXT NOT NULL,
    session_id TEXT NOT NULL, run_id TEXT, span_id TEXT, root_run_id TEXT,
    evidence TEXT NOT NULL CHECK(json_valid(evidence)), registered_at TEXT NOT NULL,
    CHECK(span_id IS NULL OR run_id IS NOT NULL)
);
CREATE INDEX expand_call_workflow_lookup ON llm_call_workflow_links(workflow_id, call_id);
CREATE TRIGGER call_workflow_source_guard BEFORE INSERT ON llm_call_workflow_links
WHEN NOT EXISTS (SELECT 1 FROM llm_calls c WHERE c.id=NEW.call_id
    AND c.run_id IS NEW.run_id AND c.span_id IS NEW.span_id)
    OR EXISTS (SELECT 1 FROM llm_call_workflow_links l WHERE l.workflow_id=NEW.workflow_id AND l.session_id<>NEW.session_id)
BEGIN SELECT RAISE(ABORT, 'LLM call workflow ownership conflict'); END;
CREATE TRIGGER call_workflow_no_update BEFORE UPDATE ON llm_call_workflow_links
BEGIN SELECT RAISE(ABORT, 'Immutable call workflow binding'); END;
CREATE TRIGGER call_workflow_no_delete BEFORE DELETE ON llm_call_workflow_links
BEGIN SELECT RAISE(ABORT, 'Preserve call workflow binding'); END;
