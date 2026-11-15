"""Pin loaded instructions and verified composition sources, never infer old deployments."""
import ast
import importlib
import inspect
import json
import hashlib
from pathlib import Path
from types import CodeType
from datetime import datetime, timezone
from dataclasses import is_dataclass

from app.domain.errors import AppError
from app.domain.prompt_registry import PromptTemplateSnapshot, CallBinding
from app.observability.provenance import digest, git_snapshot
from app.storage.prompt_registry import template_content

COMPOSITION_VERSION = 'composition-v0.14-hitl-scope-question-v1'
MODULES = {
    'intent_parser': ['app.intent.prompt','app.intent.context','app.intent.validation','app.domain.intent'],
    'analysis_planner': ['app.planning.prompt','app.planning.context','app.planning.output',
        'app.planning.capabilities','app.planning.params','app.domain.analysis_plan','app.domain.intent'],
    'insight_generator': ['app.reporting.prompt','app.reporting.contracts','app.reporting.selection',
        'app.reporting.evidence','app.domain.analysis_report','app.review.presentation','app.review.constraint_audit',
        'app.review.bindings','app.review.confirmed_scope','app.reporting.draft_v2','app.reporting.recommendations',
        'app.reporting.materialize_v2','app.reporting.capacity','app.reporting.batches',
        'app.reporting.fact_validation','app.reporting.claims'],
}
USER_KEYS = {
    'intent_parser': ['user_query','clarification_answers','dataset_context','validation_feedback?'],
    'analysis_planner': ['intent','core_requirements','profile','capabilities','validation_feedback?'],
    'insight_generator': ['analysis_goal','goal_coverage','original_query','constraints','constraints_confirmed',
        'scope_context','fields','uncompleted_tasks','task_sample_context','tasks','evidence','evidence_groups','limitations',
        'required_core_groups','required_metric_groups','primary_evidence_options','allowed_limitations','draft_schema_version','recommendation_options','limitation_pool'],
}


def _shape(code):
    def constant(value):
        if isinstance(value, CodeType): return _shape(value)
        if isinstance(value, bytes): return {'bytes':value.hex()}
        if isinstance(value, slice): return {'slice':[constant(value.start),constant(value.stop),constant(value.step)]}
        if isinstance(value, complex): return {'complex':[value.real,value.imag]}
        if isinstance(value, (tuple, frozenset)): return [constant(v) for v in sorted(value,key=repr)] if isinstance(value,frozenset) else [constant(v) for v in value]
        if value is Ellipsis: return {'ellipsis':True}
        return value
    return {'bytecode':code.co_code.hex(),'constants':[constant(v) for v in code.co_consts],
        'names':code.co_names,'varnames':code.co_varnames,'freevars':code.co_freevars,'cellvars':code.co_cellvars,
        'argcount':code.co_argcount,'posonly':code.co_posonlyargcount,'kwonly':code.co_kwonlyargcount,'flags':code.co_flags,
        'exceptions':code.co_exceptiontable.hex()}


def _code_index(code):
    result = {code.co_qualname:code}
    for value in code.co_consts:
        if isinstance(value, CodeType): result.update(_code_index(value))
    return result


def _functions(value):
    if inspect.isfunction(value):
        yield value
    elif inspect.isclass(value) and value.__module__.startswith('app.'):
        for member in vars(value).values():
            if isinstance(member,(staticmethod,classmethod)): member=member.__func__
            if inspect.isfunction(member): yield member


def _source(module, actual_objects=()):
    path = Path(module.__file__).resolve()
    text = path.read_text()
    compiled = _code_index(compile(text, str(path), 'exec', dont_inherit=True))
    functions = []
    for value in vars(module).values():
        if getattr(value,'__module__',None) == module.__name__:
            functions.extend(f for f in _functions(value) if f.__module__ == module.__name__)
    for value in actual_objects:
        functions.extend(f for f in _functions(value) if f.__module__ == module.__name__)
    loaded = {}
    for function in functions:
        code = inspect.unwrap(function).__code__
        fresh = compiled.get(code.co_qualname)
        parent = vars(module).get(function.__qualname__.split('.')[0])
        if fresh is None and inspect.isclass(parent) and is_dataclass(parent) and inspect.unwrap(function).__code__.co_filename.startswith('<'):
            # dataclasses synthesizes these methods; retain their actual code fingerprints.
            loaded[function.__qualname__] = digest({'source':_shape(code),'wrapper':_shape(function.__code__)})
            continue
        if fresh is None or _shape(code) != _shape(fresh):
            raise AppError('PROMPT_SOURCE_MISMATCH','已加载组合逻辑与源码不同，请完整重启服务。',503)
        loaded[function.__qualname__] = digest({'source':_shape(code),'wrapper':_shape(function.__code__)})
    # Detect a changed literal (including version labels and mapping text) without executing source.
    literals = {}
    for statement in ast.parse(text).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target,ast.Name) and target.id.isupper():
                    try: literal=ast.literal_eval(statement.value)
                    except (ValueError,TypeError): continue
                    actual = getattr(module,target.id,object())
                    if not isinstance(literal,(dict,list,set)) and actual != literal:
                        raise AppError('PROMPT_SOURCE_MISMATCH','已加载固定指令与源码不同，请完整重启服务。',503)
                    try:
                        literals[target.id] = json.loads(json.dumps(actual,allow_nan=False))
                    except (TypeError,ValueError): pass
    root = Path(__file__).resolve().parents[2]
    return str(path.relative_to(root)), {'source':text, 'source_hash':hashlib.sha256(text.encode()).hexdigest(),
                                         'loaded_code_hashes':loaded,'loaded_literals':literals}


class TemplateSource:
    """Service-local pin. Rechecks loaded aliases at the call boundary, no prompt replay."""
    def __init__(self, node_id, service, version, system_prompt):
        self.node_id,self.service,self.version,self.system_prompt = node_id,service,version,system_prompt
        self.snapshot = self.build()

    def build(self):
        module = inspect.getmodule(type(self.service))
        prompt = importlib.import_module(MODULES[self.node_id][0])
        if (module.SYSTEM_PROMPT != self.system_prompt or prompt.SYSTEM_PROMPT != self.system_prompt
                or prompt.PROMPT_VERSION != self.version):
            raise AppError('PROMPT_SOURCE_MISMATCH','服务实际绑定的 Prompt 与版本来源不一致。',503)
        actual = [v for v in vars(module).values() if inspect.isfunction(v) or inspect.isclass(v)]
        names = list(dict.fromkeys([module.__name__, *MODULES[self.node_id],
            *[f.__module__ for v in actual for f in _functions(v) if f.__module__.startswith('app.')]]))
        # Capability handlers and the active instance schema are also real planning input sources.
        fixed = {}
        if hasattr(self.service,'registry'):
            fixed['capabilities'] = self.service.registry.summary()
            for spec in self.service.registry.operations.values():
                actual.extend([spec.handler,spec.params_model])
                names.extend([spec.handler.__module__,spec.params_model.__module__])
        sources = dict(_source(importlib.import_module(name),actual) for name in dict.fromkeys(names))
        composition = {'version':COMPOSITION_VERSION,'ordered_user_keys':USER_KEYS[self.node_id],
            'encoding':"json.dumps(ensure_ascii=False)", 'fixed_context':fixed,
            'retry_instructions':{k:v for k,v in vars(module).items() if k.endswith('_RETRY_INSTRUCTION')},
            'retry_instructions_source':module.__name__, 'scope_text_source':'app.review.presentation' if self.node_id=='insight_generator' else None}
        schema = {'intent_parser':'ParsedIntent.model_json_schema',
                  'analysis_planner':'CapabilityRegistry.request_schema + planning.output normalization',
                  'insight_generator':'InsightSelection V2 + evidence/recommendation/limitation ID enums'}[self.node_id]
        git = git_snapshot(Path(__file__).resolve().parents[3])
        provisional = PromptTemplateSnapshot(template_snapshot_id='',node_id=self.node_id,
            version=self.version+'+'+COMPOSITION_VERSION,content_hash='',system_template=self.system_prompt,
            user_composition=composition,output_schema_definition={'generator':schema},source_files=sources,
            source_commit=git.get('commit'),source_dirty=git.get('dirty'),created_at=datetime.now(timezone.utc).isoformat())
        content_hash = digest(template_content(provisional))
        return provisional.model_copy(update={'template_snapshot_id':'pt_'+content_hash,'content_hash':content_hash})

    def binding(self, operation_id, sequence=1, trace=None, retry_reason=None):
        current = self.build()
        if current.content_hash != self.snapshot.content_hash:
            raise AppError('PROMPT_SOURCE_MISMATCH','运行时组合内容已变化，拒绝使用旧模板标签。',503)
        run_id = trace.run.run_id if trace and trace.run else None
        span_id = trace.active.record.span_id if run_id and trace.active and trace.active.record else None
        return CallBinding(template=self.snapshot,operation_id=operation_id,call_sequence=sequence,
                           retry_index=sequence-1,retry_reason=retry_reason,run_id=run_id,span_id=span_id)


def pin_template(provider,node_id,service,version,system_prompt):
    # Scripted/custom providers retain their contract. Only the configured HTTP boundary persists real calls.
    return TemplateSource(node_id,service,version,system_prompt) if getattr(provider,'capture',None) is not None else None
