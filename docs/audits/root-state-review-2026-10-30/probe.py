"""Read-only source audit probes. All writes target temporary SQLite databases."""
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, current_thread

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.domain.tracing import RunManifest, TraceRun
from app.storage.trace_repository import TraceRepository


def root(identity):
    return TraceRun(run_id=identity, kind='workflow', session_id=identity,
        workflow_run_id=identity, owner_instance='audit', attempt=1,
        status='running', business_revision=1, queued_at='2026-10-30T00:00:00Z',
        manifest=RunManifest(capture_scope='workflow_preparation'))


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix='insightflow-root-review-') as directory:
        repo = TraceRepository(Path(directory))
        initial = repo.create(root('root-terminal'))
        results['root_terminal_acceptance'] = {}
        for status in ('complete', 'partial'):
            candidate = initial.model_copy(update={'status': status})
            try:
                repo.update_run(candidate)
                outcome = 'accepted'
            except ValueError as exc:
                outcome = str(exc)
            results['root_terminal_acceptance'][status] = outcome

        repo.create(root('root-equal'))
        stale = repo.get('root-equal')
        newer = repo.get('root-equal')
        newer.status = 'waiting_approval'
        repo.update_run(newer)
        stale.status = 'failed'
        repo.update_run(stale)
        results['equal_revision_late_update'] = repo.get('root-equal').model_dump(include={'status', 'business_revision'})

        higher = repo.get('root-equal').model_copy(update={'status': 'running', 'business_revision': 20})
        repo.update_run(higher)
        repo.update_run(stale)
        results['sequential_lower_revision_control'] = repo.get('root-equal').model_dump(include={'status', 'business_revision'})

        # Schedule two real repository calls after both have read the same old row.
        # The higher revision commits first; the lower revision then commits last.
        repo.create(root('root-race'))
        low = repo.get('root-race').model_copy(update={'status': 'failed', 'business_revision': 10})
        high = repo.get('root-race').model_copy(update={'status': 'waiting_approval', 'business_revision': 20})
        original_connect = repo.connect
        readers = Barrier(2)
        high_done = Event()

        class ScheduledConnection:
            def __init__(self):
                self.connection = original_connect()
            def __enter__(self):
                self.connection.__enter__()
                return self
            def __exit__(self, *args):
                return self.connection.__exit__(*args)
            def close(self):
                self.connection.close()
            def execute(self, sql, params=()):
                if sql.startswith('SELECT record FROM trace_runs WHERE id='):
                    row = self.connection.execute(sql, params).fetchone()
                    readers.wait(timeout=5)
                    class SavedRow:
                        def fetchone(self):
                            return row
                    return SavedRow()
                if sql.startswith('UPDATE trace_runs') and current_thread().name == 'audit-low':
                    assert high_done.wait(timeout=5)
                return self.connection.execute(sql, params)

        repo.connect = ScheduledConnection
        def write(candidate, name):
            current_thread().name = name
            repo.update_run(candidate)
            if name == 'audit-high':
                high_done.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(write, low, 'audit-low')
            b = pool.submit(write, high, 'audit-high')
            a.result(timeout=10)
            b.result(timeout=10)
        repo.connect = original_connect
        results['concurrent_lower_revision_overwrite'] = repo.get('root-race').model_dump(include={'status', 'business_revision'})

        # Report attempts keep the existing independent terminal lifecycle.
        report = TraceRun(run_id='report-attempt', execution_id='execution-a', session_id='root-race',
            workflow_run_id='root-race', owner_instance='audit', attempt=1,
            status='queued', queued_at='2026-10-30T00:00:00Z', manifest=RunManifest())
        report = repo.create(report)
        report.status = 'running'
        repo.update_run(report)
        report.status = 'partial'
        repo.update_run(report)
        report.status = 'complete'
        repo.update_run(report)
        results['report_terminal_control'] = repo.get(report.run_id).status

        # The root branch checks an allowed status set, not a transition matrix.
        candidate = repo.get('root-equal')
        candidate.status = 'failed'
        repo.update_run(candidate)
        candidate.status = 'queued'
        repo.update_run(candidate)
        results['failed_to_queued_without_retry_claim'] = repo.get(candidate.run_id).status
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
