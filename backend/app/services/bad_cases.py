"""Save a human-judged Bad Case together with a frozen copy of the observed workflow evidence."""
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.bad_case import BadCaseCreate, BadCaseTransition
from app.domain.errors import AppError
from app.observability.provenance import digest

NODE_KEYS = ('span_id', 'parent_span_id', 'name', 'node_key', 'node_attempt', 'status', 'error_code', 'started_at',
             'finished_at', 'duration_ms', 'attributes')
CALL_KEYS = ('call_id', 'node_id', 'span_id', 'status', 'retry_index', 'retry_of_call_id', 'error_code', 'duration_ms',
             'request_snapshot_id', 'template_snapshot_id', 'response_hash')
REPLAY_KEYS = ('session_id', 'dataset_id', 'dataset_version', 'plan_id', 'plan_version', 'validation_version',
               'approval_id', 'execution_id', 'report_attempt')
EVIDENCE_NOTICE = ('冻结证据只含保存时的状态、节点元数据、质量信号与模型调用引用，不含原始数据、需求原文或模型文本。'
                   '回放引用指向的会话、数据集与模型快照按各自保留期管理，可能已过期。')


def now():
    return datetime.now(timezone.utc).isoformat()


def evidence_of(view):
    trace = view.get('trace') or {}
    return {
        'schema_version': 'bad-case-evidence-v1',
        'workflow_id': view['workflow_id'], 'root_run_id': view['root_run_id'],
        'business_lifecycle': view['business_lifecycle'], 'failure': view.get('failure'), 'quality': view.get('quality'),
        'consistency': view['consistency'], 'collection_status': view['collection']['status'],
        'nodes': [{k: n.get(k) for k in NODE_KEYS} for n in trace.get('nodes', [])],
        'llm_calls': [{k: c.get(k) for k in CALL_KEYS} for c in trace.get('llm_calls', [])],
        'replay_refs': {**{k: view['source_refs'].get(k) for k in REPLAY_KEYS}, 'session_id': view['session_id'],
                        'llm_call_ids': [c.get('call_id') for c in trace.get('llm_calls', [])]},
    }


class BadCaseService:
    def __init__(self, repository, workflow_observability):
        self.repository = repository
        self.workflows = workflow_observability

    def create(self, body: BadCaseCreate):
        view = self.workflows.get(body.workflow_id)
        evidence = evidence_of(view)
        node = None
        if body.span_id:
            node = next((n for n in evidence['nodes'] if n['span_id'] == body.span_id), None)
            if node is None:
                raise AppError('BAD_CASE_NODE_NOT_FOUND', '所选节点不属于该 Workflow。', 422)
        created = now()
        case = {'schema_version': 'bad-case-v1', 'case_id': 'bc_' + uuid4().hex, 'created_at': created,
                **body.model_dump(exclude={'annotator'}), 'created_by': body.annotator,
                'node_name': node['name'] if node else None,
                'evidence': evidence, 'evidence_sha256': digest(evidence), 'evidence_notice': EVIDENCE_NOTICE}
        event = {'event_id': 'bce_' + uuid4().hex, 'case_id': case['case_id'], 'sequence': 1, 'created_at': created,
                 'kind': 'created', 'status': 'open', 'note': '', 'annotator': body.annotator}
        self.repository.create(case, event)
        return self.get(case['case_id'])

    def transition(self, case_id: str, body: BadCaseTransition):
        found = self.repository.get(case_id)
        if not found:
            raise AppError('BAD_CASE_NOT_FOUND', 'Bad Case 不存在。', 404)
        if body.status in {'in_progress', 'pending_verification'} and found[1][-1]['status'] != body.status:
            raise AppError('BAD_CASE_COMMAND_REQUIRED', '请通过归因或修复提交进入此状态。', 422)
        if found[1][-1]['status'] == body.status and not body.note:
            raise AppError('BAD_CASE_NO_CHANGE', '状态未变化时请填写备注。', 422)
        self.repository.append({'event_id': 'bce_' + uuid4().hex, 'case_id': case_id, 'created_at': now(),
            'kind': 'status_changed' if found[1][-1]['status'] != body.status else 'note',
            'status': body.status, 'note': body.note, 'annotator': body.annotator}, body.expected_sequence)
        return self.get(case_id)

    def get(self, case_id: str):
        found = self.repository.get(case_id)
        if not found:
            raise AppError('BAD_CASE_NOT_FOUND', 'Bad Case 不存在。', 404)
        case, events = found
        intact = digest(case['evidence']) == case['evidence_sha256']
        attribution = next((e['attribution'] for e in reversed(events) if e.get('attribution')), None)
        repair = next((e['repair'] for e in reversed(events) if e.get('repair')), None)
        return {**case, 'attribution': attribution, 'repair': repair, 'evidence_intact': intact, 'status': events[-1]['status'],
                'sequence': events[-1]['sequence'], 'events': events}

    def attribute(self, case_id, body):
        item = self.get(case_id)
        if body.expected_sequence != item['sequence']:
            raise AppError('BAD_CASE_STALE', '归因已更新，请刷新后重试。', 409)
        if item['status'] not in {'open', 'confirmed', 'in_progress', 'pending_verification'}:
            raise AppError('BAD_CASE_NOT_EDITABLE', '请先重新打开已关闭的问题，再提交归因。', 409)
        if body.cause == 'prompt' and not body.node_id:
            raise AppError('BAD_CASE_PROMPT_NODE_REQUIRED', 'Prompt归因必须明确选择LLM节点。', 422)
        attribution = body.model_dump(exclude={'expected_sequence', 'annotator'})
        self.repository.append({'event_id':'bce_'+uuid4().hex,'case_id':case_id,'created_at':now(),
            'kind':'attribution_submitted','status':'in_progress','note':body.explanation,
            'annotator':body.annotator,'attribution':attribution}, body.expected_sequence)
        return self.get(case_id)

    def submit_repair(self, case_id, body, registry):
        item = self.get(case_id)
        if body.expected_sequence != item['sequence']:
            raise AppError('BAD_CASE_STALE', '归因已更新，请刷新后重试。', 409)
        attribution = item.get('attribution')
        if not item['evidence_intact']:
            raise AppError('BAD_CASE_EVIDENCE_INVALID', '冻结证据不完整，请先核实证据。', 409)
        if item['status'] != 'in_progress' or not attribution or attribution['cause'] != 'prompt':
            raise AppError('BAD_CASE_REPAIR_NOT_ALLOWED', '需要先提交Prompt归因并进入处理中。', 409)
        template = registry.template(body.template_snapshot_id)
        if (not template or template.node_id != attribution['node_id']
                or template.provenance != 'admin_debug_draft'):
            raise AppError('BAD_CASE_REPAIR_VERSION_MISMATCH', '修复草稿不属于当前归因节点，或不是已保存的调试草稿。', 422)
        from app.storage.prompt_registry import template_content
        if digest(template_content(template)) != template.content_hash:
            raise AppError('PROMPT_CONTENT_MISMATCH', '修复草稿哈希不一致。', 409)
        self.repository.append({'event_id':'bce_'+uuid4().hex,'case_id':case_id,'created_at':now(),
            'kind':'repair_submitted','status':'pending_verification','note':body.note or '已提交修复草稿，待验证；未发布线上版本。',
            'annotator':body.annotator,'repair':{'template_snapshot_id':template.template_snapshot_id,
                'node_id':template.node_id,'attribution_sequence':next(e['sequence'] for e in reversed(item['events']) if e.get('attribution'))}}, body.expected_sequence)
        return self.get(case_id)

    def list(self, *, workflow_id=None, status=None, category=None, limit=20, offset=0):
        rows = [{**{k: case[k] for k in ('case_id', 'workflow_id', 'span_id', 'node_name', 'category', 'severity', 'title',
                                           'created_at', 'created_by')},
                 'business_status': case['evidence']['business_lifecycle']['status'],
                 'status': latest['status'], 'sequence': latest['sequence'], 'updated_at': latest['created_at']}
                for case, latest in self.repository.all(workflow_id)]
        rows = [r for r in rows if (status is None or r['status'] == status) and (category is None or r['category'] == category)]
        selected = rows[offset:offset + limit]
        for row in selected:
            current = self.get(row['case_id'])
            row.update(attribution=current.get('attribution'),status=current['status'],sequence=current['sequence'],updated_at=current['events'][-1]['created_at'])
        return {'schema_version': 'bad-case-page-v1', 'items': selected, 'total': len(rows),
                'limit': limit, 'offset': offset}
