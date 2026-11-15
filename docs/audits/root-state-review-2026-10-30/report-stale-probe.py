"""Controlled stale-attempt schedule; temporary DB and local test provider only."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from test_report_workflow import Provider, run


def main():
    with tempfile.TemporaryDirectory(prefix='insightflow-stale-report-audit-') as directory:
        app = create_app(Settings(Path(directory)), Provider())
        with TestClient(app) as client:
            service = app.state.report_service
            original = service.generate
            old_report_ids = []
            async def delayed_finish(*args, **kwargs):
                report = await original(*args, **kwargs)
                old_report_ids.append(report.report_id)
                # Model an orphaned worker returning after recovery and retry.
                # This schedule is not an ordinary single-process restart.
                app.state.reports.recover_interrupted()
                record, fresh = app.state.report_workflow.enqueue(report.execution_id, expected_attempt=1)
                assert fresh and record.attempt == 2
                return report
            service.generate = delayed_finish
            _, execution, session = run(client)
            generation = app.state.reports.generation(execution['execution_id'])
            trace_repo = app.state.traces.repository
            old_trace = trace_repo.attempt(execution['execution_id'], 1)
            new_trace = trace_repo.attempt(execution['execution_id'], 2)
            with app.state.repository.database.connect() as conn:
                stored = conn.execute('SELECT COUNT(*) FROM analysis_reports WHERE id=?', (old_report_ids[0],)).fetchone()[0]
            print(json.dumps({
                'execution_status': execution['execution_status'],
                'session_status': session['status'],
                'current_report_attempt': generation.attempt,
                'current_generation_status': generation.status,
                'old_trace_status': old_trace.status,
                'old_trace_report_id': old_trace.report_id,
                'old_report_persisted': bool(stored),
                'new_trace_status': new_trace.status,
                'retry_of_correct': new_trace.retry_of_run_id == old_trace.run_id,
                'shared_workflow_root': old_trace.workflow_run_id == new_trace.workflow_run_id,
            }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
