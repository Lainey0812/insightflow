"""Read-only projections over V0.1 storage. Never register or render a prompt."""
from contextlib import closing
from datetime import datetime, timezone
import difflib
import json

from app.domain.errors import AppError
from app.domain.prompt_registry import PromptTemplateSnapshot, LLMCallRecord, LLMRequestSnapshot
from app.observability.provenance import digest
from app.storage.prompt_registry import template_content

NODES = {'intent_parser':'Intent Parser','analysis_planner':'Analysis Planner','insight_generator':'Insight Generator'}
ORDER = "julianday(json_extract(record,'$.created_at')) DESC, rowid DESC"


class PromptRegistryQuery:
    def __init__(self, repository, runtime_templates=None, traces=None):
        self.repository,self.runtime_templates,self.traces = repository,runtime_templates or {},traces

    def _node(self, node):
        if node not in NODES:raise AppError('PROMPT_NODE_NOT_FOUND','Prompt 节点不存在。',404)

    def _template(self, identity, node=None):
        template=self.repository.template(identity)
        if template is None or (node is not None and template.node_id!=node):
            raise AppError('PROMPT_TEMPLATE_NOT_FOUND','该历史快照未登记或不可用，不从当前内容重建。',404)
        if digest(template_content(template))!=template.content_hash:
            raise AppError('PROMPT_CONTENT_MISMATCH','登记模板完整性校验未通过。',503)
        return template

    def _summary(self, template):
        return template.model_dump(include={'template_snapshot_id','node_id','version','content_hash','created_at',
            'source_commit','source_dirty','provenance','change_summary'})

    def _state(self, node, connection):
        rows=connection.execute('SELECT record FROM prompt_templates WHERE node_id=? ORDER BY '+ORDER+' LIMIT 1',(node,)).fetchall()
        latest=PromptTemplateSnapshot.model_validate_json(rows[0]['record']) if rows else None
        runtime=self.runtime_templates.get(node)
        registered=bool(runtime and connection.execute('SELECT 1 FROM prompt_templates WHERE id=? AND node_id=?',(runtime,node)).fetchone())
        return {'latest_registered':self._summary(latest) if latest else None,'runtime_snapshot_id':runtime,
                'runtime_registration':'registered' if registered else ('not_registered' if runtime else 'unknown')}

    def catalog(self, node=None):
        if node:self._node(node)
        result=[]
        with closing(self.repository.connect()) as conn:
            conn.execute('BEGIN')
            for key,label in NODES.items():
                if node and node!=key:continue
                count=conn.execute('SELECT count(*) FROM prompt_templates WHERE node_id=?',(key,)).fetchone()[0]
                result.append({'prompt_id':key,'node_id':key,'label':label,'version_count':count,**self._state(key,conn)})
        return {'items':result,'notice':'仅显示真实登记快照；最新登记不等于已发布或当前启用。'}

    def history(self,node,limit=20,offset=0):
        self._node(node)
        with closing(self.repository.connect()) as conn:
            conn.execute('BEGIN')
            total=conn.execute('SELECT count(*) FROM prompt_templates WHERE node_id=?',(node,)).fetchone()[0]
            state=self._state(node,conn)
            rows=conn.execute('SELECT record FROM prompt_templates WHERE node_id=? ORDER BY '+ORDER+' LIMIT ? OFFSET ?',
                              (node,limit,offset)).fetchall()
        return {'prompt_id':node,'label':NODES[node],'items':[self._summary(PromptTemplateSnapshot.model_validate_json(r['record'])) for r in rows],
                'total':total,'limit':limit,'offset':offset,**state}

    def detail(self,node,identity):
        self._node(node)
        template=self._template(identity,node)
        with closing(self.repository.connect()) as conn:state=self._state(node,conn)
        return {'template':template,'availability':'available',**state,
            'variables_schema_availability':'unavailable','variables_notice':'V0.1 仅保存 User 字段与组合定义，未保存独立变量类型 Schema。'}

    def calls(self,node,identity,limit=20,offset=0):
        self._template(identity,node)
        with closing(self.repository.connect()) as conn:
            conn.execute('BEGIN')
            where="json_extract(c.record,'$.template_snapshot_id')=?"
            total=conn.execute('SELECT count(*) FROM llm_calls c WHERE '+where,(identity,)).fetchone()[0]
            rows=conn.execute('SELECT c.record,s.record AS snapshot FROM llm_calls c LEFT JOIN llm_request_snapshots s ON s.id=c.request_id WHERE '+where+
                " ORDER BY julianday(json_extract(c.record,'$.started_at')) DESC,c.rowid DESC LIMIT ? OFFSET ?",(identity,limit,offset)).fetchall()
        items=[]
        for row in rows:
            call=LLMCallRecord.model_validate_json(row['record'])
            snapshot=LLMRequestSnapshot.model_validate_json(row['snapshot']) if row['snapshot'] else None
            linked=False
            if call.run_id and self.traces:
                try:
                    run=self.traces.get(call.run_id)
                    span=self.traces.span(call.span_id) if call.span_id else None
                    linked=bool(run and (not call.span_id or (span and span.run_id==call.run_id)))
                except Exception:pass
            items.append({'call':call,'model':snapshot.model_parameters.get('model') if snapshot else None,'trace_available':linked})
        return {'items':items,'total':total,'limit':limit,'offset':offset}

    def call_summary(self,call_id):
        call=self.repository.call(call_id)
        if not call:raise AppError('LLM_CALL_NOT_FOUND','调用记录不存在。',404)
        snapshot=self.repository.snapshot(call.request_snapshot_id)
        with closing(self.repository.connect()) as conn:
            row=conn.execute('SELECT expires_at FROM llm_request_payloads WHERE snapshot_id=?',(call.request_snapshot_id,)).fetchone()
        availability='unavailable' if row is None else ('expired' if row['expires_at'] and row['expires_at']<=datetime.now(timezone.utc).isoformat() else 'retained')
        linked=False
        if call.run_id and self.traces:
            try:
                run=self.traces.get(call.run_id)
                span=self.traces.span(call.span_id) if call.span_id else None
                linked=bool(run and (not call.span_id or (span and span.run_id==call.run_id)))
            except Exception:pass
        return {'call':call,'request_snapshot':snapshot,'trace_available':linked,'raw_availability':availability,
                'redaction':{'messages':'hidden','output_schema':'hidden','reason':'完整内容需要独立快照读取授权。'}}

    def compare(self,left_id,right_id):
        left,right=self._template(left_id),self._template(right_id)
        if left.node_id!=right.node_id:raise AppError('PROMPT_NODE_MISMATCH','请选择同一节点的两个快照。',422)
        if left_id==right_id:raise AppError('PROMPT_DISTINCT_VERSIONS_REQUIRED','请选择两个不同快照。',422)
        def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)
        sections=[]
        def section(key,label,a,b):
            available=isinstance(a,str) and isinstance(b,str)
            lines=[]
            if available:
                aa,bb=a.splitlines(keepends=True),b.splitlines(keepends=True)
                for kind,i,j,k,l in difflib.SequenceMatcher(None,aa,bb,autojunk=True).get_opcodes():
                    for index in range(max(j-i,l-k)):
                        lines.append({'kind':kind,'left_number':i+index+1 if i+index<j else None,
                            'right_number':k+index+1 if k+index<l else None,
                            'left':aa[i+index] if i+index<j else None,'right':bb[k+index] if k+index<l else None})
            sections.append({'key':key,'label':label,'availability':'available' if available else 'unavailable',
                             'changed':a!=b if available else None,'lines':lines})
        section('system','System',left.system_template,right.system_template)
        section('user','User 组合与变量定义',encode(left.user_composition),encode(right.user_composition))
        section('retry','重试指令',encode(left.user_composition.get('retry_instructions',{})),encode(right.user_composition.get('retry_instructions',{})))
        section('fixed','其他固定上下文',encode(left.user_composition.get('fixed_context',{})),encode(right.user_composition.get('fixed_context',{})))
        section('schema','输出 Schema 生成定义',encode(left.output_schema_definition),encode(right.output_schema_definition))
        for path in sorted(set(left.source_files)|set(right.source_files)):
            section('source:'+path,'来源代码 · '+path,left.source_files.get(path,{}).get('source'),right.source_files.get(path,{}).get('source'))
        return {'left':self._summary(left),'right':self._summary(right),'content_hash_equal':left.content_hash==right.content_hash,
                'sections':sections,'notice':'比较已保存的固定模板与组合定义，不含动态请求。哈希还包含版本与代码指纹；不同哈希不保证 System 文本不同。'}
