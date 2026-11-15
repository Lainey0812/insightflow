import sqlite3
from contextlib import closing
from pathlib import Path


class Database:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "insightflow.sqlite3"
        with closing(self.connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, state TEXT NOT NULL
            )""")

            conn.execute("""CREATE TABLE IF NOT EXISTS session_access (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id), token_hash TEXT NOT NULL)""")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
