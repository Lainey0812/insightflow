"""No constructors, writers, revalidation or fallback to a Session's latest plan."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

from app.domain.business_workflow import WorkflowView, WorkflowPlanView
from app.domain.errors import AppError
from app.domain.plan_review import PlanVersion, ReviewApproval
from app.domain.execution import ExecutionRequest, ExecutionResultV1, ApprovedExecutionSnapshot
from app.domain.analysis_report import AnalysisReport
from app.observability.provenance import digest
from .workflow_expand import connect


class WorkflowReader:
    def __init__(self, business_path: Path):
        self.path = business_path

    @contextmanager
    def snapshot(self):
        conn = connect(self.path, readonly=True)
        try:
            conn.execute('BEGIN')
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _require(condition):
        if not condition:
            raise AppError('WORKFLOW_REFERENCE_INVALID', 'Workflow 归属或快照不一致；未重新校验或修改记录。', 409)

    def _workflow(self, conn, workflow_id):
        row = conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?', (workflow_id,)).fetchone()
        if row is None:
            raise AppError('BUSINESS_WORKFLOW_NOT_FOUND', '未登记 Business Workflow；Expand 不会自动回填。', 404)
        self._require(hashlib.sha256(row['goal_text'].encode()).hexdigest() == row['goal_sha256'])
        data = {key: row[key] for key in WorkflowView.model_fields}
        data['control_context'] = json.loads(data['control_context'])
        return WorkflowView.model_validate(data)

    def get(self, workflow_id):
        with self.snapshot() as conn:
            return self._workflow(conn, workflow_id)

    def list(self, session_id):
        with self.snapshot() as conn:
            ids = conn.execute('SELECT workflow_id FROM business_workflows WHERE session_id=? ORDER BY created_at,workflow_id', (session_id,)).fetchall()
            return [self._workflow(conn, row[0]) for row in ids]

    def _plan(self, conn, workflow_id, *, version=None, identity=None):
        workflow = self._workflow(conn, workflow_id)
        selector, value = ('plan_version', version) if version is not None else ('plan_version_id', identity)
        row = conn.execute(f'SELECT * FROM workflow_plan_versions WHERE workflow_id=? AND {selector}=?', (workflow_id, value)).fetchone()
        if row is None:
            raise AppError('WORKFLOW_PLAN_NOT_FOUND', '该 Workflow 没有此计划版本。', 404)
        raw = row['record_json']
        if row['source_kind'] == 'legacy_ref':
            legacy = conn.execute('SELECT record FROM plan_versions WHERE session_id=? AND plan_version=?',
                (row['legacy_session_id'], row['legacy_plan_version'])).fetchone()
            self._require(legacy is not None)
            raw = legacy[0]
        self._require(raw is not None and hashlib.sha256(raw.encode()).hexdigest() == row['payload_hash'])
        plan = PlanVersion.model_validate_json(raw)
        self._require((plan.session_id, plan.plan_id, plan.plan_version, plan.dataset_id, plan.dataset_version, plan.validation_version) ==
            (workflow.session_id, row['plan_id'], row['plan_version'], workflow.dataset_id, workflow.dataset_version, row['validation_version']))
        actual = plan.validated_plan.plan
        self._require((actual.plan_id, actual.plan_version, actual.dataset_id, actual.dataset_version) ==
            (plan.plan_id, plan.plan_version, plan.dataset_id, plan.dataset_version) and
            plan.validated_plan.validation_version == plan.validation_version)
        return WorkflowPlanView(workflow_id=workflow_id, plan_version_id=row['plan_version_id'], source_kind=row['source_kind'], version=plan)

    def plan(self, workflow_id, version):
        with self.snapshot() as conn:
            return self._plan(conn, workflow_id, version=version)

    def current_plan(self, workflow_id):
        with self.snapshot() as conn:
            workflow = self._workflow(conn, workflow_id)
            return self._plan(conn, workflow_id, identity=workflow.current_plan_version_id) if workflow.current_plan_version_id else None

    def _approval(self, conn, workflow_id, approval_id):
        row = conn.execute('''SELECT l.*,a.record FROM workflow_approval_links l JOIN plan_approvals a
            ON a.approval_id=l.approval_id WHERE l.workflow_id=? AND l.approval_id=?''', (workflow_id, approval_id)).fetchone()
        if row is None:
            raise AppError('WORKFLOW_APPROVAL_NOT_FOUND', '该 Workflow 没有此审批归属。', 404)
        plan = self._plan(conn, workflow_id, identity=row['plan_version_id']).version
        approval = ReviewApproval.model_validate_json(row['record'])
        self._require(approval.session_id == plan.session_id and approval.snapshot.validated_plan == plan.validated_plan
            and approval.plan_id == plan.plan_id and approval.plan_version == plan.plan_version
            and approval.validation_version == plan.validation_version and approval.snapshot.approval_id == approval_id
            and digest(approval.snapshot) == row['snapshot_hash'])
        return approval

    def approval(self, workflow_id, approval_id):
        with self.snapshot() as conn:
            return self._approval(conn, workflow_id, approval_id)

    def _execution(self, conn, workflow_id, execution_id):
        row = conn.execute('''SELECT l.*,e.request,e.approval,e.result,e.status FROM workflow_execution_links l
            JOIN executions e ON e.id=l.execution_id WHERE l.workflow_id=? AND l.execution_id=?''', (workflow_id, execution_id)).fetchone()
        if row is None:
            raise AppError('WORKFLOW_EXECUTION_NOT_FOUND', '该 Workflow 没有此执行归属。', 404)
        approval = self._approval(conn, workflow_id, row['approval_id'])
        request = ExecutionRequest.model_validate_json(row['request'])
        snapshot = ApprovedExecutionSnapshot.model_validate_json(row['approval'])
        self._require(snapshot == approval.snapshot and request.session_id == approval.session_id and
            (request.plan_id, request.plan_version) == (approval.plan_id, approval.plan_version))
        result = ExecutionResultV1.model_validate_json(row['result']) if row['result'] else None
        if result:
            self._require(result.execution_id == execution_id and result.approval_id == approval.approval_id and
                (result.session_id,result.plan_id,result.plan_version,result.dataset_id,result.dataset_version) ==
                (approval.session_id,approval.plan_id,approval.plan_version,approval.dataset_id,approval.dataset_version))
            for task in result.tasks:
                if task.result_id:
                    table = conn.execute('SELECT execution_id,row_count FROM execution_results WHERE id=?', (task.result_id,)).fetchone()
                    self._require(table is not None and table['execution_id'] == execution_id and table['row_count'] == task.row_count)
        return {'workflow_id': workflow_id, 'status': row['status'], 'request': request, 'approval': snapshot, 'result': result}

    def execution(self, workflow_id, execution_id):
        with self.snapshot() as conn:
            return self._execution(conn, workflow_id, execution_id)

    def report(self, workflow_id, report_id):
        with self.snapshot() as conn:
            row = conn.execute('''SELECT l.execution_id,r.report,r.audit FROM workflow_report_links l JOIN analysis_reports r
                ON r.id=l.report_id WHERE l.workflow_id=? AND l.report_id=?''', (workflow_id, report_id)).fetchone()
            if row is None:
                raise AppError('WORKFLOW_REPORT_NOT_FOUND', '该 Workflow 没有此已提交报告归属。', 404)
            execution = self._execution(conn, workflow_id, row['execution_id'])
            report = AnalysisReport.model_validate_json(row['report'])
            audit = json.loads(row['audit'])
            approval = execution['approval']
            self._require(report.execution_id == row['execution_id'] and report.execution_source == 'engine'
                and report.plan_version == approval.validated_plan.plan.plan_version
                and (report.dataset_id, report.dataset_version) ==
                (approval.validated_plan.plan.dataset_id, approval.validated_plan.plan.dataset_version)
                and audit.get('approval_id') == approval.approval_id and audit.get('session_id') == approval.session_id)
            return report

    def observation_links(self, workflow_id, sidecar_path: Path, *, kind):
        """Metadata only. Cross-database ownership is verified, never a fake FK."""
        workflow = self.get(workflow_id)
        if kind not in {'trace', 'registry'}:
            raise ValueError('Unknown sidecar kind')
        table = 'trace_workflow_links' if kind == 'trace' else 'llm_call_workflow_links'
        conn = connect(sidecar_path, readonly=True)
        try:
            conn.execute('BEGIN')
            rows = [dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE workflow_id=?', (workflow_id,))]
            for row in rows:
                self._require(row['session_id'] == workflow.session_id)
                if kind == 'trace':
                    stored = conn.execute('SELECT record FROM trace_runs WHERE id=?', (row['run_id'],)).fetchone()
                    self._require(stored is not None)
                    run = json.loads(stored[0])
                    self._require(run.get('session_id') == workflow.session_id and
                        run.get('kind', 'report_generation') == row['kind'])
                    if row['kind'] == 'workflow':
                        self._require(row['run_id'] == workflow.root_run_id)
                else:
                    stored = conn.execute('SELECT record FROM llm_calls WHERE id=?', (row['call_id'],)).fetchone()
                    self._require(stored is not None)
                    call = json.loads(stored[0])
                    self._require(call.get('run_id') == row['run_id'] and call.get('span_id') == row['span_id'] and
                        row['root_run_id'] in (None, workflow.root_run_id))
            self._require(self.get(workflow_id).revision == workflow.revision)
            return rows
        finally:
            conn.close()
