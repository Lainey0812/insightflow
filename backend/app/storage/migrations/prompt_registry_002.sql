CREATE TABLE IF NOT EXISTS llm_response_payloads (
 call_id TEXT PRIMARY KEY REFERENCES llm_calls(id),
 kind TEXT NOT NULL CHECK (kind IN ('content','raw_body')),
 content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 truncated INTEGER NOT NULL CHECK (truncated IN (0,1)), expires_at TEXT);
CREATE TRIGGER IF NOT EXISTS response_payload_no_update BEFORE UPDATE ON llm_response_payloads BEGIN SELECT RAISE(ABORT,'Immutable response'); END;
INSERT OR IGNORE INTO registry_migrations VALUES (2);
