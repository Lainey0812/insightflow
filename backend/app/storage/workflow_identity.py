"""Single-flow identity bootstrap; Session remains the business state authority."""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from uuid import uuid4

from app.domain.errors import AppError
from app.domain.models import SessionState, now, record_status_event


@dataclass(frozen=True)
class WorkflowIdentity:
    session_id: str
    workflow_id: str
    root_run_id: str


class WorkflowIdentityRepository:
    def __init__(self, database):
        self.database = database

    def create(self, state, request_id):
        """Session, source facts, identity and key commit together, before any Trace IO.

        Idempotency is deliberately scoped to an already allocated Session ID;
        a new upload creates a new Session, as before. This is not HTTP upload deduplication.
        """
        if state.workflow_kind != 'real_v1' or not request_id or not state.messages:
            raise AppError('WORKFLOW_IDENTITY_INVALID', '缺少真实流程创建信息。', 409)
        if not state.user_goal.strip():
            raise AppError('ANALYSIS_GOAL_REQUIRED', '身份登记需要非空分析需求，请填写后上传。', 422)
        origin = state.messages[0]
        payload = json.dumps({'file': state.file.model_dump(mode='json'), 'goal': state.user_goal,
            'options': state.profile_options.model_dump(mode='json'), 'origin': origin.model_dump(mode='json')},
            sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute('SELECT * FROM business_workflows WHERE session_id=?', (state.id,)).fetchall()
            if rows:
                if len(rows) != 1 or rows[0]['creation_request_id'] != request_id or rows[0]['creation_payload_hash'] != fingerprint:
                    raise AppError('WORKFLOW_IDENTITY_CONFLICT', '单流程身份或创建请求冲突。', 409)
                stored = conn.execute('SELECT state FROM sessions WHERE id=?', (state.id,)).fetchone()
                replay = SessionState.model_validate_json(stored['state'])
                self._verify(rows[0], replay)
                return replay
            if conn.execute('SELECT 1 FROM sessions WHERE id=?', (state.id,)).fetchone():
                raise AppError('WORKFLOW_IDENTITY_UNAVAILABLE', '历史会话不能自动登记为新流程。', 409)
            if state.status.value != 'CREATED' or origin.role != 'user':
                raise AppError('WORKFLOW_IDENTITY_INVALID', '仅新建用户分析请求可以登记身份。', 409)
            state.workflow_id = 'wf_' + uuid4().hex
            state.root_run_id = 'run_' + uuid4().hex
            record_status_event(state, None)
            conn.execute('INSERT INTO sessions VALUES (?,?,?)', (state.id,state.updated_at,state.model_dump_json()))
            existing = conn.execute('SELECT file_info FROM datasets WHERE id=?', (state.file.id,)).fetchone()
            if existing and json.loads(existing['file_info']) != state.file.model_dump(mode='json'):
                raise AppError('WORKFLOW_IDENTITY_CONFLICT', '文件清单与登记内容不一致。', 409)
            conn.execute('INSERT OR IGNORE INTO datasets VALUES (?,?)', (state.file.id,state.file.model_dump_json()))
            conn.execute('INSERT INTO session_datasets VALUES (?,?,?)', (state.id,state.file.id,now()))
            conn.execute('INSERT INTO session_messages VALUES (?,?,?,?,?,?,?,NULL)',
                (origin.id,state.id,1,origin.role,origin.kind,origin.content,origin.created_at))
            conn.execute('''INSERT INTO business_workflows
                (workflow_id,session_id,root_run_id,origin_message_id,input_file_id,goal_text,goal_sha256,
                 control_status,control_context,creation_request_id,creation_payload_hash,origin,
                 created_at,updated_at,materialized_at,provenance)
                VALUES (?,?,?,?,?,?,?,'CREATED',?,?,?,?,?,?,?,?)''',
                (state.workflow_id,state.id,state.root_run_id,origin.id,state.file.id,state.user_goal,
                 hashlib.sha256(state.user_goal.encode()).hexdigest(),
                 json.dumps({'authority':'session','scope':'identity_only'}),request_id,fingerprint,'native',
                 state.created_at,state.updated_at,now(),json.dumps({'source':'identity-bootstrap-v1'})))
            conn.execute('UPDATE session_messages SET workflow_id=? WHERE session_id=? AND message_id=?',
                (state.workflow_id,state.id,origin.id))
        return state

    @staticmethod
    def _verify(row, state):
        if (row['workflow_id'],row['root_run_id'],row['input_file_id']) != (state.workflow_id,state.root_run_id,state.file.id):
            raise AppError('WORKFLOW_IDENTITY_MISMATCH', '流程身份与业务登记不一致。', 409)

    def require_unregistered(self, session_id):
        with closing(self.database.connect()) as conn:
            if conn.execute('SELECT 1 FROM business_workflows WHERE session_id=?', (session_id,)).fetchone():
                raise AppError('WORKFLOW_IDENTITY_MISMATCH', '会话缺少已登记的显式流程身份。', 409)

    def resolve(self, state):
        with closing(self.database.connect()) as conn:
            rows = conn.execute('SELECT * FROM business_workflows WHERE session_id=?', (state.id,)).fetchall()
        if len(rows) != 1:
            raise AppError('WORKFLOW_IDENTITY_UNAVAILABLE', '缺少唯一明确登记的流程身份。', 409)
        self._verify(rows[0],state)
        return WorkflowIdentity(state.id,state.workflow_id,state.root_run_id)
