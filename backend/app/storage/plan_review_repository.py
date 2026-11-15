"""Append-only audit tables, committed atomically with the existing session."""
from contextlib import closing, contextmanager
from app.domain.errors import AppError
from app.domain.models import SessionState, now, record_status_event
from app.domain.plan_review import PlanVersion, ReviewApproval

class PlanReviewRepository:
    def __init__(self, database):
        self.database = database
        with closing(database.connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS plan_versions (
                session_id TEXT NOT NULL REFERENCES sessions(id), plan_id TEXT NOT NULL,
                plan_version INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(session_id, plan_version))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS plan_approvals (
                approval_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                request_id TEXT NOT NULL, request TEXT NOT NULL, record TEXT NOT NULL,
                UNIQUE(session_id, request_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS plan_constraint_audits (
                approval_id TEXT PRIMARY KEY REFERENCES plan_approvals(approval_id),
                session_id TEXT NOT NULL REFERENCES sessions(id), record TEXT NOT NULL)""")
            from app.review.analysis_basis import initialize
            initialize(conn)
            for table in ("plan_versions", "plan_approvals", "plan_constraint_audits"):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                        BEFORE {operation} ON {table} BEGIN
                        SELECT RAISE(ABORT, 'immutable HITL audit record'); END""")

    @contextmanager
    def transaction(self, session_id):
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise AppError("SESSION_NOT_FOUND", "会话不存在。", 404)
            state = SessionState.model_validate_json(row["state"])
            before = state.model_dump_json()
            previous = state.status
            yield conn, state
            record_status_event(state, previous)
            if state.model_dump_json() != before:
                state.revision += 1
                state.updated_at = now()
                conn.execute("UPDATE sessions SET state=?, updated_at=? WHERE id=?",
                             (state.model_dump_json(), state.updated_at, session_id))

    def versions(self, session_id):
        with closing(self.database.connect()) as conn:
            return [PlanVersion.model_validate_json(r["record"]) for r in conn.execute(
                "SELECT record FROM plan_versions WHERE session_id=? ORDER BY plan_version", (session_id,))]

    def approvals(self, session_id):
        with closing(self.database.connect()) as conn:
            return [ReviewApproval.model_validate_json(r["record"]) for r in conn.execute(
                "SELECT record FROM plan_approvals WHERE session_id=? ORDER BY rowid", (session_id,))]

    def constraint_audits(self, session_id):
        import json
        with closing(self.database.connect()) as conn:
            return [json.loads(r['record']) for r in conn.execute(
                'SELECT record FROM plan_constraint_audits WHERE session_id=? ORDER BY rowid', (session_id,))]

    @staticmethod
    def append_version(conn, record):
        conn.execute("INSERT INTO plan_versions VALUES (?, ?, ?, ?)",
                     (record.session_id, record.plan_id, record.plan_version, record.model_dump_json()))

        from app.review.analysis_basis import register
        register(conn, record)
