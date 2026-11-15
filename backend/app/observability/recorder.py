"""Explicit per-run context; observation failures never change business decisions."""
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import traceback
import re
from time import perf_counter
from uuid import uuid4

from app.domain.models import now
from app.domain.tracing import RunManifest, TraceRun, TraceSpan, TraceEvent, TraceSnapshot

from app.observability.provenance import digest, git_snapshot, input_fingerprints

logger=logging.getLogger('app.trace')
SAFE_KEYS={'candidate_status','evidence_count','selected_evidence_count','evidence_refs','candidate_count','accepted_count',
    'rejected_count','candidate_index','primary_evidence_id','error_code','rule','rule_ids','role',
    'input_bytes','output_bytes','provider','model','is_mock','purpose','prompt_version','schema_version',
    'generation_version','timeout_seconds','enable_thinking','skip_reason','report_status','goal_coverage',
    'inputs_match','insight_count','chart_count','dropped_events','observation_gap','report_id',
    'call_id','request_snapshot_id','template_snapshot_id'}
SAFE_KEYS.update({'status','previous_status','session_revision','node_name','operation_id','validation_role',
                  'next_action','coverage_status','executable_count','blocked_count','error_message',
                  'dataset_id','dataset_version','plan_id','plan_version','validation_version'})
SAFE_KEYS.update({'execution_id','plan_version_id','report_attempt','report_run_id','execution_status','result_ref','result_refs','commit_sha256'})
SAFE_KEYS.update({'row_count','column_count','workflow_id','root_run_id','approval_id','command','outcome'})
SAFE_KEYS.update({'batch_index','batch_count','group_refs','report_capacity_version','draft_schema_version','generation_mode','recommendation_id','limitation_refs'})
# Node input summaries: parse options, sizes and counts only; never file names, user text or data values.
SAFE_KEYS.update({'input_header_row','input_sheet_name','input_encoding','input_delimiter','input_file_extension',
                  'input_file_size_bytes','input_query_chars','input_clarification_count','input_field_count',
                  'input_dataset_id','input_dataset_version'})
SAFE_KEYS.update({'f0_count','f1_count','f2_count','unmet_core_count'})
SAFE_KEYS.update({'input_tokens','output_tokens','cached_tokens','total_tokens','estimated_cost','http_status','endpoint','error_stack','temperature','top_p','max_tokens'})
SAFE_KEYS.update({'file_format','profiler_version','sheet_name','quality_issue_count','total_cell_count','missing_cell_count','missing_cell_rate','duplicate_row_count','duplicate_row_rate','task_count'})

def feasibility_counts(validated):
    counts={'f0_count':0,'f1_count':0,'f2_count':0}
    for result in validated.validation_results:
        counts[result.feasibility.lower()+'_count']+=1
    return {**counts,'unmet_core_count':len(validated.unmet_core_requirements)}

def sanitized_stack(error):
    if not isinstance(error, BaseException):
        return None
    frames = traceback.extract_tb(error.__traceback__)[-12:]
    if not frames:
        return None
    lines = [type(error).__name__]
    code = error_code(error)
    if code:
        lines.append(code)
    for frame in frames:
        name = Path(frame.filename).name
        lines.append(f'{name}:{frame.lineno} {frame.name}')
    return '\n'.join(lines)


def safe_error_message(code):
    messages={'LLM_TIMEOUT':'模型调用超时。','LLM_HTTP_ERROR':'模型服务返回错误。',
        'LLM_UNAVAILABLE':'模型服务暂不可用。','LLM_INVALID_JSON':'模型输出不是有效 JSON。',
        'INTENT_SCHEMA_INVALID':'意图输出未通过结构校验。','LLM_UNGROUNDED_OUTPUT':'输出未通过原文溯源校验。',
        'PLANNER_INVALID_JSON':'规划输出不是有效 JSON。','PLAN_SCHEMA_INVALID':'计划结构校验未通过。',
        'TRACE_STAGE_FAILED':'执行范围异常结束，原始异常未记录。',
        'TRACE_PROCESS_INTERRUPTED':'服务重启发现未完成的观测。'}
    return messages.get(code,'节点未完成，请按错误代码核查；原始异常未记录。')

def safe(data):
    result={}
    for key,value in data.items():
        if key not in SAFE_KEYS: continue
        if value is None or type(value) in (int,float,bool): result[key]=value
        elif isinstance(value,str): result[key]=value[:2000 if key == 'error_stack' else 160]
        elif isinstance(value,list): result[key]=[v[:128] for v in value[:80] if isinstance(v,str)]
    return result

def error_code(error):
    code=error if isinstance(error,str) else getattr(getattr(error,'error',None),'code',None)
    return code if isinstance(code,str) and re.fullmatch('[A-Z][A-Z0-9_]{0,95}',code) else 'TRACE_STAGE_FAILED'

class SpanHandle:
    def __init__(self, context, name, attributes=None, skip=False):
        self.context=context
        self.skipped=skip
        flat = getattr(context, 'workflow_identity', None) is not None
        parent_key=(context.active.record.node_key+'#'+str(context.active.record.node_attempt)) if context.active and context.active.record and not flat else None
        key=(parent_key+'/' if parent_key else '')+name
        context.node_attempts[key]=context.node_attempts.get(key,0)+1
        self.record=TraceSpan(span_id='span_'+uuid4().hex,run_id=context.run.run_id,
            name=name,node_key=key,node_attempt=context.node_attempts[key],status='running',started_at=now(),attributes=safe({**getattr(context,'bindings',{}), **(attributes or {}), **({'workflow_id': context.workflow_identity.workflow_id,
                'root_run_id': context.workflow_identity.root_run_id} if flat else {})}),
            parent_span_id=context.active.record.span_id if context.active and context.active.record and not flat else None) if context.run else None
        self.timer=perf_counter()
        if self.record:
            if context.run.kind == 'workflow':
                saved=context.call(lambda: context.owner.repository.reserve_workflow_span(self.record))
                if saved is None:
                    self.record=None
            else:
                context.call(lambda: context.owner.repository.save_span(self.record))
            if self.record:
                self.event('span.skipped' if skip else 'span.started', **self.record.attributes)
    def event(self, event_type, **payload): self.context.event(event_type,self.record.span_id if self.record else None,**payload)
    def attributes(self, **values):
        if self.record: self.record.attributes.update(safe(values))
    def finish(self, error=None):
        if self.record:
            if error:
                self.record.status='suspended' if isinstance(error,BaseException) and not isinstance(error,Exception) else 'error'
                self.record.error_code=error_code(error)
                self.record.error_message=safe_error_message(self.record.error_code)
                observed = getattr(error, 'observation', None)
                if isinstance(observed, dict):
                    self.attributes(**observed)
                stack = sanitized_stack(error)
                if stack:
                    self.attributes(error_stack=stack)
            else:
                self.record.status=getattr(self,'terminal_status',None) or ('skipped' if self.skipped else ('error' if self.record.attributes.get('rejected_count',0) else 'success'))
            self.record.finished_at=now()
            self.record.duration_ms=max(0,(perf_counter()-self.timer)*1000)
            saved = self.context.call(lambda: self.context.owner.repository.save_span(self.record))
            if saved:
                self.event('span.finished', **{**self.record.attributes, 'error_code': self.record.error_code,
                                             'error_message':self.record.error_message})

class TraceContext:
    def __init__(self, owner, run=None):
        self.owner,self.run=owner,run
        self.sequence,self.gaps,self.emitted=0,0,0
        self.timer=perf_counter()
        self.active=None
        self.node_attempts={}
    def call(self, action):
        ok,value=self.owner.call(action)
        if not ok:
            self.gaps+=1
            if self.run and self.run.kind=='workflow':
                self.owner.call(lambda:self.owner.repository.mark_collection_gap(self.run.run_id))
        return value
    def event(self,event_type,span_id=None,**payload):
        if not self.run: return
        if self.emitted>=256:
            self.gaps+=1
            return
        if self.gaps: payload.update(observation_gap=True,dropped_events=self.gaps)
        cleaned=safe(payload)
        if len(json.dumps(cleaned).encode())>8192:
            self.gaps+=1
            return
        self.sequence+=1
        self.emitted+=1
        event=TraceEvent(event_id='evt_'+uuid4().hex,run_id=self.run.run_id,span_id=span_id,
            sequence=self.sequence,event_type=event_type,recorded_at=now(),payload=cleaned)
        self.call(lambda:self.owner.repository.event(event))
    @contextmanager
    def span(self,name,attributes=None,skip=False):
        handle=SpanHandle(self,name,attributes,skip)
        previous=self.active
        self.active=handle
        try:
            yield handle
        except BaseException as error:
            handle.finish(error)
            raise
        else: handle.finish()
        finally: self.active=previous
    def verify_inputs(self, execution, approval, profile, goal):
        if not self.run: return
        def verify():
            actual=input_fingerprints(execution,approval,profile,goal)
            self.event('inputs.verified',inputs_match=actual==self.run.manifest.input_sha256)
        self.call(verify)
    def snapshot(self, kind, content, projection):
        # Everything, including projection construction, is inside fail-open observation boundary.
        if not self.run: return
        def save():
            value=TraceSnapshot(snapshot_id='snap_'+uuid4().hex,run_id=self.run.run_id,
                span_id=self.active.record.span_id if self.active and self.active.record else None,
                kind=kind,captured_at=now(),content_sha256=(hashlib.sha256(content.encode()).hexdigest() if isinstance(content,str) else digest(content)),projection=projection())
            self.owner.repository.save_snapshot(value)
        self.call(save)
    def candidate(self,payload):
        if self.active:
            self.active.attributes(**{k:v for k,v in payload.items() if k in {'candidate_count','accepted_count','rejected_count'}})
            self.active.event('candidates.summarized' if 'candidate_count' in payload else 'candidate.validated',**payload)
    def finish(self,status,report=None,error=None):
        if not self.run: return
        self.event('run.finished',report_status=getattr(report,'report_status',None),goal_coverage=getattr(report,'goal_coverage',None),
            report_id=getattr(report,'report_id',None),error_code=error_code(error) if error else None)
        self.run.status=status
        self.run.finished_at=now()
        self.run.duration_ms=max(0,(perf_counter()-self.timer)*1000)
        self.run.report_id=getattr(report,'report_id',None)
        self.run.error_code=error_code(error) if error else None
        if self.gaps: self.run.integrity='incomplete'
        self.call(lambda:self.owner.repository.update_run(self.run))

class TraceRecorder:
    def __init__(self,repository=None):
        self.repository=repository
        self.owner_instance=uuid4().hex
        self.degraded=False
        self.warning_count=0
        self.workflow_gaps=set()
    def workflow_gap(self,session_id):
        self.degraded=True
        if len(self.workflow_gaps)<256:self.workflow_gaps.add(session_id)
        if self.warning_count<10:
            logger.warning('Workflow root observation unavailable; business continues',
                           extra={'event':'workflow_trace_gap','error_code':'TRACE_ROOT_NOT_COLLECTED'})
            self.warning_count+=1
    def call(self,action):
        if self.repository is None: return False,None
        try:return True,action()
        except Exception:
            self.degraded=True
            if self.warning_count<10:
                logger.warning('Trace persistence unavailable; business continues; observations may be missing',
                               extra={'event':'trace_write_failed','error_code':'TRACE_WRITE_FAILED'})
                self.warning_count+=1
            return False,None
    def queue(self,execution,record,approval_reader,service,input_reader=None):
        binding = getattr(record,'workflow_binding',None)
        def create():
            from app.reporting.prompt import PROMPT_VERSION,GENERATION_VERSION,SYSTEM_PROMPT
            pinned = getattr(service,'prompt_source',None)
            template_refs = {}
            if pinned:
                service.provider.capture.repository.register(pinned.snapshot)
                PROMPT_VERSION,SYSTEM_PROMPT = pinned.version,pinned.system_prompt
                template_refs['insight_generator'] = pinned.snapshot.template_snapshot_id
            approval=approval_reader()
            checked=approval.validated_plan
            root=Path(__file__).resolve().parents[1]
            paths=['services/analysis_report.py','workflow/reporting.py','reporting/evidence.py',
                   'reporting/fact_validation.py','reporting/claims.py','reporting/prompt.py',
                   'reporting/selection.py','reporting/contracts.py','reporting/visualization.py',
                   'domain/analysis_report.py','domain/tracing.py','observability/recorder.py',
                   'observability/provenance.py','observability/snapshots.py','llm/compatible_provider.py']
            fingerprints=input_fingerprints(*input_reader()) if input_reader else {}
            manifest=RunManifest(schema_version='workflow-trace-v0.3',capture_scope='report_generation',
                git=git_snapshot(root.parents[1]),input_sha256=fingerprints,prompt_template_snapshots=template_refs,
                bindings={'session_id':execution.session_id,'execution_id':execution.execution_id,
                'approval_id':execution.approval_id,'dataset_id':execution.dataset_id,'dataset_version':execution.dataset_version,
                'plan_id':execution.plan_id,'plan_version':execution.plan_version,
                **({'workflow_id':binding['workflow_id'],'root_run_id':binding['root_run_id']} if binding else {})},
                versions={'prompt_version':PROMPT_VERSION,'generation_version':GENERATION_VERSION,
                    'schema_version':'analysis-report-v1','prompt_sha256':digest(SYSTEM_PROMPT),
                    'fact_validator_sha256':digest([(root/p).read_text() for p in ('reporting/fact_validation.py','reporting/claims.py')]),
                    'validation_version':checked.validation_version,
                    'registry_version':checked.registry_version},
                model_config_snapshot={'provider':type(service.provider).__name__,
                    'model':getattr(service.provider,'model',None),
                    'endpoint_sha256':digest(service.provider.url) if isinstance(getattr(service.provider,'url',None),str) else None,
                    'timeout_seconds':service.timeout_seconds,
                    'enable_thinking':service.enable_thinking,
                    'temperature':getattr(service.provider,'temperature',None),
                    'top_p':getattr(service.provider,'top_p',None),
                    'max_tokens':getattr(service.provider,'max_tokens',None),'usage':None},
                source_sha256={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})
            previous=self.repository.attempt(execution.execution_id,record.attempt-1)
            root_run=None if binding else self.repository.workflow(execution.session_id)
            root_id=binding['root_run_id'] if binding else (root_run.run_id if root_run else None)
            return self.repository.create(TraceRun(run_id='run_'+uuid4().hex,
                session_id=execution.session_id,execution_id=execution.execution_id,attempt=record.attempt,
                workflow_run_id=root_id,
                retry_of_run_id=previous.run_id if previous else None,owner_instance=self.owner_instance,
                status='running',queued_at=record.queued_at,manifest=manifest))
        self.call(create)
    def start(self,execution_id,attempt):
        _,run=self.call(lambda:self.repository.attempt(execution_id,attempt))
        context=TraceContext(self,run)
        if run:
            run.status,run.started_at='running',now()
            context.call(lambda:self.repository.update_run(run))
            context.event('run.started')
        return context
    def recover(self): self.call(lambda:self.repository.recover())
