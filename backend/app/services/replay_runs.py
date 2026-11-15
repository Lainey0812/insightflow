"""Read-only view of Bad Case replays written by scripts/run_bad_case_replay.py. Never starts a replay."""
import json
import re
from pathlib import Path

from app.domain.errors import AppError
from app.replay.judge import NOTICE

RUN_ID = re.compile(r'^rp_\d{8}-\d{6}_[0-9a-f]{6}$')
CASE_FILE = re.compile(r'^bc_[0-9a-f]{32}\.json$')
SUMMARY_KEYS = ('run_id', 'label', 'started_at', 'finished_at', 'state', 'environment', 'source_fingerprint', 'summary', 'selected_cases')


class ReplayRunService:
    def __init__(self, directory: Path):
        self.directory = directory

    def _load(self, run_dir: Path):
        try:
            final = run_dir / 'run.json'
            if final.is_file():
                return {**json.loads(final.read_text()), 'state': 'finished'}
            start = json.loads((run_dir / 'run-start.json').read_text())
        except (OSError, ValueError):
            return None
        cases = []
        case_dir = run_dir / 'cases'
        if case_dir.is_dir():
            for path in sorted(case_dir.glob('bc_*.json')):
                if CASE_FILE.match(path.name):
                    try:
                        cases.append(json.loads(path.read_text()))
                    except ValueError:
                        continue
        from app.replay.runner import summarize
        return {**start, 'finished_at': None, 'state': 'incomplete', 'summary': summarize(cases), 'cases': cases}

    def list(self):
        items = []
        if self.directory.is_dir():
            for run_dir in sorted(self.directory.iterdir(), reverse=True):
                if run_dir.is_dir() and RUN_ID.match(run_dir.name):
                    run = self._load(run_dir)
                    if run:
                        items.append({k: run.get(k) for k in SUMMARY_KEYS})
        return {'schema_version': 'replay-run-page-v1', 'items': items, 'total': len(items), 'notice': NOTICE + ' 回放在独立目录，不写入日常库；页面不启动回放。'}

    def get(self, run_id: str):
        if not RUN_ID.match(run_id):
            raise AppError('REPLAY_RUN_NOT_FOUND', '回放运行不存在。', 404)
        run = self._load(self.directory / run_id)
        if run is None:
            raise AppError('REPLAY_RUN_NOT_FOUND', '回放运行不存在。', 404)
        return run
