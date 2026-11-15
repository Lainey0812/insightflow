"""Immutable templates/requests and append-to-terminal call lifecycle, local SQLite."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

from app.domain.errors import AppError
from app.domain.prompt_registry import PromptTemplateSnapshot, LLMRequestSnapshot, LLMCallRecord
from app.observability.provenance import digest


def template_content(template):
    return template.model_dump(exclude={'template_snapshot_id', 'content_hash', 'created_at',
        'source_commit', 'source_dirty', 'provenance', 'change_summary'})


class PromptRegistryRepository:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / 'registry.sqlite3'
        # Create with restrictive permissions before SQLite writes any sensitive content.
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with closing(self.connect()) as conn, conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            existing=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='registry_migrations'").fetchone()
            if existing and any(row[0] not in (1, 2) for row in conn.execute('SELECT version FROM registry_migrations')):
                raise ValueError('Unsupported prompt registry migration version')
            for name in ('prompt_registry_001.sql', 'prompt_registry_002.sql'):
                conn.executescript(Path(__file__).with_name('migrations').joinpath(name).read_text())

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def register(self, template):
        template = PromptTemplateSnapshot.model_validate_json(template.model_dump_json())
        if digest(template_content(template)) != template.content_hash or template.template_snapshot_id != 'pt_'+template.content_hash:
            raise AppError('PROMPT_CONTENT_MISMATCH', '模板内容与哈希不一致，未调用模型。', 503)
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM prompt_templates WHERE node_id=? AND version=?',
                               (template.node_id, template.version)).fetchone()
            if row:
                saved = PromptTemplateSnapshot.model_validate_json(row['record'])
                if saved.content_hash != template.content_hash:
                    raise AppError('PROMPT_VERSION_CONFLICT', '同一模板版本已有不同内容，需登记新组合版本。', 409)
                return saved
            conn.execute('INSERT INTO prompt_templates VALUES (?,?,?,?,?)',
                (template.template_snapshot_id, template.node_id, template.version, template.content_hash, template.model_dump_json()))
        return template

    def begin(self, call, snapshot, payload):
        if (call.request_snapshot_id != snapshot.request_snapshot_id or
                call.template_snapshot_id != snapshot.template_snapshot_id or
                snapshot.request_hash != digest(payload) or snapshot.messages_hash != digest(payload['messages']) or
                snapshot.schema_hash != digest(payload['response_format']) or
                call.call_sequence != call.retry_index + 1 or call.status != 'running'):
            raise ValueError('Call/request binding mismatch')
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if call.retry_index:
                prior=conn.execute('SELECT record FROM llm_calls WHERE id=?',(call.retry_of_call_id,)).fetchone()
                previous=LLMCallRecord.model_validate_json(prior['record']) if prior else None
                if previous is None or previous.operation_id!=call.operation_id or previous.call_sequence!=call.call_sequence-1:
                    raise ValueError('Invalid retry binding')
            conn.execute('INSERT INTO llm_request_snapshots VALUES (?,?,?)',
                (snapshot.request_snapshot_id,snapshot.template_snapshot_id,snapshot.model_dump_json()))
            conn.execute('INSERT INTO llm_request_payloads VALUES (?,?,?)',
                (snapshot.request_snapshot_id,json.dumps(payload,ensure_ascii=False,allow_nan=False),snapshot.expires_at))
            conn.execute('INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?)',
                (call.call_id,call.operation_id,call.call_sequence,call.run_id,call.span_id,call.status,call.model_dump_json(),snapshot.request_snapshot_id))

    def finish(self, call, response=None):
        """response: optional (kind, content, truncated); saved atomically with the terminal call record."""
        with closing(self.connect()) as conn, conn:
            row = conn.execute('SELECT record FROM llm_calls WHERE id=?',(call.call_id,)).fetchone()
            if not row: raise ValueError('Call missing')
            old = LLMCallRecord.model_validate_json(row['record'])
            if old.status != 'running' or call.status == 'running': raise ValueError('Invalid call transition')
            stable = set(LLMCallRecord.model_fields) - {'status','finished_at','duration_ms','error_code','response_hash','http_status','endpoint','usage'}
            if any(getattr(old,k) != getattr(call,k) for k in stable): raise ValueError('Call identity changed')
            conn.execute('UPDATE llm_calls SET status=?,record=? WHERE id=? AND status=?',
                (call.status,call.model_dump_json(),call.call_id,'running'))
            if response is not None:
                kind, content, truncated = response
                if kind == 'content' and hashlib.sha256(content.encode()).hexdigest() != call.response_hash:
                    raise ValueError('Response content does not match call hash')
                expiry = conn.execute('SELECT expires_at FROM llm_request_payloads WHERE snapshot_id=?',
                                      (call.request_snapshot_id,)).fetchone()
                conn.execute('INSERT INTO llm_response_payloads VALUES (?,?,?,?,?,?)',
                    (call.call_id, kind, content, hashlib.sha256(content.encode()).hexdigest(), int(truncated),
                     expiry['expires_at'] if expiry else None))

    def response_availability(self, call_id):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT kind,expires_at FROM llm_response_payloads WHERE call_id=?',(call_id,)).fetchone()
        if row is None: return 'unavailable', None
        expired = row['expires_at'] and row['expires_at'] <= datetime.now(timezone.utc).isoformat()
        return ('expired' if expired else 'retained'), row['kind']

    def response(self, call_id):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT * FROM llm_response_payloads WHERE call_id=?',(call_id,)).fetchone()
        if row is None or (row['expires_at'] and row['expires_at'] <= datetime.now(timezone.utc).isoformat()):
            return None
        call = self.call(call_id)
        actual = hashlib.sha256(row['content'].encode()).hexdigest()
        if actual != row['content_sha256'] or (row['kind'] == 'content' and (call is None or actual != call.response_hash)):
            raise AppError('LLM_RESPONSE_INTEGRITY_ERROR','存档返回完整性校验失败，未返回原文。',503)
        return {'kind': row['kind'], 'content': row['content'], 'truncated': bool(row['truncated']),
                'content_sha256': actual}

    def _get(self, table, identity, model):
        with closing(self.connect()) as conn:
            row = conn.execute(f'SELECT record FROM {table} WHERE id=?',(identity,)).fetchone()
        return model.model_validate_json(row['record']) if row else None

    def template(self, identity): return self._get('prompt_templates',identity,PromptTemplateSnapshot)
    def snapshot(self, identity): return self._get('llm_request_snapshots',identity,LLMRequestSnapshot)
    def call(self, identity): return self._get('llm_calls',identity,LLMCallRecord)

    def calls(self, *, run_id=None, span_id=None, operation_id=None):
        filters = {k:v for k,v in {'run_id':run_id,'span_id':span_id,'operation_id':operation_id}.items() if v is not None}
        if not filters: raise ValueError('A call scope is required')
        where = ' AND '.join(k+'=?' for k in filters)
        with closing(self.connect()) as conn:
            rows = conn.execute('SELECT record FROM llm_calls WHERE '+where+' ORDER BY rowid LIMIT 500',list(filters.values())).fetchall()
        return [LLMCallRecord.model_validate_json(r['record']) for r in rows]

    def payload(self, snapshot_id):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT payload,expires_at FROM llm_request_payloads WHERE snapshot_id=?',(snapshot_id,)).fetchone()
        if row is None or (row['expires_at'] and row['expires_at'] <= datetime.now(timezone.utc).isoformat()):
            return None
        payload=json.loads(row['payload'])
        snapshot=self.snapshot(snapshot_id)
        if snapshot is None or digest(payload)!=snapshot.request_hash:
            raise AppError('LLM_REQUEST_INTEGRITY_ERROR','存档请求完整性校验失败，未返回原文。',503)
        return payload

    def prune_expired(self):
        with closing(self.connect()) as conn, conn:
            cutoff = datetime.now(timezone.utc).isoformat()
            responses = conn.execute('DELETE FROM llm_response_payloads WHERE expires_at IS NOT NULL AND expires_at<=?',
                                     (cutoff,)).rowcount
            return responses + conn.execute('DELETE FROM llm_request_payloads WHERE expires_at IS NOT NULL AND expires_at<=?',
                                            (cutoff,)).rowcount

    def recover(self):
        # Same single-process recovery boundary as the existing workflow services.
        with closing(self.connect()) as conn, conn:
            rows = conn.execute("SELECT record FROM llm_calls WHERE status='running'").fetchall()
            for row in rows:
                old = LLMCallRecord.model_validate_json(row['record'])
                value = old.model_copy(update={'status':'interrupted','error_code':'LLM_CALL_INTERRUPTED',
                    'finished_at':datetime.now(timezone.utc).isoformat()})
                conn.execute('UPDATE llm_calls SET status=?,record=? WHERE id=?',('interrupted',value.model_dump_json(),old.call_id))
