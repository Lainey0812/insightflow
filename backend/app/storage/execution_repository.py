import json
from collections.abc import Callable
from contextlib import closing

from app.domain.enums import SessionStatus as S
from app.domain.errors import AppError
from app.domain.execution import ApprovedExecutionSnapshot, ExecutedTask, ExecutionRequest, ExecutionResultV1, ResultTable
from app.domain.models import Message, SessionState, now, uid, record_status_event
from .database import Database


class ExecutionRepository:
    def __init__(self, database: Database):
        self.database = database
        with closing(database.connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(id), status TEXT NOT NULL,
                started_at TEXT NOT NULL, approval TEXT NOT NULL, progress TEXT NOT NULL, result TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_results (
                id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(id),
                row_count INTEGER NOT NULL, columns_json TEXT NOT NULL, rows_json TEXT NOT NULL
            )""")

    @staticmethod
    def _existing(row, request):
        if row["request"] != request.model_dump_json():
            raise AppError("EXECUTION_REQUEST_CONFLICT", "该 execution_request_id 已用于其他执行参数。", 409)
        if row["status"] == "running":
            raise AppError("EXECUTION_IN_PROGRESS", "同一请求正在执行，不会重复启动。", 409,
                           details={"execution_id": row["id"]})
        return ExecutionResultV1.model_validate_json(row["result"])

    def replay(self, request: ExecutionRequest):
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT * FROM executions WHERE request_id=?", (request.execution_request_id,)).fetchone()
        return self._existing(row, request) if row else None

    def claim(self, request: ExecutionRequest, expected_revision: int, check: Callable):
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT * FROM executions WHERE request_id=?", (request.execution_request_id,)).fetchone()
            if previous:
                return self._existing(previous, request)
            row = conn.execute("SELECT state FROM sessions WHERE id=?", (request.session_id,)).fetchone()
            if not row:
                raise AppError("SESSION_NOT_FOUND", "会话不存在。", 404)
            state = SessionState.model_validate_json(row["state"])
            check(state, request)
            if state.revision != expected_revision:
                raise AppError("APPROVAL_CHANGED", "读取数据期间会话或批准快照已改变，请重新提交。", 409)
            execution_id, started_at = "exec_" + uid(), now()
            conn.execute("INSERT INTO executions VALUES (?, ?, ?, ?, 'running', ?, ?, '[]', NULL)",
                (execution_id, request.execution_request_id, request.model_dump_json(), request.session_id,
                 started_at, state.engine_approval.model_dump_json()))
            previous = state.status
            state.status = S.RUNNING
            record_status_event(state, previous)
            if state.review_plan is not None:
                state.review_status = "executing"
            state.data_source = "uploaded"
            state.revision += 1
            state.updated_at = started_at
            state.engine_execution_ids.append(execution_id)
            state.messages.append(Message(role="assistant", kind="status", content="已核对批准版本，正在执行真实上传数据。"))
            from .workflow_bindings import bind_execution
            binding = bind_execution(conn,state,execution_id,request)
            conn.execute("UPDATE sessions SET state=?, updated_at=? WHERE id=?", (state.model_dump_json(), state.updated_at, state.id))
            return {"execution_id": execution_id, "started_at": started_at, "approval": state.engine_approval, "workflow_binding": binding}

    def save_task(self, execution_id: str, task: ExecutedTask, columns=None, rows=None):
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute("SELECT status, progress FROM executions WHERE id=?", (execution_id,)).fetchone()
            if not record or record["status"] != "running":
                raise AppError("EXECUTION_NOT_RUNNING", "执行记录已结束，不能写入任务结果。", 409)
            progress = json.loads(record["progress"])
            if any(t["task_id"] == task.task_id for t in progress):
                raise AppError("TASK_ALREADY_RECORDED", "该任务结果已保存。", 409)
            if rows is not None:
                conn.execute("INSERT INTO execution_results VALUES (?, ?, ?, ?, ?)",
                    (task.result_id, execution_id, len(rows), json.dumps(columns, ensure_ascii=False, allow_nan=False),
                     json.dumps(rows, ensure_ascii=False, allow_nan=False)))
            progress.append(task.model_dump(mode="json"))
            conn.execute("UPDATE executions SET progress=? WHERE id=?", (json.dumps(progress, ensure_ascii=False, allow_nan=False), execution_id))

    def finish(self, result: ExecutionResultV1, *, recovering=False):
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute("SELECT status,session_id,approval FROM executions WHERE id=?", (result.execution_id,)).fetchone()
            if not record or record["status"] != "running":
                raise AppError("EXECUTION_NOT_RUNNING", "执行记录已结束。", 409)
            saved = ApprovedExecutionSnapshot.model_validate_json(record['approval'])
            plan = saved.validated_plan.plan
            if (record['session_id'],saved.approval_id,plan.plan_id,plan.plan_version,plan.dataset_id,plan.dataset_version) != (result.session_id,result.approval_id,result.plan_id,result.plan_version,result.dataset_id,result.dataset_version):
                raise AppError('WORKFLOW_EXECUTION_STALE','执行结果与不可变批准快照不一致。',409)
            current = conn.execute('SELECT state FROM sessions WHERE id=?',(result.session_id,)).fetchone()
            state = SessionState.model_validate_json(current['state'])
            from .workflow_bindings import current_execution
            try:
                link = current_execution(conn,state,result.execution_id,result.plan_version,result.approval_id)
                if link and (state.status != S.RUNNING or link['dispatch_key'] != result.execution_id+'@'+str(state.revision)):
                    raise AppError('WORKFLOW_EXECUTION_STALE','执行提交授权已过期。',409)
            except AppError:
                if not recovering:raise
                # Recovery retains historical progress but cannot change a newer Session branch.
                conn.execute("UPDATE executions SET status='finished',result=? WHERE id=?",(result.model_dump_json(),result.execution_id))
                return False
            conn.execute("UPDATE executions SET status='finished', result=? WHERE id=?", (result.model_dump_json(), result.execution_id))
            row = conn.execute("SELECT state FROM sessions WHERE id=?", (result.session_id,)).fetchone()
            state = SessionState.model_validate_json(row["state"])
            if state.status == S.RUNNING:
                state.status = S.FAILED if result.execution_status == "failed" else S.COMPLETED
                record_status_event(state, S.RUNNING)
                if state.review_plan is not None:
                    state.review_status = "execution_failed" if result.execution_status == "failed" else "completed"
                state.revision += 1
                state.updated_at = now()
                state.messages.append(Message(role="assistant", kind="status", content="真实计算已结束，执行结果与步骤记录已保存；本阶段不自动生成报告。"))
                conn.execute("UPDATE sessions SET state=?, updated_at=? WHERE id=?", (state.model_dump_json(), state.updated_at, state.id))

    def get(self, execution_id: str) -> ExecutionResultV1:
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT status, result FROM executions WHERE id=?", (execution_id,)).fetchone()
        if not row:
            raise AppError("EXECUTION_NOT_FOUND", "执行记录不存在。", 404)
        if row["status"] == "running":
            raise AppError("EXECUTION_IN_PROGRESS", "执行尚未结束。", 409, details={"execution_id": execution_id})
        return ExecutionResultV1.model_validate_json(row["result"])

    def get_table(self, execution_id: str, result_id: str, offset=0, limit=5000) -> ResultTable:
        self.get(execution_id)
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT * FROM execution_results WHERE execution_id=? AND id=?", (execution_id, result_id)).fetchone()
        if not row:
            raise AppError("EXECUTION_RESULT_NOT_FOUND", "该执行中不存在指定结果。", 404)
        rows = json.loads(row["rows_json"])[offset:offset + limit]
        return ResultTable(result_id=result_id, columns=json.loads(row["columns_json"]), rows=rows,
            truncated=len(rows) != row["row_count"], total_result_rows=row["row_count"], row_offset=offset)

    def approved_snapshot(self, execution_id: str) -> ApprovedExecutionSnapshot:
        """Internal downstream reader: use the immutable execution approval, not the latest session plan."""
        self.get(execution_id)
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT approval FROM executions WHERE id=?", (execution_id,)).fetchone()
        return ApprovedExecutionSnapshot.model_validate_json(row["approval"])

    def complete(self, execution_id: str) -> ExecutionResultV1:
        result = self.get(execution_id)
        total = 0
        for task in result.tasks:
            if task.result:
                if task.row_count > 5000:
                    raise AppError("FULL_EXECUTION_TOO_LARGE", "完整结果超过单次读取限制，请分页读取结果引用。", 413)
                total += task.row_count * len(task.result.columns)
                if total > 100_000:
                    raise AppError("FULL_EXECUTION_TOO_LARGE", "完整结果超过单次读取单元格限制，请分页读取。", 413)
                task.result = self.get_table(execution_id, task.result_id, 0, 5000)
        result.result_view = "complete"
        return ExecutionResultV1.model_validate(result.model_dump())

    def running(self):
        with closing(self.database.connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM executions WHERE status='running'").fetchall()]
