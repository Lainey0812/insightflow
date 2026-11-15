"""Append-only Bad Case store. Cases and status events are never updated or deleted."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3

from app.domain.errors import AppError


class BadCaseRepository:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'bad_cases.sqlite3'
        self.path.touch(mode=0o600, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            existing = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bad_case_migrations'").fetchone()
            if existing and any(row[0] != 1 for row in conn.execute('SELECT version FROM bad_case_migrations')):
                raise ValueError('Unsupported bad case migration version')
            conn.executescript(Path(__file__).with_name('migrations').joinpath('bad_cases_001.sql').read_text())

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def create(self, case: dict, event: dict):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO bad_cases VALUES (?,?,?,?,?)', (case['case_id'], case['workflow_id'], case['created_at'],
                case['evidence_sha256'], json.dumps(case, ensure_ascii=False, sort_keys=True)))
            self._append(conn, event)

    def append(self, event: dict, expected_sequence: int):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM bad_cases WHERE id=?', (event['case_id'],)).fetchone():
                raise AppError('BAD_CASE_NOT_FOUND', 'Bad Case 不存在。', 404)
            current = conn.execute('SELECT max(sequence) FROM bad_case_events WHERE case_id=?', (event['case_id'],)).fetchone()[0]
            if current != expected_sequence:
                raise AppError('BAD_CASE_STALE', '该 Bad Case 已被他人更新，请刷新后再提交。', 409, details={'current_sequence': current})
            self._append(conn, {**event, 'sequence': current + 1})

    @staticmethod
    def _append(conn, event):
        conn.execute('INSERT INTO bad_case_events VALUES (?,?,?,?,?)', (event['event_id'], event['case_id'], event['sequence'],
            event['created_at'], json.dumps(event, ensure_ascii=False, sort_keys=True)))

    def get(self, case_id: str):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT record FROM bad_cases WHERE id=?', (case_id,)).fetchone()
            if not row:
                return None
            events = [json.loads(r['record']) for r in conn.execute(
                'SELECT record FROM bad_case_events WHERE case_id=? ORDER BY sequence', (case_id,))]
        return json.loads(row['record']), events

    def all(self, workflow_id: str | None = None):
        sql = ('SELECT c.record, e.record AS latest FROM bad_cases c JOIN bad_case_events e ON e.case_id=c.id '
               'AND e.sequence=(SELECT max(sequence) FROM bad_case_events WHERE case_id=c.id)')
        args = []
        if workflow_id:
            sql += ' WHERE c.workflow_id=?'
            args.append(workflow_id)
        with closing(self.connect()) as conn:
            rows = conn.execute(sql + ' ORDER BY c.created_at DESC, c.id ASC', args).fetchall()
        return [(json.loads(r['record']), json.loads(r['latest'])) for r in rows]
