import json
from contextlib import closing

from app.domain.analysis_report import AnalysisReport
from app.domain.errors import AppError
from .database import Database


class ReportRepository:
    def __init__(self, database: Database):
        self.database = database
        with closing(database.connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS analysis_reports (id TEXT PRIMARY KEY, report TEXT NOT NULL, audit TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS report_generations (execution_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL)")

    def save(self, report: AnalysisReport, audit: dict):
        # Immutable IDs: no update endpoint, no overwrite of earlier reports.
        with closing(self.database.connect()) as conn, conn:
            conn.execute("INSERT INTO analysis_reports VALUES (?, ?, ?)",
                (report.report_id, report.model_dump_json(), json.dumps(audit, ensure_ascii=False, allow_nan=False)))

    def get(self, report_id: str) -> AnalysisReport:
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT report FROM analysis_reports WHERE id=?", (report_id,)).fetchone()
        if row is None:
            raise AppError("REPORT_NOT_FOUND", "报告不存在。", 404)
        return AnalysisReport.model_validate_json(row["report"])

    def generation(self, execution_id: str):
        from app.domain.models import ReportGeneration
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT record FROM report_generations WHERE execution_id=?", (execution_id,)).fetchone()
        return ReportGeneration.model_validate_json(row['record']) if row else None

    def queue(self, execution_id: str, session_id: str, expected_attempt: int | None = None):
        from app.domain.models import ReportGeneration
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM report_generations WHERE execution_id=?', (execution_id,)).fetchone()
            previous = ReportGeneration.model_validate_json(row['record']) if row else None
            if previous:
                if expected_attempt is None or previous.status in {'completed', 'unavailable'}:
                    return previous, False
                if previous.status != 'failed' or previous.attempt != expected_attempt:
                    raise AppError('STALE_REPORT_ATTEMPT', '报告状态已更新，请刷新后重试。')
            elif expected_attempt is not None:
                raise AppError('STALE_REPORT_ATTEMPT', '报告生成记录不存在，请刷新后重试。')
            record = ReportGeneration(execution_id=execution_id, session_id=session_id,
                status='queued', attempt=previous.attempt + 1 if previous else 1)
            record.workflow_binding = self._binding(conn,record)
            self._write_generation(conn, record)
            return record, True

    def start(self, execution_id: str, attempt: int):
        from app.domain.models import ReportGeneration, now
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM report_generations WHERE execution_id=?', (execution_id,)).fetchone()
            record = ReportGeneration.model_validate_json(row['record']) if row else None
            if record is None or record.attempt != attempt or record.status != 'queued':
                return None
            record.status, record.started_at = 'generating', now()
            if record.workflow_binding:
                record.workflow_binding = self._binding(conn,record)
            self._write_generation(conn, record)
            return record

    def finish(self, execution_id: str, attempt: int, report=None, audit=None, error=None):
        from app.domain.models import ReportGeneration, now
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM report_generations WHERE execution_id=?', (execution_id,)).fetchone()
            record = ReportGeneration.model_validate_json(row['record']) if row else None
            if not record or record.attempt != attempt or record.status not in {'queued', 'generating'}:
                return False
            if record.workflow_binding and not self._authorized(conn,record):
                return False
            if report:
                audit = dict(audit or {})
                if record.workflow_binding:
                    from .workflow_bindings import sha
                    bound = record.workflow_binding
                    for key in ('session_id','execution_id','approval_id','dataset_id','dataset_version','plan_id','plan_version'):
                        if audit.get(key) != bound[key]:
                            raise AppError('REPORT_APPROVAL_MISMATCH','报告提交引用与授权快照不一致。',409)
                    audit['commit_receipt'] = {**bound,'report_id':report.report_id,
                        'report_sha256':sha(report.model_dump_json()),
                        'committed_revision':bound['authorized_revision']+1,
                        'persistence_span_id':audit.get('persistence_span_id')}
                conn.execute('INSERT INTO analysis_reports VALUES (?, ?, ?)',
                    (report.report_id, report.model_dump_json(), json.dumps(audit, ensure_ascii=False, allow_nan=False)))
                record.report_id = report.report_id
                record.status = 'unavailable' if report.report_status == 'unavailable' else 'completed'
            else:
                record.status, record.error = 'failed', error
            record.finished_at = now()
            self._write_generation(conn, record)
            if report and record.workflow_binding:
                from app.domain.models import now
                bound=record.workflow_binding
                conn.execute('INSERT INTO workflow_report_links VALUES (?,?,?,?,?,?,?)',
                    (report.report_id,bound['workflow_id'],record.session_id,execution_id,attempt,'native',now()))
        return True

    def _binding(self,conn,record):
        from app.domain.models import SessionState
        from .workflow_bindings import current_execution, branch_hash
        state=SessionState.model_validate_json(conn.execute('SELECT state FROM sessions WHERE id=?',(record.session_id,)).fetchone()[0])
        if not state.workflow_id and not state.root_run_id:return None
        # Existing pre-C2 executions retain their original report contract; never infer a new ownership link.
        if not conn.execute('SELECT 1 FROM workflow_execution_links WHERE execution_id=?',(record.execution_id,)).fetchone():return None
        execution=conn.execute('SELECT result FROM executions WHERE id=?',(record.execution_id,)).fetchone()
        if not execution or not execution['result']:raise AppError('REPORT_ENGINE_RESULT_REQUIRED','执行结果未提交。',409)
        result=json.loads(execution['result'])
        link=current_execution(conn,state,record.execution_id,result['plan_version'],result['approval_id'])
        return {**{key:result[key] for key in ('session_id','execution_id','approval_id','dataset_id','dataset_version','plan_id','plan_version')},
            'workflow_id':state.workflow_id,'root_run_id':state.root_run_id,'plan_version_id':link['plan_version_id'],
            'report_attempt':record.attempt,'active_key':record.execution_id+':'+str(record.attempt),
            'commit_request_id':record.execution_id+':'+str(record.attempt),
            'authorized_revision':state.revision+1,'revision_authority':'session_single_flow','branch_sha256':branch_hash(state)}

    def _authorized(self,conn,record):
        from app.domain.models import SessionState
        from .workflow_bindings import branch_hash, identity
        state=SessionState.model_validate_json(conn.execute('SELECT state FROM sessions WHERE id=?',(record.session_id,)).fetchone()[0])
        identity(conn,state)
        bound=record.workflow_binding
        return (state.workflow_id==bound['workflow_id'] and state.root_run_id==bound['root_run_id']
                and state.revision==bound['authorized_revision'] and branch_hash(state)==bound['branch_sha256']
                and bound['active_key']==record.execution_id+':'+str(record.attempt))

    def committed(self,execution_id,attempt,report_id,span_id=None):
        """C19-B readback. Also works when commit succeeded but its return value was lost."""
        from .workflow_bindings import sha, branch_hash
        from app.domain.models import SessionState
        with closing(self.database.connect()) as conn:
            conn.execute('BEGIN')
            row=conn.execute('SELECT record FROM report_generations WHERE execution_id=?',(execution_id,)).fetchone()
            if not row:return False
            record=json.loads(row['record'])
            if record['attempt']!=attempt or record['report_id']!=report_id or record['status'] not in {'completed','unavailable'}:return False
            report=conn.execute('SELECT report,audit FROM analysis_reports WHERE id=?',(report_id,)).fetchone()
            if not report:return False
            bound=record.get('workflow_binding')
            if not bound:return True  # Existing legacy transaction contract, not a native C19 claim.
            audit=json.loads(report['audit']);receipt=audit.get('commit_receipt',{})
            link=conn.execute('SELECT * FROM workflow_report_links WHERE report_id=?',(report_id,)).fetchone()
            state=SessionState.model_validate_json(conn.execute('SELECT state FROM sessions WHERE id=?',(bound['session_id'],)).fetchone()[0])
            return bool(state.revision>=bound['authorized_revision']+1 and branch_hash(state)==bound['branch_sha256'] and link and link['workflow_id']==bound['workflow_id'] and link['execution_id']==execution_id
                and link['accepted_report_attempt']==attempt
                and all(receipt.get(key)==value for key,value in bound.items())
                and receipt.get('report_sha256')==sha(report['report'])
                and receipt.get('persistence_span_id')==span_id
                and receipt.get('committed_revision')==bound['authorized_revision']+1)

    def _write_generation(self, conn, record):
        from app.domain.models import SessionState, now
        row = conn.execute('SELECT state FROM sessions WHERE id=?', (record.session_id,)).fetchone()
        if row is None:
            raise AppError('SESSION_NOT_FOUND', '会话不存在。', 404)
        state = SessionState.model_validate_json(row['state'])
        state.report_generations = [r for r in state.report_generations if r.execution_id != record.execution_id] + [record]
        state.revision += 1
        state.updated_at = now()
        conn.execute('UPDATE sessions SET state=?, updated_at=? WHERE id=?',
            (state.model_dump_json(), state.updated_at, state.id))
        conn.execute('INSERT OR REPLACE INTO report_generations VALUES (?, ?, ?, ?)',
            (record.execution_id, record.session_id, record.status, record.model_dump_json()))

    def recover_interrupted(self):
        from app.domain.models import ReportGeneration, WorkflowError, now
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("SELECT record FROM report_generations WHERE status IN ('queued','generating')").fetchall()
            for row in rows:
                record = ReportGeneration.model_validate_json(row['record'])
                record.status, record.finished_at = 'failed', now()
                record.error = WorkflowError(code='REPORT_PROCESS_INTERRUPTED', message='报告生成被服务重启中断，可基于已保存的计算结果重试。', retryable=True)
                self._write_generation(conn, record)

    def owner(self, report_id):
        with closing(self.database.connect()) as conn:
            row = conn.execute('SELECT audit FROM analysis_reports WHERE id=?', (report_id,)).fetchone()
        return json.loads(row['audit']).get('session_id') if row else None
