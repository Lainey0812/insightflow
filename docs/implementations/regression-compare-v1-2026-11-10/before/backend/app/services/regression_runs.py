"""Read-only view of regression runs written by scripts/run_regression.py. Never starts a run or reads the run's databases."""
import json
import re
from pathlib import Path

from app.domain.errors import AppError

RUN_ID = re.compile(r'^rg_\d{8}-\d{6}_[0-9a-f]{6}$')
CASE_FILE = re.compile(r'^TC\d{2}\.json$')
SUMMARY_KEYS = ('run_id', 'label', 'started_at', 'finished_at', 'state', 'suite', 'environment', 'source_fingerprint', 'summary', 'selected_cases')


class RegressionRunService:
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
        for path in sorted((run_dir / 'cases').glob('TC*.json')):
            if CASE_FILE.match(path.name):
                try:
                    cases.append(json.loads(path.read_text()))
                except ValueError:
                    continue
        from app.regression.runner import summarize
        return {**start, 'finished_at': None, 'state': 'incomplete', 'summary': summarize(cases), 'cases': cases}

    def list(self):
        items = []
        if self.directory.is_dir():
            for run_dir in sorted(self.directory.iterdir(), reverse=True):
                if run_dir.is_dir() and RUN_ID.match(run_dir.name):
                    run = self._load(run_dir)
                    if run:
                        items.append({k: run.get(k) for k in SUMMARY_KEYS})
        return {'schema_version': 'regression-run-page-v1', 'items': items, 'total': len(items),
                'notice': '回归在独立存储中运行，计划由运行器代为批准；结果不进入日常 Workflow 列表。'}

    def get(self, run_id: str):
        if not RUN_ID.match(run_id):
            raise AppError('REGRESSION_RUN_NOT_FOUND', '回归运行不存在。', 404)
        run = self._load(self.directory / run_id)
        if run is None:
            raise AppError('REGRESSION_RUN_NOT_FOUND', '回归运行不存在。', 404)
        return run
