"""Isolated, explicitly requested prompt experiments over the existing captured Provider.

No Workflow execution or runtime template activation. Test metadata references the
authoritative immutable templates and LLM calls; raw contents stay in Registry.
"""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from app.domain.errors import AppError
from app.domain.prompt_registry import CallBinding
from app.llm.base import LLMRequest
from app.observability.provenance import digest
from app.storage.prompt_registry import template_content


class DebugRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    node_id: str = Field(pattern=r'^(intent_parser|analysis_planner|insight_generator)$')
    snapshot_ids: list[str] = Field(min_length=1, max_length=2)
    case_name: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=60000)
    response_schema: dict
    draft_system: str | None = Field(default=None, min_length=1, max_length=60000)


class PromptWorkbench:
    def __init__(self, repository, provider):
        self.repo, self.provider = repository, provider

    def _template(self, node, identity):
        template = self.repo.template(identity)
        if not template or template.node_id != node:
            raise AppError('PROMPT_NODE_MISMATCH', '版本不存在或不属于当前节点。', 422)
        if digest(template_content(template)) != template.content_hash:
            raise AppError('PROMPT_CONTENT_MISMATCH', '版本内容校验失败。', 409)
        return template

    def _initialize(self):
        with closing(self.repo.connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS prompt_debug_cases (
                id TEXT PRIMARY KEY, node_id TEXT NOT NULL, created_at TEXT NOT NULL,
                record TEXT NOT NULL)''')
            for op in ('UPDATE', 'DELETE'):
                conn.execute(f'''CREATE TRIGGER IF NOT EXISTS prompt_debug_cases_no_{op.lower()}
                    BEFORE {op} ON prompt_debug_cases BEGIN
                    SELECT RAISE(ABORT,'immutable debug test metadata'); END''')

    def cases(self, node, snapshot, limit=20, offset=0):
        self._template(node, snapshot)
        with closing(self.repo.connect()) as conn:
            present = conn.execute("SELECT 1 FROM sqlite_master WHERE name='prompt_debug_cases'").fetchone()
            records = [json.loads(r['record']) for r in conn.execute(
                'SELECT record FROM prompt_debug_cases WHERE node_id=? ORDER BY created_at DESC,id', (node,))] if present else []
        items = []
        for record in records:
            sides = [s for s in record['sides'] if s['template_snapshot_id'] == snapshot]
            if sides:
                items.append({**record, 'sides': [self._side(s) for s in sides]})
        return {'items': items[offset:offset+limit], 'total': len(items), 'limit': limit, 'offset': offset,
                'notice': '仅包含明确保存的调试用例关联。历史评测未记录精确模板关系时，不从版本名称推测；生产调用另列。'}

    def _side(self, side):
        calls = self.repo.calls(operation_id=side['operation_id'])
        return {**side, 'calls': [c.model_dump(mode='json') for c in calls],
                'status': calls[-1].status if calls else 'unavailable'}

    def save_draft(self, node, identity, system):
        base = self._template(node, identity)
        composition = {**base.user_composition, 'admin_debug': {
            'base_snapshot_id': base.template_snapshot_id,
            'scope': 'system_override_with_explicit_test_input; no runtime activation'}}
        version = 'debug-' + digest({'base': base.template_snapshot_id, 'system': system})
        draft = base.model_copy(update={'version': version, 'system_template': system,
            'user_composition': composition, 'source_commit': None, 'source_dirty': None,
            'provenance': 'admin_debug_draft', 'created_at': datetime.now(timezone.utc).isoformat(),
            'change_summary': 'Admin isolated System draft; composition source retained as base reference, not activated.'})
        sha = digest(template_content(draft))
        return self.repo.register(draft.model_copy(update={'content_hash': sha, 'template_snapshot_id': 'pt_'+sha}))

    async def run(self, body):
        if len(set(body.snapshot_ids)) != len(body.snapshot_ids):
            raise AppError('PROMPT_DISTINCT_VERSIONS_REQUIRED', '请选择两个不同版本。', 422)
        if body.draft_system is not None and len(body.snapshot_ids) != 1:
            raise AppError('PROMPT_DEBUG_DRAFT_SCOPE', '草稿仅用于单独调试；Diff请选择两个已登记版本。', 422)
        if body.response_schema.get('type') != 'object' or len(json.dumps(body.response_schema).encode()) > 100000:
            raise AppError('PROMPT_DEBUG_SCHEMA_INVALID', '请提供大小不超过100KB的object输出JSON Schema。', 422)
        templates = [self._template(body.node_id, i) for i in body.snapshot_ids]
        if body.draft_system is not None:
            templates = [self.save_draft(body.node_id, templates[0].template_snapshot_id, body.draft_system)]
        self._initialize()
        record = {'test_id': 'pdt_'+uuid4().hex, 'node_id': body.node_id, 'case_name': body.case_name,
            'created_at': datetime.now(timezone.utc).isoformat(), 'input_hash': digest(body.instruction),
            'schema_hash': digest(body.response_schema), 'sides': [
                {'template_snapshot_id': t.template_snapshot_id, 'operation_id': 'debug_'+uuid4().hex} for t in templates]}
        with closing(self.repo.connect()) as conn, conn:
            conn.execute('INSERT INTO prompt_debug_cases VALUES (?,?,?,?)',
                (record['test_id'], body.node_id, record['created_at'], json.dumps(record,ensure_ascii=False)))
        results = []
        for template, side in zip(templates, record['sides']):
            try:
                response = await asyncio.wait_for(self.provider.generate(LLMRequest(
                    purpose='admin_prompt_debug', instruction=body.instruction, system_prompt=template.system_template,
                    response_schema=body.response_schema,
                    call_binding=CallBinding(template=template, operation_id=side['operation_id'], call_sequence=1, retry_index=0))),
                    timeout=min(float(getattr(self.provider, 'timeout', 60)), 120)+2)
                parsed = None
                try: parsed = json.loads(response.text)
                except ValueError: pass
                results.append({**self._side(side), 'output': response.text,
                    'json_valid': parsed is not None, 'model': response.model, 'is_mock': response.is_mock,
                    'validation_notice': '仅验证JSON可解析；未运行Intent/Planner/Report业务校验器，不代表业务质量通过。'})
            except Exception as error:
                code = getattr(getattr(error, 'error', None), 'code', None) or ('LLM_TIMEOUT' if isinstance(error, asyncio.TimeoutError) else 'PROMPT_DEBUG_FAILED')
                results.append({**self._side(side), 'error_code': code})
        return {**record, 'results': results, 'notice': '隔离调试，不触发分析执行或发布；两个版本使用完全相同的测试输入和Schema。'}
