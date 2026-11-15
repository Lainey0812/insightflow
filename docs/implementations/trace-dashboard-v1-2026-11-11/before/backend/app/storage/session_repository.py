from collections.abc import Callable
from contextlib import closing

from app.domain.errors import AppError
from app.domain.models import SessionState, now, record_status_event
from .database import Database


class SessionRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, state: SessionState) -> None:
        record_status_event(state, None)
        with closing(self.database.connect()) as conn, conn:
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                         (state.id, state.updated_at, state.model_dump_json()))

    def get(self, session_id: str) -> SessionState:
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise AppError("SESSION_NOT_FOUND", "会话不存在。", 404)
        return SessionState.model_validate_json(row["state"])

    def list(self) -> list[dict]:
        with closing(self.database.connect()) as conn:
            rows = conn.execute("SELECT state FROM sessions ORDER BY updated_at DESC").fetchall()
        return [SessionState.model_validate_json(row["state"]).model_dump(include={
            "id", "title", "status", "updated_at", "data_source"
        }) for row in rows]

    def mutate(self, session_id: str, change: Callable[[SessionState], None],
               expected_revision: int | None = None) -> SessionState:
        # Claim, validate, and persist under one SQLite write transaction.
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise AppError("SESSION_NOT_FOUND", "会话不存在。", 404)
            state = SessionState.model_validate_json(row["state"])
            if expected_revision is not None and state.revision != expected_revision:
                raise AppError("STALE_SESSION", "会话已更新，请刷新后重试。")
            previous = state.status
            change(state)
            record_status_event(state, previous)
            state.revision += 1
            state.updated_at = now()
            conn.execute("UPDATE sessions SET state = ?, updated_at = ? WHERE id = ?",
                         (state.model_dump_json(), state.updated_at, session_id))
            return state
