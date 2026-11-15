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

    def compare(self, left_id: str, right_id: str):
        left, right = self.get(left_id), self.get(right_id)
        by_left = {c['case_id']: c for c in left.get('cases') or []}
        by_right = {c['case_id']: c for c in right.get('cases') or []}
        rank = {'passed': 2, 'needs_review': 1, 'blocked': 1, 'failed': 0}
        cases = []
        for case_id in list(dict.fromkeys([*(left.get('selected_cases') or []), *(right.get('selected_cases') or []), *by_left, *by_right])):
            a, b = by_left.get(case_id), by_right.get(case_id)
            left_status, right_status = (a or {}).get('status'), (b or {}).get('status')
            if a is None or b is None:
                change = 'only_one'
            elif left_status == right_status:
                change = 'unchanged'
            elif left_status not in rank or right_status not in rank:
                change = 'not_compared'
            elif rank[right_status] > rank[left_status]:
                change = 'improved'
            elif rank[right_status] < rank[left_status]:
                change = 'regressed'
            else:
                change = 'changed'
            left_checks = {c['key']: c for c in (a or {}).get('checks') or []}
            right_checks = {c['key']: c for c in (b or {}).get('checks') or []}
            checks = [{'key': key, 'label': (right_checks.get(key) or left_checks.get(key) or {}).get('label'),
                       'left': (left_checks.get(key) or {}).get('status'), 'right': (right_checks.get(key) or {}).get('status')}
                      for key in dict.fromkeys([*left_checks, *right_checks])
                      if (left_checks.get(key) or {}).get('status') != (right_checks.get(key) or {}).get('status')]
            cases.append({'case_id': case_id, 'title': (b or a or {}).get('title'), 'left_status': left_status, 'right_status': right_status,
                          'change': change, 'check_changes': checks})
        counts = {}
        for case in cases:
            counts[case['change']] = counts.get(case['change'], 0) + 1
        brief = ('run_id', 'label', 'state', 'environment', 'source_fingerprint', 'summary')
        return {'schema_version': 'regression-compare-v1', 'left': {k: left.get(k) for k in brief}, 'right': {k: right.get(k) for k in brief},
                'cases': cases, 'counts': counts,
                'notice': '右侧相对左侧。变好/变差只比较自动判定；未自动运行的用例不算回归。结果来自各自的独立库，编号不在日常 Workflow 列表。'}
