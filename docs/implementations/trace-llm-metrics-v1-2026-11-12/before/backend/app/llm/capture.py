"""Mandatory request journal for configured HTTP providers; no raw content in logs."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from time import perf_counter
from uuid import uuid4

from app.domain.errors import AppError
from app.domain.prompt_registry import LLMCallRecord, LLMRequestSnapshot
from app.observability.provenance import digest

logger = logging.getLogger('app.llm.capture')
CAPTURE_CODES = {'PROMPT_SOURCE_MISMATCH','PROMPT_CONTENT_MISMATCH','PROMPT_VERSION_CONFLICT',
                 'LLM_SNAPSHOT_UNAVAILABLE','LLM_CAPTURE_FINALIZE_FAILED','LLM_TEMPLATE_REQUIRED'}
RAW_BODY_LIMIT = 64 * 1024


class CallRecorder:
    def __init__(self, repository=None, retention_days=None):
        self.repository,self.retention_days = repository,retention_days

    def begin(self, request, payload, client_config=None):
        binding = request.call_binding
        if binding is None:
            raise AppError('LLM_TEMPLATE_REQUIRED','模型调用缺少已绑定模板，未发送请求。',503)
        try:
            if self.repository is None: raise RuntimeError('Registry unavailable')
            template = self.repository.register(binding.template)
            if payload['messages'][0] != {'role':'system','content':template.system_template}:
                raise AppError('PROMPT_CONTENT_MISMATCH','发送的 System 与模板快照不一致。',503)
            created = datetime.now(timezone.utc)
            previous = None
            if binding.retry_index:
                records = self.repository.calls(operation_id=binding.operation_id)
                previous = next((c for c in records if c.call_sequence == binding.call_sequence-1),None)
                if previous is None: raise ValueError('Missing prior attempt')
            identity = 'request_'+uuid4().hex
            snapshot = LLMRequestSnapshot(request_snapshot_id=identity,template_snapshot_id=template.template_snapshot_id,
                messages_hash=digest(payload['messages']),schema_hash=digest(payload['response_format']),request_hash=digest(payload),
                model_parameters={k:v for k,v in payload.items() if k not in {'messages','response_format'}},
                client_config=client_config or {},
                payload_ref=identity,created_at=created.isoformat(),
                expires_at=(created+timedelta(days=self.retention_days)).isoformat() if self.retention_days else None)
            call = LLMCallRecord(call_id='call_'+uuid4().hex,node_id=template.node_id,operation_id=binding.operation_id,
                call_sequence=binding.call_sequence,retry_index=binding.retry_index,template_snapshot_id=template.template_snapshot_id,
                retry_reason=binding.retry_reason,
                retry_of_call_id=previous.call_id if previous else None,
                request_snapshot_id=identity,run_id=binding.run_id,span_id=binding.span_id,status='running',started_at=created.isoformat())
            self.repository.begin(call,snapshot,payload)
            return call,perf_counter()
        except AppError: raise
        except Exception:
            logger.error('Request capture unavailable; HTTP call not sent',extra={'error_code':'LLM_SNAPSHOT_UNAVAILABLE'})
            raise AppError('LLM_SNAPSHOT_UNAVAILABLE','模型请求快照无法保存，本次请求未发送。',503) from None

    def finish(self, handle, response=None, error=None):
        call,timer = handle
        status = 'succeeded' if error is None else ('cancelled' if not isinstance(error,Exception) else 'failed')
        code = getattr(getattr(error,'error',None),'code',None) if error else None
        if error and not code: code = 'LLM_CALL_CANCELLED' if status=='cancelled' else 'LLM_CALL_FAILED'
        value = call.model_copy(update={'status':status,'finished_at':datetime.now(timezone.utc).isoformat(),
            'duration_ms':max(0,(perf_counter()-timer)*1000),'error_code':code,
            'response_hash':hashlib.sha256(response.text.encode()).hexdigest() if response else None})
        raw = getattr(error, 'raw_response', None) if error is not None else None
        stored = (('content', response.text, False) if response is not None else
                  ('raw_body', raw[:RAW_BODY_LIMIT], len(raw) > RAW_BODY_LIMIT) if isinstance(raw, str) else None)
        try: self.repository.finish(value, stored)
        except Exception:
            logger.error('LLM call occurred but terminal capture failed; result withheld',extra={'error_code':'LLM_CAPTURE_FINALIZE_FAILED'})
            raise AppError('LLM_CAPTURE_FINALIZE_FAILED','模型已调用但记录未能完成保存，未将本次调用标记为成功。',503) from None
