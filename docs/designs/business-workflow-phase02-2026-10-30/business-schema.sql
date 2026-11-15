CREATE TABLE analysis_reports (id TEXT PRIMARY KEY, report TEXT NOT NULL, audit TEXT NOT NULL);

CREATE TABLE dataset_profiles (
                dataset_id TEXT NOT NULL, dataset_version TEXT NOT NULL, profile TEXT NOT NULL,
                PRIMARY KEY (dataset_id, dataset_version),
                FOREIGN KEY (dataset_id) REFERENCES datasets(id)
            );

CREATE TABLE datasets (id TEXT PRIMARY KEY, file_info TEXT NOT NULL);

CREATE TABLE execution_results (
                id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id),
                row_count INTEGER NOT NULL, columns_json TEXT NOT NULL, rows_json TEXT NOT NULL
            );

CREATE TABLE executions (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id), status TEXT NOT NULL,
                started_at TEXT NOT NULL, approval TEXT NOT NULL, progress TEXT NOT NULL, result TEXT
            );

CREATE TABLE plan_approvals (
                approval_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                request_id TEXT NOT NULL, request TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(session_id, request_id));

CREATE TABLE plan_constraint_audits (
                approval_id TEXT PRIMARY KEY REFERENCES plan_approvals(approval_id),
                session_id TEXT NOT NULL REFERENCES sessions(id), record TEXT NOT NULL);

CREATE TABLE plan_versions (
                session_id TEXT NOT NULL REFERENCES sessions(id), plan_id TEXT NOT NULL,
                plan_version INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(session_id, plan_version));

CREATE TABLE report_generations (execution_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL);

CREATE TABLE session_access (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id), token_hash TEXT NOT NULL);

CREATE TABLE sessions (
                id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, state TEXT NOT NULL
            );

CREATE TRIGGER plan_approvals_no_delete
                        BEFORE DELETE ON plan_approvals BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;

CREATE TRIGGER plan_approvals_no_update
                        BEFORE UPDATE ON plan_approvals BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;

CREATE TRIGGER plan_constraint_audits_no_delete
                        BEFORE DELETE ON plan_constraint_audits BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;

CREATE TRIGGER plan_constraint_audits_no_update
                        BEFORE UPDATE ON plan_constraint_audits BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;

CREATE TRIGGER plan_versions_no_delete
                        BEFORE DELETE ON plan_versions BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;

CREATE TRIGGER plan_versions_no_update
                        BEFORE UPDATE ON plan_versions BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END;
