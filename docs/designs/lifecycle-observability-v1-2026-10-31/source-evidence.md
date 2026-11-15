# 只读源码摘录

此文件记录当前实现事实，不是目标实现或新运行日志。

## S01 — RunManifest

`backend/app/domain/tracing.py:8`

```python
class RunManifest(TraceModel):
    schema_version: Literal['workflow-trace-v0.1','workflow-trace-v0.3','workflow-trace-v0.3.1'] = 'workflow-trace-v0.1'
    bindings: dict = Field(default_factory=dict)
    versions: dict = Field(default_factory=dict)
    model_config_snapshot: dict = Field(default_factory=dict)
    source_sha256: dict[str, str] = Field(default_factory=dict)
    capture_scope: str | None = None
    git: dict = Field(default_factory=dict)
    input_sha256: dict[str, str] = Field(default_factory=dict)
    prompt_template_snapshots: dict[str, str] = Field(default_factory=dict)
    raw_content_retained: Literal[False] = False
```

## S02 — TraceRun

`backend/app/domain/tracing.py:20`

```python
class TraceRun(TraceModel):
    run_id: str
    kind: Literal['report_generation','workflow'] = 'report_generation'
    session_id: str
    execution_id: str | None = None
    workflow_run_id: str | None = None
    business_revision: int | None = None
    # Observation CAS token, independent of Session revisions and node retries.
    # Legacy JSON rows read as zero; no new table or Attempt entity is required.
    observation_revision: int = Field(default=0, ge=0)
    attempt: int = Field(ge=1)
    retry_of_run_id: str | None = None
    owner_instance: str
    status: Literal['queued','running','waiting_input','waiting_approval','complete','partial','unavailable','failed','interrupted']
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    recovered_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    report_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    integrity: Literal['observed','incomplete'] = 'observed'
    manifest: RunManifest

    @model_validator(mode='after')
    def valid_kind(self):
        if self.kind == 'report_generation' and not self.execution_id:
            raise ValueError('Report runs require the actual execution ID')
        if self.kind == 'workflow' and (self.execution_id is not None or self.workflow_run_id != self.run_id):
            raise ValueError('Workflow roots refer to themselves and do not invent an execution ID')
        return self
```

## S03 — TraceSpan

`backend/app/domain/tracing.py:53`

```python
class TraceSpan(TraceModel):
    span_id: str
    run_id: str
    parent_span_id: str | None = None
    name: str
    node_key: str | None = None
    node_attempt: int | None = Field(default=None, ge=1)
    status: Literal['running','complete','partial','failed','skipped','interrupted']
    started_at: str
    finished_at: str | None = None
    recovered_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    attributes: dict = Field(default_factory=dict)
```

## S04 — TraceEvent

`backend/app/domain/tracing.py:69`

```python
class TraceEvent(TraceModel):
    event_id: str
    run_id: str
    span_id: str | None = None
    sequence: int = Field(ge=1)
    event_type: str
    recorded_at: str
    payload: dict = Field(default_factory=dict)
```

## S05 — TraceSnapshot

`backend/app/domain/tracing.py:78`

```python
class TraceSnapshot(TraceModel):
    snapshot_id: str
    run_id: str
    span_id: str | None = None
    kind: Literal['evidence','llm_output','report']
    captured_at: str
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    projection: dict = Field(default_factory=dict)
    schema_version: Literal['controlled-projection-v1'] = 'controlled-projection-v1'
    raw_content_retained: Literal[False] = False
```

## S06 — register_root

`backend/app/observability/workflow.py:11`

```python
def register_root(recorder, state, parser, planner):
    def create():
        refs = {}
        versions = {}
        models = {}
        for name, service in [('intent_parser', parser), ('analysis_planner', planner)]:
            source = getattr(service, 'prompt_source', None)
            if source:
                refs[name] = source.snapshot.template_snapshot_id
                versions[name] = source.version
            provider = getattr(service, 'provider', None)
            models[name] = {'provider': type(provider).__name__, 'model': getattr(provider, 'model', None),
                            'timeout_seconds': getattr(service, 'timeout_seconds', None),
                            'enable_thinking': getattr(service, 'enable_thinking', None)}
        identity = 'run_' + uuid4().hex
        return recorder.repository.create(TraceRun(run_id=identity, kind='workflow', workflow_run_id=identity,
            session_id=state.id, attempt=1, owner_instance=recorder.owner_instance, status='queued',
            business_revision=state.revision, queued_at=state.created_at,
            manifest=RunManifest(schema_version='workflow-trace-v0.3.1', capture_scope='workflow_preparation',
                bindings={'session_id': state.id, 'file_id': state.file.id}, versions=versions,
                git=git_snapshot(Path(__file__).resolve().parents[3]),
                input_sha256={'user_goal': digest(state.user_goal)},
                prompt_template_snapshots=refs, model_config_snapshot=models)))
    ok, run = recorder.call(create)
    if not ok:
        recorder.workflow_gap(state.id)
    return run
```

## S07 — preparation_context

`backend/app/observability/workflow.py:40`

```python
def preparation_context(recorder, session_id):
    ok, run = recorder.call(lambda: recorder.repository.workflow(session_id))
    if not ok:
        recorder.workflow_gap(session_id)
    return TraceContext(recorder, run)
```

## S08 — start_preparation

`backend/app/observability/workflow.py:47`

```python
def start_preparation(trace, revision):
    if not trace.run:
        return
    run = trace.run
    previous = run.status
    if previous == 'running':
        # A second dispatch must not take ownership of an active observation.
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=revision)
        trace.run = None
        return
    run.status, run.business_revision = 'running', revision
    run.started_at = run.started_at or datetime.now(timezone.utc).isoformat()
    run.finished_at, run.duration_ms, run.error_code, run.error_message = None, None, None, None
    accepted = trace.call(lambda: trace.owner.repository.update_run(run))
    if accepted:
        trace.event('workflow.started' if previous == 'queued' else 'workflow.resumed',
                    status='running', previous_status=previous, session_revision=revision)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=revision)
        trace.run = None
```

## S09 — checkpoint

`backend/app/observability/workflow.py:69`

```python
def checkpoint(trace, state):
    if not trace.run:
        return
    mapping = {'WAITING_FOR_CLARIFICATION': 'waiting_input', 'AWAITING_APPROVAL': 'waiting_approval', 'FAILED': 'failed'}
    status = mapping.get(state.status.value, 'running')
    run = trace.run
    run.status, run.business_revision = status, state.revision
    if status == 'failed':
        run.finished_at = datetime.now(timezone.utc).isoformat()
        # The root's elapsed wall time is not a node computation duration.
        run.duration_ms = None
        run.error_code = error_code(state.error.code) if state.error else 'WORKFLOW_PREPARATION_FAILED'
        run.error_message = safe_error_message(run.error_code)
    if trace.gaps:
        run.integrity = 'incomplete'
    accepted = trace.call(lambda: trace.owner.repository.update_run(run))
    if accepted:
        trace.event('workflow.' + status, status=status, session_revision=state.revision,
                    error_code=run.error_code, error_message=run.error_message)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK', session_revision=state.revision)
```

## S10 — interrupt

`backend/app/observability/workflow.py:92`

```python
def interrupt(trace, error):
    if not trace.run:
        return
    trace.run.status = 'interrupted'
    trace.run.error_code = error_code(error)
    trace.run.error_message = safe_error_message(trace.run.error_code)
    trace.run.finished_at = datetime.now(timezone.utc).isoformat()
    trace.run.duration_ms = None
    accepted = trace.call(lambda: trace.owner.repository.update_run(trace.run))
    if accepted:
        trace.event('workflow.interrupted', error_code=trace.run.error_code)
    elif accepted is False:
        trace.event('workflow.callback_ignored', error_code='TRACE_STALE_CALLBACK')
```

## S11 — safe

`backend/app/observability/recorder.py:37`

```python
def safe(data):
    result={}
    for key,value in data.items():
        if key not in SAFE_KEYS: continue
        if value is None or type(value) in (int,float,bool): result[key]=value
        elif isinstance(value,str): result[key]=value[:160]
        elif isinstance(value,list): result[key]=[v[:128] for v in value[:80] if isinstance(v,str)]
    return result
```

## S12 — SpanHandle.__init__

`backend/app/observability/recorder.py:51`

```python
def __init__(self, context, name, attributes=None, skip=False):
        self.context=context
        self.skipped=skip
        parent_key=(context.active.record.node_key+'#'+str(context.active.record.node_attempt)) if context.active and context.active.record else None
        key=(parent_key+'/' if parent_key else '')+name
        context.node_attempts[key]=context.node_attempts.get(key,0)+1
        self.record=TraceSpan(span_id='span_'+uuid4().hex,run_id=context.run.run_id,
            name=name,node_key=key,node_attempt=context.node_attempts[key],status='running',started_at=now(),attributes=safe(attributes or {}),
            parent_span_id=context.active.record.span_id if context.active and context.active.record else None) if context.run else None
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
```

## S13 — SpanHandle.finish

`backend/app/observability/recorder.py:73`

```python
def finish(self, error=None):
        if self.record:
            if error:
                self.record.status='interrupted' if isinstance(error,BaseException) and not isinstance(error,Exception) else 'failed'
                self.record.error_code=error_code(error)
                self.record.error_message=safe_error_message(self.record.error_code)
            else:
                self.record.status='skipped' if self.skipped else ('partial' if self.record.attributes.get('rejected_count',0) else 'complete')
            self.record.finished_at=now()
            self.record.duration_ms=max(0,(perf_counter()-self.timer)*1000)
            self.event('span.finished', **{**self.record.attributes, 'error_code': self.record.error_code,
                                         'error_message':self.record.error_message})
            self.context.call(lambda: self.context.owner.repository.save_span(self.record))
```

## S14 — TraceContext.event

`backend/app/observability/recorder.py:98`

```python
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
```

## S15 — TraceContext.span

`backend/app/observability/recorder.py:114`

```python
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
```

## S16 — TraceContext.finish

`backend/app/observability/recorder.py:144`

```python
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
```

## S17 — TraceRecorder.call

`backend/app/observability/recorder.py:170`

```python
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
```

## S18 — TraceRecorder.queue

`backend/app/observability/recorder.py:180`

```python
def queue(self,execution,record,approval_reader,service,input_reader=None):
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
                'plan_id':execution.plan_id,'plan_version':execution.plan_version},
                versions={'prompt_version':PROMPT_VERSION,'generation_version':GENERATION_VERSION,
                    'schema_version':'analysis-report-v1','prompt_sha256':digest(SYSTEM_PROMPT),
                    'fact_validator_sha256':digest([(root/p).read_text() for p in ('reporting/fact_validation.py','reporting/claims.py')]),
                    'validation_version':checked.validation_version,
                    'registry_version':checked.registry_version},
                model_config_snapshot={'provider':type(service.provider).__name__,
                    'model':getattr(service.provider,'model',None),
                    'endpoint_sha256':digest(service.provider.url) if isinstance(getattr(service.provider,'url',None),str) else None,
                    'timeout_seconds':service.timeout_seconds,
                    'enable_thinking':service.enable_thinking,'temperature':None,'top_p':None,'usage':None},
                source_sha256={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})
            previous=self.repository.attempt(execution.execution_id,record.attempt-1)
            root_run=self.repository.workflow(execution.session_id)
            return self.repository.create(TraceRun(run_id='run_'+uuid4().hex,
                session_id=execution.session_id,execution_id=execution.execution_id,attempt=record.attempt,
                workflow_run_id=root_run.run_id if root_run else None,
                retry_of_run_id=previous.run_id if previous else None,owner_instance=self.owner_instance,
                status='queued',queued_at=record.queued_at,manifest=manifest))
        self.call(create)
```

## S19 — TraceRecorder.start

`backend/app/observability/recorder.py:222`

```python
def start(self,execution_id,attempt):
        _,run=self.call(lambda:self.repository.attempt(execution_id,attempt))
        context=TraceContext(self,run)
        if run:
            run.status,run.started_at='running',now()
            context.call(lambda:self.repository.update_run(run))
            context.event('run.started')
        return context
```

## S20 — TraceRecorder.workflow_gap

`backend/app/observability/recorder.py:163`

```python
def workflow_gap(self,session_id):
        self.degraded=True
        if len(self.workflow_gaps)<256:self.workflow_gaps.add(session_id)
        if self.warning_count<10:
            logger.warning('Workflow root observation unavailable; business continues',
                           extra={'event':'workflow_trace_gap','error_code':'TRACE_ROOT_NOT_COLLECTED'})
            self.warning_count+=1
```

## S21 — current_trace

`backend/app/observability/context.py:8`

```python
def current_trace():
    return _trace.get()
```

## S22 — bind_trace

`backend/app/observability/context.py:13`

```python
def bind_trace(trace):
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)
```

## S23 — TraceRepository.create

`backend/app/storage/trace_repository.py:48`

```python
def create(self, run):
        run = TraceRun.model_validate(run.model_dump())
        with closing(self.connect()) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO trace_runs VALUES (?, ?, ?, ?, ?, ?)',
                (run.run_id,run.execution_id,run.attempt,run.queued_at,run.status,run.model_dump_json()))
        return self.workflow(run.session_id) if run.kind == 'workflow' else self.attempt(run.execution_id,run.attempt)
```

## S24 — TraceRepository.workflow

`backend/app/storage/trace_repository.py:55`

```python
def workflow(self, session_id):
        with closing(self.connect()) as conn:
            row=conn.execute("SELECT record FROM trace_runs WHERE json_extract(record,'$.kind')='workflow' AND json_extract(record,'$.session_id')=?",(session_id,)).fetchone()
        return TraceRun.model_validate_json(row['record']) if row else None
```

## S25 — TraceRepository.update_run

`backend/app/storage/trace_repository.py:60`

```python
def update_run(self, run):
        with closing(self.connect()) as conn, conn:
            # Read, compare and write under one lock. The JSON token also fences
            # separate callbacks which carry the same business revision.
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT record FROM trace_runs WHERE id=?',(run.run_id,)).fetchone()
            if row is None: raise ValueError('Trace run missing')
            previous=TraceRun.model_validate_json(row['record'])
            if previous.manifest != run.manifest: raise ValueError('Manifest is immutable')
            if any(getattr(run,key)!=getattr(previous,key) for key in
                   ('kind','session_id','execution_id','attempt','retry_of_run_id','owner_instance','queued_at','workflow_run_id')):
                raise ValueError('Run identity is immutable')
            if run.observation_revision != previous.observation_revision:
                return False
            if previous.kind == 'workflow':
                if run.kind != 'workflow' or run.status not in {'queued','running','waiting_input','waiting_approval','failed','interrupted'}:
                    raise ValueError('Unsupported preparation root transition')
                if (previous.business_revision is not None
                        and (run.business_revision is None or run.business_revision < previous.business_revision)): return False
                allowed_root = {
                    'queued': {'running', 'interrupted'},
                    'running': {'running', 'waiting_input', 'waiting_approval', 'failed', 'interrupted'},
                    'waiting_input': {'running'}, 'waiting_approval': set(),
                    'failed': {'running'}, 'interrupted': {'running'},
                }
                if run.status not in allowed_root.get(previous.status, set()):
                    return False
                if previous.status in {'waiting_input','failed','interrupted'} and (
                        run.business_revision is None or
                        run.business_revision <= (previous.business_revision if previous.business_revision is not None else -1)):
                    return False
                if previous.integrity == 'incomplete': run.integrity = 'incomplete'
            elif previous.status not in {'queued','running'}: return False
            allowed={'queued':{'queued','running','interrupted'},
                     'running':{'running','complete','partial','failed','unavailable','interrupted'}}
            if previous.kind != 'workflow' and run.status not in allowed[previous.status]: raise ValueError('Invalid observation transition')
            saved = run.model_copy(update={'observation_revision': previous.observation_revision + 1})
            conn.execute('UPDATE trace_runs SET status=?,record=? WHERE id=?',(saved.status,saved.model_dump_json(),saved.run_id))
        # Advance the caller's token only after a successful database commit.
        run.observation_revision = saved.observation_revision
        return True
```

## S26 — TraceRepository.reserve_workflow_span

`backend/app/storage/trace_repository.py:102`

```python
def reserve_workflow_span(self, span):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            run=conn.execute('SELECT record FROM trace_runs WHERE id=?',(span.run_id,)).fetchone()
            if not run or json.loads(run['record']).get('kind')!='workflow' or not span.node_key:
                raise ValueError('Workflow span requires a real root and node key')
            if span.parent_span_id:
                parent=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(span.parent_span_id,)).fetchone()
                if not parent or parent['run_id'] != span.run_id: raise ValueError('Cross-run parent')
            attempt=conn.execute("SELECT COALESCE(MAX(json_extract(record,'$.node_attempt')),0)+1 FROM trace_spans WHERE run_id=? AND json_extract(record,'$.node_key')=?",(span.run_id,span.node_key)).fetchone()[0]
            span.node_attempt=attempt
            conn.execute('INSERT INTO trace_spans VALUES (?,?,?)',(span.span_id,span.run_id,span.model_dump_json()))
        return span
```

## S27 — TraceRepository.save_span

`backend/app/storage/trace_repository.py:116`

```python
def save_span(self, span):
        with closing(self.connect()) as conn, conn:
            if span.parent_span_id:
                parent=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(span.parent_span_id,)).fetchone()
                if not parent or parent['run_id']!=span.run_id: raise ValueError('Cross-run parent')
            previous=conn.execute('SELECT run_id,record FROM trace_spans WHERE id=?',(span.span_id,)).fetchone()
            if previous and (previous['run_id'] != span.run_id or TraceSpan.model_validate_json(previous['record']).status != 'running'):
                raise ValueError('Span is immutable after completion')
            if previous:
                old = TraceSpan.model_validate_json(previous['record'])
                if any(getattr(old,k) != getattr(span,k) for k in ('name','parent_span_id','node_key','node_attempt')):
                    raise ValueError('Span identity is immutable')
            conn.execute('INSERT INTO trace_spans VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                         (span.span_id,span.run_id,span.model_dump_json()))
```

## S28 — TraceRepository.event

`backend/app/storage/trace_repository.py:131`

```python
def event(self, event):
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if event.span_id:
                row=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(event.span_id,)).fetchone()
                if not row or row['run_id']!=event.run_id: raise ValueError('Cross-run event')
            existing=conn.execute('SELECT record FROM trace_events WHERE id=?',(event.event_id,)).fetchone()
            if existing:
                if existing['record'] != event.model_dump_json(): raise ValueError('Conflicting event identity')
                return
            run=conn.execute('SELECT record FROM trace_runs WHERE id=?',(event.run_id,)).fetchone()
            if run and json.loads(run['record']).get('kind') == 'workflow':
                sequence=conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM trace_events WHERE run_id=?',(event.run_id,)).fetchone()[0]
                if sequence > 256: raise ValueError('Workflow event limit reached')
                event.sequence=sequence
            conn.execute('INSERT INTO trace_events VALUES (?,?,?,?,?)',
                (event.event_id,event.run_id,event.span_id,event.sequence,event.model_dump_json()))
```

## S29 — TraceRepository.save_snapshot

`backend/app/storage/trace_repository.py:213`

```python
def save_snapshot(self, snapshot):
        if len(snapshot.model_dump_json().encode()) > 256*1024:
            raise ValueError('Controlled snapshot too large')
        with closing(self.connect()) as conn, conn:
            if snapshot.span_id:
                row=conn.execute('SELECT run_id FROM trace_spans WHERE id=?',(snapshot.span_id,)).fetchone()
                if not row or row['run_id'] != snapshot.run_id: raise ValueError('Cross-run snapshot')
            old=conn.execute('SELECT record FROM trace_snapshots WHERE run_id=? AND kind=?',
                             (snapshot.run_id,snapshot.kind)).fetchone()
            if old:
                if old['record'] != snapshot.model_dump_json(): raise ValueError('Snapshot is immutable')
                return
            conn.execute('INSERT INTO trace_snapshots VALUES (?,?,?,?,?)',
                (snapshot.snapshot_id,snapshot.run_id,snapshot.span_id,snapshot.kind,snapshot.model_dump_json()))
```

## S30 — TraceRepository.recover

`backend/app/storage/trace_repository.py:194`

```python
def recover(self):
        # Same single-process deployment boundary as the business recovery code.
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in conn.execute("SELECT record FROM trace_runs WHERE status IN ('queued','running')").fetchall():
                run=TraceRun.model_validate_json(row['record'])
                run.status,run.error_code,run.integrity='interrupted','TRACE_PROCESS_INTERRUPTED','incomplete'
                run.observation_revision += 1
                run.recovered_at=now()
                run.duration_ms=None
                conn.execute('UPDATE trace_runs SET status=?,record=? WHERE id=?',(run.status,run.model_dump_json(),run.run_id))
                for spanrow in conn.execute('SELECT record FROM trace_spans WHERE run_id=?',(run.run_id,)).fetchall():
                    span=TraceSpan.model_validate_json(spanrow['record'])
                    if span.status=='running':
                        span.status,span.error_code='interrupted','TRACE_PROCESS_INTERRUPTED'
                        span.recovered_at=run.recovered_at
                        span.duration_ms=None
                        conn.execute('UPDATE trace_spans SET record=? WHERE id=?',(span.model_dump_json(),span.span_id))
```

## S31 — WorkflowOrchestrator.trace_created

`backend/app/workflow/orchestrator.py:44`

```python
def trace_created(self, state):
        register_root(self.traces, state, self.intent_parser.parser,
                      self.real_planner.planner if self.real_planner else None)
```

## S32 — WorkflowOrchestrator.observed_node

`backend/app/workflow/orchestrator.py:48`

```python
async def observed_node(self, trace, name, node, request, guard=None):
        with trace.span(name, {'node_name': node.name}) as span:
            data = self.real_output(await node.run(request), guard)
            if name == 'intent_parser':
                span.attributes(next_action=data.next_action)
            elif name == 'analysis_planner':
                span.attributes(coverage_status=data.coverage_status,
                                executable_count=len(data.executable_task_ids), blocked_count=len(data.blocked_task_ids))
            elif name == 'data_profiler':
                span.attributes(dataset_id=data.dataset_id, dataset_version=data.dataset_version,
                                row_count=data.row_count, column_count=data.column_count)
            return data
```

## S33 — WorkflowOrchestrator.prepare_real

`backend/app/workflow/orchestrator.py:227`

```python
async def prepare_real(self, session_id):
        guard = {'revision': self.repository.get(session_id).revision}
        trace = preparation_context(self.traces, session_id)
        with bind_trace(trace):
            start_preparation(trace, guard['revision'])
            try:
                result = await self._prepare_real(session_id, trace, guard)
                checkpoint(trace, result)
                return result
            except AppError as error:
                if error.error.code == 'STALE_SESSION':
                    trace.event('workflow.callback_ignored', error_code='STALE_SESSION', session_revision=guard['revision'])
                    return self.repository.get(session_id)
                interrupt(trace, error)
                raise
            except BaseException as error:
                if self.repository.get(session_id).revision == guard['revision']:
                    interrupt(trace, error)
                else:
                    trace.event('workflow.callback_ignored', error_code='STALE_SESSION', session_revision=guard['revision'])
                raise
```

## S34 — WorkflowOrchestrator._prepare_real

`backend/app/workflow/orchestrator.py:249`

```python
async def _prepare_real(self, session_id, trace, guard):
        """Checkpointed real branch; approval/execution remain the existing services."""
        try:
            state = self.repository.get(session_id)
            if state.revision != guard['revision']:
                raise AppError('STALE_SESSION', '准备回调已过期，当前流程未修改。', 409)
            if state.workflow_kind != "real_v1":
                raise AppError("REAL_WORKFLOW_REQUIRED", "当前会话不属于真实Workflow。", 409)
            if state.status == S.CREATED:
                def start(current):
                    if current.status != S.CREATED:
                        raise AppError("WORKFLOW_ALREADY_STARTED", "该流程已经启动。", 409)
                    transition(current, S.PROFILING)
                    current.messages.append(Message(role="assistant", kind="status", content="正在解析上传文件并计算真实数据画像。"))
                state = self.preparation_mutate(session_id, start, guard)
            if state.status == S.PROFILING:
                profile = await self.observed_node(trace, 'data_profiler', self.data_profiler, NodeInput(session_id=session_id,
                    payload=ProfileInput(file=state.file, options=state.profile_options)), guard)
                def profiled(current):
                    current.profile = profile
                    current.dataset_ref = DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version)
                    transition(current, S.PARSING_INTENT)
                    current.messages.append(Message(role="assistant", kind="status", content=
                        f"真实画像完成：{profile.row_count}行、{profile.column_count}列；正在理解分析需求。"))
                state = self.preparation_mutate(session_id, profiled, guard)
            if state.status == S.PARSING_INTENT:
                ref = state.dataset_ref
                profile = self.datasets.profile(ref.dataset_id, ref.dataset_version)
                intent = await self.observed_node(trace, 'intent_parser', self.intent_parser, NodeInput(session_id=session_id,
                    payload=IntentInput(user_query=state.user_goal, profile=profile,
                                        clarification_answers=state.clarification_answers)), guard)
                if intent.next_action == "proceed" and (intent.llm is None or intent.parse_origin != "llm"):
                    raise AppError("REAL_INTENT_REQUIRED", "继续分析必须具备真实模型意图结果。", 409)
                def interpreted(current):
                    current.intent = intent
                    current.intent_history.append(intent)
                    current.analysis_mode = intent.analysis_mode
                    if intent.next_action == "clarify":
                        transition(current, S.WAITING_FOR_CLARIFICATION)
                        current.messages.append(Message(role="assistant", content="需要先补充以下信息：\n" +
                            "\n".join(intent.clarification_questions)))
                    else:
                        transition(current, S.PLANNING)
                        current.messages.append(Message(role="assistant", kind="status", content="需求已理解，正在生成受控分析计划。"))
                state = self.preparation_mutate(session_id, interpreted, guard)
            if state.status == S.WAITING_FOR_CLARIFICATION:
                return state
            if state.status == S.PLANNING:
                if self.real_planner is None:
                    raise AppError("PLANNER_NOT_AVAILABLE", "真实Planner尚未配置。", 503)
                ref = state.dataset_ref
                candidate = await self.observed_node(trace, 'analysis_planner', self.real_planner, NodeInput(session_id=session_id,
                    payload=PlannerV1Input(intent=state.intent, profile=self.datasets.profile(ref.dataset_id, ref.dataset_version))), guard)
                if candidate.llm is None or candidate.llm.is_mock:
                    raise AppError("REAL_PLANNER_REQUIRED", "真实流程必须使用真实模型计划。", 409)
                def planned(current):
                    current.planner_result = candidate
                    transition(current, S.VALIDATING)
                state = self.preparation_mutate(session_id, planned, guard)
            if state.status == S.VALIDATING:
                return self.save_generated_plan(session_id, guard)
            return state
        except NodeFailure as exc:
            return self.fail_real(session_id, exc.error, guard)
        except AppError as exc:
            if exc.error.code == 'STALE_SESSION':
                raise
            return self.fail_real(session_id, exc.error, guard)
        except Exception:
            return self.fail_real(session_id, WorkflowError(code="WORKFLOW_PREPARATION_FAILED",
                message="真实流程准备失败，已保存可用检查点，未使用示例结果替代。"), guard)
```

## S35 — WorkflowOrchestrator.save_generated_plan

`backend/app/workflow/orchestrator.py:321`

```python
def save_generated_plan(self, session_id, guard=None):
        # This adapter saves generated drafts; it does not change manual-import
        # goal matching, validation, approval or execution rules.
        with self.review.audit.transaction(session_id) as (conn, state):
            if guard is not None:
                self.review.revision_guard(state, guard['revision'])
            if state.workflow_kind != "real_v1" or state.status != S.VALIDATING or state.review_plan is not None:
                raise AppError("GENERATED_PLAN_STATE_INVALID", "当前状态不能保存生成计划。", 409)
            candidate = state.planner_result
            if candidate is None or candidate.llm is None or candidate.llm.is_mock:
                raise AppError("REAL_PLANNER_REQUIRED", "缺少真实模型计划检查点。", 409)
            checked = self.review.validate_v1(state, candidate.plan, candidate.intent_snapshot)
            record = PlanVersion(session_id=session_id, plan_id=checked.plan.plan_id, plan_version=1,
                dataset_id=checked.plan.dataset_id, dataset_version=checked.plan.dataset_version,
                validation_version=checked.validation_version, created_at=now(), change_type="created",
                change_summary="真实LLM生成计划；现有Validator重新校验，等待人工批准。", validated_plan=checked)
            self.review.audit.append_version(conn, record)
            state.review_plan = record
            state.current_plan_version = 1
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = "awaiting_review"
            transition(state, S.AWAITING_APPROVAL)
            state.messages.append(Message(role="assistant", kind="plan", plan_version=1,
                content=f"真实计划已保存，目标覆盖：{checked.coverage_status}。请审核任务、未满足需求和约束；批准前不会计算。"))
        if guard is not None:
            guard['revision'] = state.revision
        return state
```

## S36 — WorkflowOrchestrator.begin_real_clarification

`backend/app/workflow/orchestrator.py:350`

```python
def begin_real_clarification(self, session_id, answer, expected_revision):
        def resume(state):
            if state.workflow_kind != "real_v1" or state.status != S.WAITING_FOR_CLARIFICATION:
                raise AppError("CLARIFICATION_NOT_ALLOWED", "当前真实会话不在等待澄清。", 409)
            state.clarification_answers.append(answer)
            state.planner_result = None
            state.error = None
            state.messages.append(Message(role="user", content=answer))
            transition(state, S.PARSING_INTENT)
        return self.repository.mutate(session_id, resume, expected_revision)
```

## S37 — WorkflowOrchestrator.begin_real_retry

`backend/app/workflow/orchestrator.py:361`

```python
def begin_real_retry(self, session_id, expected_revision):
        def resume(state):
            if (state.workflow_kind != "real_v1" or state.status != S.FAILED or not state.error
                    or not state.error.retryable or state.review_plan is not None or state.engine_execution_ids):
                raise AppError("PREPARATION_RETRY_NOT_ALLOWED", "只能显式重试尚未批准、未执行的准备阶段失败。", 409)
            if state.planner_result is not None:
                target = S.VALIDATING
            elif state.intent is not None and state.intent.next_action == "proceed" and state.intent.clarification_answers == state.clarification_answers:
                target = S.PLANNING
            else:
                target = S.PARSING_INTENT if state.dataset_ref else S.PROFILING
            transition(state, target)
            state.error = None
            state.messages.append(Message(role="assistant", kind="status", content="按已保存检查点重试准备；不会自动批准或执行。"))
        return self.repository.mutate(session_id, resume, expected_revision)
```

## S38 — WorkflowOrchestrator.recover_interrupted

`backend/app/workflow/orchestrator.py:187`

```python
def recover_interrupted(self) -> None:
        # Single-process local deployment. HITL sessions remain resumable after restart.
        for item in self.repository.list():
            if (item["status"] in {S.PROFILING, S.PARSING_INTENT, S.PLANNING, S.VALIDATING} or
                    item["status"] == S.CREATED and self.repository.get(item["id"]).workflow_kind == "real_v1"):
                self.fail_real(item["id"], WorkflowError(code="PROCESS_INTERRUPTED", retryable=True,
                    message="服务重启中断了准备阶段，已有检查点已保存；请点击重试准备，不会自动执行。"))
            elif item["status"] in {S.PREPARING, S.RUNNING}:
                self.fail(item["id"], WorkflowError(code="PROCESS_INTERRUPTED",
                    message="上次处理因服务重启中断，请新建会话重新提交。"))
```

## S39 — DataProfilerService.profile

`backend/app/services/data_profiler.py:15`

```python
def profile(self, file: FileInfo, options: ProfileOptions | None = None) -> DatasetProfile:
        content = self.files.read(file)
        profile = build_profile(content, file.extension, file.id, file.name, options)
        return self.datasets.save(file, profile)
```

## S40 — IntentParserService.parse

`backend/app/services/intent_parser.py:69`

```python
async def parse(self, user_query: str, profile: DatasetProfile | None,
                    clarification_answers: list[str] | None = None) -> IntentArtifact:
        context = build_dataset_context(profile)
        if (not isinstance(user_query, str) or
                (clarification_answers is not None and (not isinstance(clarification_answers, list) or
                 len(clarification_answers) > 10 or any(not isinstance(x, str) or len(x) > 2000 for x in clarification_answers)))):
            raise AppError("INTENT_INPUT_INVALID", "需求和澄清答复必须是规定长度内的文本。", 422)
        answers = list(clarification_answers or [])
        sources = [user_query, *answers]
        try:
            for source in sources:
                source.encode("utf-8")
        except UnicodeError:
            raise AppError("INTENT_INPUT_INVALID", "需求或澄清答复包含无效 Unicode 文本。", 422) from None
        if len(user_query) > 2000 or sum(map(len, sources)) > 8000:
            raise AppError("INTENT_INPUT_TOO_LONG", "需求或累计澄清内容过长。", 422)
        dataset_ref = DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version)
        parse_id, attempts = uuid4().hex, 0
        trace = current_trace()
        if trace and trace.active:
            trace.active.attributes(operation_id=parse_id)

        def artifact(result, response=None):
            return IntentArtifact(**result.model_dump(), user_query=user_query, clarification_answers=answers,
                dataset_ref=dataset_ref, parse_origin="llm" if response else "input_guard",
                llm=LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock) if response else None,
                parser_version="1.1", prompt_version=PROMPT_VERSION, llm_attempts=attempts, parse_id=parse_id,
                provenance=Provenance(source=("mock" if response.is_mock else "llm") if response else "input_guard",
                    dataset=profile.dataset_id, dataset_version=profile.dataset_version,
                    notice="结构化意图识别；约束未验证，未生成任务或计算结果。" if response else "空输入校验：等待用户补充，未调用模型。"))

        if not any(source.strip() for source in sources):
            logger.info("Intent requires input", extra={"event": "intent_guard", "parse_id": parse_id,
                "attempt": 0, "prompt_version": PROMPT_VERSION})
            return artifact(ParsedIntent.model_validate({
                "analysis_mode": "undetermined", "next_action": "clarify",
                "analysis_goal": {"analysis_object": None, "business_goal": None, "decision_goal": None},
                "constraints": {"time_range": None, "filters": [], "metric_requirements": [], "analysis_limits": []},
                "uncertainties": [{"id": "missing_query", "issue": "尚未提供分析需求。",
                    "reason": "无法确定需要开展什么分析。", "action": "clarify", "resolve_at": "before_planning"}],
                "clarification_questions": ["你希望分析什么问题，还是先探索这份数据的主要特征和规律？"]}))

        data = {"user_query": user_query, "clarification_answers": answers, "dataset_context": context.model_dump()}
        failure = None
        try:
            # One total deadline, including validation retries. A retry never doubles the timeout.
            async with asyncio.timeout(self.timeout_seconds):
                for attempts in range(1, self.max_attempts + 1):
                    instruction_data = dict(data)
                    if failure:
                        instruction_data["validation_feedback"] = {"previous_error_code": failure.error.code,
                            "stage": failure.error.details.get("stage", "call"),
                            "instruction": INTENT_RETRY_INSTRUCTION}
                        if failure.error.code == "LLM_UNGROUNDED_OUTPUT":
                            instruction_data["validation_feedback"]["instruction"] = GROUNDING_RETRY_INSTRUCTION
                    instruction = json.dumps(instruction_data, ensure_ascii=False)
                    if len(instruction.encode("utf-8")) > MAX_REQUEST_BYTES:
                        raise AppError("INTENT_REQUEST_TOO_LARGE", "当前意图上下文请求超过 96 KiB，未发送本次调用。", 422,
                            details={"stage": "input", "attempts": attempts - 1, "parse_id": parse_id})
                    request = LLMRequest(purpose="intent_v1", system_prompt=SYSTEM_PROMPT,
                        instruction=instruction, response_schema=ParsedIntent.model_json_schema(),
                        enable_thinking=self.enable_thinking,
                        call_binding=self.prompt_source.binding(parse_id,attempts,trace=trace,retry_reason=failure.error.code if failure else None) if self.prompt_source else None)
                    try:
                        response = await self._generate(request)
                        result = validate_output(response.text, sources)
                    except AppError as exc:
                        exc.error.details = {"stage": "call", **exc.error.details, "attempts": attempts, "parse_id": parse_id}
                        logger.info("Intent attempt failed", extra={"event": "intent_attempt", "parse_id": parse_id,
                            "stage": exc.error.details["stage"], "error_code": exc.error.code, "attempt": attempts,
                            "prompt_version": PROMPT_VERSION})
                        if exc.error.code not in RETRYABLE or attempts == self.max_attempts:
                            raise
                        failure = exc
                        continue
                    except Exception:
                        raise AppError("LLM_CALL_FAILED", "模型调用失败，未生成意图结果。", 502,
                            details={"stage": "call", "attempts": attempts, "parse_id": parse_id}) from None
                    logger.info("Intent parsed", extra={"event": "intent_success", "parse_id": parse_id,
                        "attempt": attempts, "prompt_version": PROMPT_VERSION})
                    return artifact(result, response)
        except TimeoutError:
            logger.info("Intent timed out", extra={"event": "intent_attempt", "parse_id": parse_id,
                "stage": "call", "error_code": "LLM_TIMEOUT", "attempt": attempts, "prompt_version": PROMPT_VERSION})
            raise AppError("LLM_TIMEOUT", "意图模型调用超过总时间限制，未生成意图结果。", 504,
                details={"stage": "call", "attempts": attempts, "parse_id": parse_id}) from None
        raise AssertionError("Intent retries exhausted without an outcome")
```

## S41 — AnalysisPlannerService.plan

`backend/app/services/analysis_planner.py:48`

```python
async def plan(self, intent: ParsedIntent, profile: DatasetProfile) -> ValidatedAnalysisPlan:
        try:
            clean_intent = ParsedIntent.model_validate({key: getattr(intent, key) for key in ParsedIntent.model_fields})
        except (ValidationError, AttributeError, ValueError):
            raise AppError('PLANNER_INTENT_INVALID', '分析意图结构或流程规则无效。', 422) from None
        if clean_intent.next_action != 'proceed':
            raise AppError('INTENT_CLARIFICATION_REQUIRED', '意图仍需澄清，不能生成分析计划。', 409)
        if isinstance(intent, IntentArtifact) and (intent.dataset_ref.dataset_id, intent.dataset_ref.dataset_version) != (profile.dataset_id, profile.dataset_version):
            raise AppError('INTENT_DATASET_MISMATCH', '意图与画像的数据集版本不一致。', 409)
        context, requirements = planner_context(clean_intent, profile, self.registry)
        parse_id, attempts, failure = uuid4().hex, 0, None
        trace = current_trace()
        if trace and trace.active:
            trace.active.attributes(operation_id=parse_id)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                for attempts in range(1, self.max_attempts + 1):
                    data = dict(context)
                    if failure:
                        data['validation_feedback'] = {'code': failure.error.code,
                            'instruction': PLANNER_RETRY_INSTRUCTION}
                    instruction = json.dumps(data, ensure_ascii=False)
                    if len(instruction.encode('utf-8')) > 132 * 1024:
                        raise AppError('PLANNER_CONTEXT_TOO_LARGE', '规划请求过大。', 422, details={'stage': 'input'})
                    request = LLMRequest(purpose='analysis_planner_v1', system_prompt=SYSTEM_PROMPT,
                        instruction=instruction, response_schema=request_schema(self.registry),
                        enable_thinking=self.enable_thinking,
                        call_binding=self.prompt_source.binding(parse_id,attempts,trace=trace,retry_reason=failure.error.code if failure else None) if self.prompt_source else None)
                    try:
                        try:
                            response = await self.provider.generate(request)
                        except AppError as exc:
                            code = exc.error.code if exc.error.code in PROVIDER_CODES else 'PLANNER_LLM_CALL_FAILED'
                            status = exc.status if code in PROVIDER_CODES else 502
                            raise AppError(code, '规划模型调用未成功，未生成计划。', status,
                                           details={'stage': 'call'}) from None
                        except TimeoutError:
                            raise AppError('LLM_TIMEOUT', '规划模型调用超时。', 504, details={'stage': 'call'}) from None
                        except Exception:
                            raise AppError('PLANNER_LLM_CALL_FAILED', '规划模型调用失败。', 502, details={'stage': 'call'}) from None
                        draft = validate_draft(response.text, self.registry)
                    except AppError as exc:
                        exc.error.details.update(attempts=attempts, parse_id=parse_id, prompt_version=PROMPT_VERSION)
                        logger.info('Planner attempt failed', extra={'parse_id': parse_id, 'attempt': attempts,
                            'error_code': exc.error.code, 'prompt_version': PROMPT_VERSION})
                        if exc.error.code not in RETRYABLE or attempts == self.max_attempts:
                            raise
                        failure = exc
                        continue
                    break
        except TimeoutError:
            raise AppError('LLM_TIMEOUT', '规划调用超过总时间限制。', 504,
                           details={'stage': 'call', 'attempts': attempts, 'parse_id': parse_id,
                                    'prompt_version': PROMPT_VERSION}) from None
        plan = AnalysisPlan(plan_id='plan_' + uuid4().hex, dataset_id=profile.dataset_id,
            dataset_version=profile.dataset_version, plan_version=1, tasks=draft.tasks,
            core_requirements=requirements)
        # Exactly one deterministic validation. No LLM repair of F0 or deleting tasks.
        with trace.span('plan_validator', {'validation_role':'planner_output'}) if trace else nullcontext() as validation_span:
            validated = self.validator.validate(plan, profile)
            if trace:
                validation_span.attributes(coverage_status=validated.coverage_status,
                    executable_count=len(validated.executable_task_ids), blocked_count=len(validated.blocked_task_ids))
        logger.info('Planner validated', extra={'parse_id': parse_id, 'attempts': attempts,
            'prompt_version': PROMPT_VERSION, 'coverage_status': validated.coverage_status})
        return validated.model_copy(update={
            'intent_snapshot': clean_intent,
            'llm': LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock),
            'provenance': Provenance(source='mock' if response.is_mock else 'llm', dataset=profile.dataset_id,
                dataset_version=profile.dataset_version, plan_version=1,
                notice=f'Prompt={PROMPT_VERSION}; attempts={attempts}; 模型草案经技术校验，不代表业务约束已核实或用户批准，未执行统计。')})
```

## S42 — PlanReviewService.validate_v1

`backend/app/services/plan_review.py:113`

```python
def validate_v1(self, state, plan, intent):
        from contextlib import nullcontext
        from app.observability.context import current_trace
        from app.planning.validator import PlanValidator
        ref = state.dataset_ref
        if ref is None or state.file.id != plan.dataset_id or (ref.dataset_id, ref.dataset_version) != (plan.dataset_id, plan.dataset_version):
            raise AppError("DATASET_VERSION_MISMATCH", "计划必须使用当前会话上传的数据集及准确版本。", 409)
        trace = current_trace()
        with trace.span('plan_validator', {'validation_role':'initial_plan_save'}) if trace else nullcontext() as validation_span:
            checked = PlanValidator(self.registry).validate(plan, self.datasets.profile(plan.dataset_id, plan.dataset_version))
            if trace:
                validation_span.attributes(coverage_status=checked.coverage_status, validation_version=checked.validation_version,
                    executable_count=len(checked.executable_task_ids), blocked_count=len(checked.blocked_task_ids))
        checked.intent_snapshot = intent
        return checked
```

## S43 — PlanReviewService.revise_v1

`backend/app/services/plan_review.py:169`

```python
def revise_v1(self, session_id, request):
        from app.domain.plan_review import PlanVersion
        with self.audit.transaction(session_id) as (conn, state):
            self.revision_guard(state, request.expected_revision)
            old = self.current_guard(state, request)
            if request.instruction.strip():
                raise AppError("AI_REVISION_NOT_AVAILABLE", "自然语言修订尚未接入 LLM；当前仅支持删除任务并确定性重新校验。", 501)
            plan = old.validated_plan.plan.model_copy(deep=True)
            ids = set(request.remove_task_ids)
            if not ids or not ids <= {t.task_id for t in plan.tasks}:
                raise AppError("TASK_NOT_FOUND", "待删除任务不存在。", 422)
            plan.tasks = [t for t in plan.tasks if t.task_id not in ids]
            plan.plan_version += 1
            state.review_status = "validating"
            checked = self.validate_v1(state, plan, old.validated_plan.intent_snapshot)
            record = PlanVersion(session_id=session_id, plan_id=plan.plan_id, plan_version=plan.plan_version,
                dataset_id=plan.dataset_id, dataset_version=plan.dataset_version, validation_version=checked.validation_version,
                created_at=now(), change_type="tasks_deleted", change_summary="删除任务：" + ", ".join(sorted(ids)), validated_plan=checked)
            self.audit.append_version(conn, record)
            state.review_plan = record
            state.current_plan_version = plan.plan_version
            state.approved_plan_version = None
            state.engine_approval = None
            state.review_status = "awaiting_approval"
            state.status = S.AWAITING_APPROVAL
            state.messages.append(Message(role="user", content=record.change_summary))
            state.messages.append(Message(role="assistant", kind="status", content=f"计划 v{plan.plan_version} 已重新校验，目标覆盖：{checked.coverage_status}。"))
        return state
```

## S44 — PlanReviewService.approve_v1

`backend/app/services/plan_review.py:273`

```python
def approve_v1(self, session_id, request):
        from app.domain.execution import ApprovedExecutionSnapshot
        from app.domain.plan_review import ReviewApproval
        with self.audit.transaction(session_id) as (conn, state):
            record = self.current_guard(state, request)
            if not request.approval_request_id:
                raise AppError("APPROVAL_REQUEST_ID_REQUIRED", "确认操作需要唯一请求 ID；重试必须复用此 ID。", 422)
            previous = conn.execute("SELECT request, record FROM plan_approvals WHERE session_id=? AND request_id=?",
                                    (session_id, request.approval_request_id)).fetchone()
            if previous:
                if previous["request"] != request.model_dump_json():
                    raise AppError("APPROVAL_REQUEST_CONFLICT", "审批请求 ID 已用于不同参数。", 409)
                if state.engine_approval is None or state.engine_approval.approval_id != json.loads(previous["record"])["approval_id"]:
                    raise AppError("APPROVAL_SUPERSEDED", "原审批已不再是当前有效审批。", 409)
                return state
            self.revision_guard(state, request.expected_revision)
            if state.approved_plan_version == record.plan_version:
                raise AppError("ALREADY_APPROVED", "当前版本已批准；请继续执行。", 409)
            if (request.dataset_id, request.dataset_version) != (record.dataset_id, record.dataset_version):
                raise AppError("DATASET_VERSION_MISMATCH", "确认的数据集版本与当前计划不一致。", 409)
            checked = self.validate_v1(state, record.validated_plan.plan, record.validated_plan.intent_snapshot)
            saved = record.validated_plan
            if request.validation_version != saved.validation_version or checked.model_dump() != saved.model_dump():
                raise AppError("PLAN_VALIDATION_STALE", "计划校验已失效，需要重新校验和审核。", 409)
            intent = checked.intent_snapshot
            if intent.next_action != "proceed" or any(u.action in {"clarify", "defer"} for u in intent.uncertainties):
                raise AppError("BLOCKING_UNCERTAINTY", "仍有待澄清或待解决的不确定性，不能以确认替代解决。", 409)
            constraints = intent.constraints
            constraint_audit = self.constraint_audit(checked)
            if not constraint_audit.all_verified:
                raise AppError("UNVERIFIED_CONSTRAINTS", "分析条件未能与当前步骤完整对应，请明确范围或口径后重新提出需求。", 409,
                    details={'unverified': [item.model_dump(mode='json') for item in constraint_audit.items if item.status != 'verified']})
            if checked.coverage_status == "blocked":
                raise AppError("COVERAGE_BLOCKED", "核心业务目标覆盖不足，不能批准。", 422)
            if not checked.executable_task_ids:
                raise AppError("NO_EXECUTABLE_TASKS", "至少需要一个可执行任务。", 422)
            required = self.warning_ids(checked)
            if set(request.acknowledged_warnings) != set(required):
                raise AppError("WARNINGS_NOT_ACKNOWLEDGED", "请明确确认当前计划全部重要限制。", 422, details={"required_warnings": required})
            snapshot = ApprovedExecutionSnapshot(approval_id="approval_" + uid(), approved_at=now(),
                session_id=session_id, validated_plan=checked, intent=intent, acknowledged_warnings=required,
                constraints_confirmed=bool(constraints.time_range or constraints.filters or constraints.metric_requirements or constraints.analysis_limits) and constraint_audit.all_verified)
            approval = ReviewApproval(approval_id=snapshot.approval_id, approval_request_id=request.approval_request_id,
                session_id=session_id, plan_id=record.plan_id, plan_version=record.plan_version,
                validation_version=record.validation_version, dataset_id=record.dataset_id, dataset_version=record.dataset_version,
                approved_at=snapshot.approved_at, acknowledged_warnings=required, snapshot=snapshot)
            conn.execute("INSERT INTO plan_approvals VALUES (?, ?, ?, ?, ?)",
                (approval.approval_id, session_id, request.approval_request_id, request.model_dump_json(), approval.model_dump_json()))
            conn.execute('INSERT INTO plan_constraint_audits VALUES (?, ?, ?)',
                (approval.approval_id, session_id, json.dumps({'approval_id': approval.approval_id, 'session_id': session_id,
                    'approved_at': snapshot.approved_at, 'audit': constraint_audit.model_dump(mode='json')}, ensure_ascii=False)))
            state.engine_approval = snapshot
            state.approved_plan_version = record.plan_version
            state.status = S.APPROVED
            state.review_status = "approved"
            state.messages.append(Message(role="user", content=f"确认真实计划 v{record.plan_version} 并执行；已确认限制：{', '.join(required) or '无'}。"))
        return state
```

## S45 — AnalysisEngineService.execute

`backend/app/services/analysis_engine.py:94`

```python
def execute(self, request: ExecutionRequest) -> ExecutionResultV1:
        request = ExecutionRequest.model_validate(request.model_dump())
        replay = self.executions.replay(request)
        if replay is not None: return replay
        state = self.sessions.get(request.session_id)
        checked = self.check_approval(state,request)
        plan = checked.plan
        loaded = self.loader.load(plan.dataset_id,plan.dataset_version)
        claim = self.executions.claim(request,state.revision,self.check_approval)
        if isinstance(claim, ExecutionResultV1): return claim
        timer, tasks = perf_counter(), []
        remaining_bytes, remaining_cells = 256 * 1024, 100_000
        validation = {v.task_id:v for v in checked.validation_results}
        for task in plan.tasks:
            result = validation[task.task_id]
            if not result.executable:
                issue = result.validation_issues[0] if result.validation_issues else None
                output = self.skipped(task.task_id,result.reason_code,
                    issue.message if issue else "该任务不能执行。",issue.step_id if issue else None)
                columns, rows, used = None, None, 0
            else:
                output, columns, rows, used = self.runner.run(task,loaded,remaining_bytes,remaining_cells)
            self.executions.save_task(claim["execution_id"],output,columns,rows)
            tasks.append(output)
            remaining_bytes -= used
            if output.result: remaining_cells -= len(output.result.rows) * len(output.result.columns)
        result = self.outcome(claim["execution_id"],request,claim["approval"],claim["started_at"],tasks,
            (perf_counter()-timer)*1000,warnings=[i.message[:2000] for i in loaded.profile.quality_issues[:20]])
        self.executions.finish(result)
        return result
```

## S46 — AnalysisEngineService.recover_interrupted

`backend/app/services/analysis_engine.py:125`

```python
def recover_interrupted(self):
        # Existing deployment is explicitly single-process. Never resume/replay calculations automatically.
        for record in self.executions.running():
            request = ExecutionRequest.model_validate_json(record["request"])
            approval = ApprovedExecutionSnapshot.model_validate_json(record["approval"])
            import json
            completed = [ExecutedTask.model_validate(item) for item in json.loads(record["progress"])]
            completed_ids = {task.task_id for task in completed}
            tasks = completed + [self.skipped(task.task_id,"EXECUTION_INTERRUPTED","服务中断，该任务没有已保存的完成结果。")
                                 for task in approval.validated_plan.plan.tasks if task.task_id not in completed_ids]
            elapsed = max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(record["started_at"])).total_seconds()*1000)
            result = self.outcome(record["id"],request,approval,record["started_at"],tasks,elapsed,
                warnings=["服务重启中断执行；保留已保存结果，未自动重跑。"],
                extra_errors=[ExecutionError(code="EXECUTION_INTERRUPTED",message="执行因服务中断结束。")])
            self.executions.finish(result)
```

## S47 — TaskRunner.run

`backend/app/execution/task_runner.py:87`

```python
def run(self, task, loaded, preview_bytes, preview_cells):
        started, timer = now(), perf_counter()
        frame = loaded.frame.copy(deep=True)
        fields = {f.field_id: FieldState(f.logical_type, f.non_missing_count) for f in loaded.profile.fields}
        reserved, normalized = set(fields), set()
        logs, warnings, metrics = [], [], {}
        labels = {f.field_id: f.display_name for f in loaded.profile.fields}
        effective, aggregated, metric_valid = len(frame), False, {}
        step_id = None
        try:
            for step in task.steps:
                step_id, step_timer, input_rows = step.step_id, perf_counter(), len(frame)
                try:
                    spec = self.registry.operations.get(step.operation)
                    if spec is None:
                        raise TaskDataError("UNSUPPORTED_OPERATION", "该操作未在当前能力目录中实现。")
                    params = spec.params_model.model_validate(step.params)
                    new_fields = self.registry.propagate(step.operation, params, fields, reserved)
                    needed = [name for name in dict.fromkeys(references(params)) if name not in normalized and name in loaded.frame.columns]
                    normalize_fields(frame, needed, fields)
                    normalized.update(needed)
                    if isinstance(params, AggregateParams):
                        if not aggregated: effective = len(frame)
                        aggregated = True
                        metrics = {m.alias:m for m in params.metrics}
                        metric_valid = {m.alias: len(frame) if m.field is None else int(frame[m.field].count()) for m in params.metrics}
                        functions = {"count":"计数", "distinct_count":"去重计数", "sum":"合计", "avg":"均值", "median":"中位数", "min":"最小值", "max":"最大值"}
                        for metric in params.metrics:
                            labels[metric.alias] = (labels.get(metric.field, "记录")[:1800] + " · " + functions[metric.function])[:2000]
                    elif isinstance(params, DeriveParams):
                        labels[params.alias] = labels.get(params.field, params.field)[:1800] + (" · 年份" if params.function == "extract_year" else " · 月份")
                    result = spec.handler(frame, params, {name:state.kind for name,state in fields.items()})
                    if not isinstance(result, pd.DataFrame) or list(result.columns) != list(new_fields):
                        raise TaskDataError("INVALID_RESULT_SCHEMA", "计算内核输出字段与能力目录不一致。")
                    # Validate numeric intermediates before another step can hide an
                    # overflow or consume a rounded nullable integer produced by Pandas.
                    for name, state in new_fields.items():
                        if state.kind in {L.INTEGER, L.NUMBER} and (name in normalized or name not in loaded.frame.columns):
                            for value in result[name]:
                                scalar(value, state.kind)
                    frame, fields = result, new_fields
                    reserved.update(fields)
                    step_warnings = ["本步骤结果为空，仍按成功记录。"] if frame.empty else []
                    logs.append(StepExecutionLog(step_id=step_id, operation=step.operation, status="success",
                        input_row_count=input_rows, output_row_count=len(frame), duration_ms=(perf_counter()-step_timer)*1000,
                        warnings=step_warnings))
                except Exception as exc:
                    error = task_error(exc, task.task_id, step_id)
                    logs.append(StepExecutionLog(step_id=step_id, operation=step.operation, status="failed",
                        input_row_count=input_rows, output_row_count=None, duration_ms=(perf_counter()-step_timer)*1000, error=error))
                    raise TaskDataError(error.code, error.message) from None
            if not aggregated: effective = len(frame)
            remaining = [name for name in frame.columns if name in loaded.frame.columns and name not in normalized]
            normalize_fields(frame, remaining, fields)
            columns = [ResultColumn(field=name, label=labels.get(name,name)[:2000], logical_type=state.kind,
                role="metric" if name in metrics else "dimension",
                unit="条" if name in metrics and metrics[name].function in {"count","distinct_count"} else None) for name,state in fields.items()]
            rows = [{name:scalar(value, fields[name].kind) for name,value in zip(frame.columns, values)}
                    for values in frame.itertuples(index=False, name=None)]
            # Full rows are persisted separately. Preview is a bounded prefix, never a computation input.
            preview, used = [], 0
            for row in rows[:min(100, preview_cells // max(1,len(columns)))]:
                size = len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode())
                if used + size > preview_bytes: break
                preview.append(row); used += size
            result_id = "result_" + uid()
            table = ResultTable(result_id=result_id, columns=columns, rows=preview,
                truncated=len(preview) != len(rows), total_result_rows=len(rows))
            counts = set(metric_valid.values())
            valid_count = next(iter(counts)) if len(counts) == 1 else (effective if not aggregated else None)
            if len(preview) < len(rows): warnings.append("响应仅包含预览；完整结果已保存，不能把预览行数当作完整行数。")
            metadata = TaskExecutionMetadata(input_row_count=len(loaded.frame), started_at=started, finished_at=now(),
                duration_ms=(perf_counter()-timer)*1000, preview_row_count=len(preview), metric_valid_counts=metric_valid,
                steps=logs, warnings=warnings)
            output = ExecutedTask(task_id=task.task_id, status="success", result=table, result_id=result_id,
                result_ref=result_id, row_count=len(rows), effective_row_count=effective, valid_sample_count=valid_count,
                sample_definition="聚合前各最终指标的非缺失参与数；指标样本数不同时不提供统一有效样本量。" if aggregated else "结果保留记录数；未执行通用整行缺失剔除。",
                scope="指定数据集版本内，按批准任务的筛选和选择操作限定的范围。",
                calculation="批准操作链：" + " → ".join(s.operation for s in task.steps), failure_reason=None,
                execution_metadata=metadata)
            return output, [column.model_dump(mode="json") for column in columns], rows, used
        except Exception as exc:
            error = task_error(exc, task.task_id, step_id)
            return ExecutedTask(task_id=task.task_id, status="failed", result=None,
                effective_row_count=effective, valid_sample_count=None, sample_definition="任务未完成，不提供有效样本量。",
                scope="指定数据集版本", calculation="任务未完成，未生成统计结果。", failure_reason=error.message,
                error=error, execution_metadata=TaskExecutionMetadata(input_row_count=len(loaded.frame), started_at=started,
                    finished_at=now(), duration_ms=(perf_counter()-timer)*1000, preview_row_count=0, steps=logs)), None, None, 0
```

## S48 — AnalysisReportService.generate

`backend/app/services/analysis_report.py:39`

```python
async def generate(self, intent: ParsedIntent, validated: ValidatedAnalysisPlan,
                       execution: ExecutionResultV1, profile: DatasetProfile, *, approved_snapshot=None, original_query=None, trace=None) -> AnalysisReport:
        trace = trace or TraceContext(TraceRecorder())
        # Reparse all input instances; neither model_copy nor caller validation claims are trusted.
        try:
            intent = type(intent).model_validate(intent.model_dump())
            execution = ExecutionResultV1.model_validate(execution.model_dump())
            validated = ValidatedAnalysisPlan.model_validate(validated.model_dump())
            profile = DatasetProfile.model_validate(profile.model_dump())
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise AppError("REPORT_INPUT_INVALID", "报告输入结构不正确，未生成报告。", 422) from None
        if len(execution.model_dump_json().encode()) > 4 * 1024 * 1024:
            raise AppError("REPORT_INPUT_TOO_LARGE", "计算结果过大，请缩小返回结果范围并明确截断信息。", 422)
        checked, descriptions = prepare(intent, validated, execution, profile, self.registry)
        tasks = {task.task_id: task for task in checked.plan.tasks}
        with trace.span('evidence_builder') as stage:
            evidence = EvidenceBuilder().build(execution, profile, descriptions)
            stage.attributes(evidence_count=len(evidence))
            trace.snapshot('evidence',[e.model_dump(mode='json') for e in evidence],lambda:evidence_projection(evidence))
        # Stable task priority ordering, retaining evidence IDs and row references.
        evidence.sort(key=lambda item: (tasks[item.task_id].priority, item.evidence_id))
        evidenced_tasks = {item.task_id for item in evidence}
        uncompleted = [UncompletedTask(task_id=t.task_id, title=tasks[t.task_id].title,
            priority=tasks[t.task_id].priority,
            reason=t.failure_reason or "结果没有可用于报告的有效数据证据。")
            for t in execution.tasks if t.status != "success" or t.task_id not in evidenced_tasks]
        core_tasks = [task for task in tasks.values() if task.priority == "P0"]
        core_success = [task for task in core_tasks if task.task_id in evidenced_tasks]
        coverage = "blocked" if not core_success else ("partial" if checked.coverage_status != "complete" or len(core_success) < len(core_tasks) else "complete")
        confirmed, resolved = False, set()
        if approved_snapshot is not None:
            from app.domain.execution import ApprovedExecutionSnapshot
            approved = ApprovedExecutionSnapshot.model_validate(approved_snapshot.model_dump())
            plain = ParsedIntent.model_validate({key: getattr(intent, key) for key in ParsedIntent.model_fields})
            if (execution.source != "engine" or approved.status != "approved" or
                    approved.approval_id != execution.approval_id or approved.session_id != execution.session_id or
                    approved.validated_plan != validated or approved.intent != plain):
                raise AppError("REPORT_APPROVAL_MISMATCH", "报告输入与批准快照不一致。", 422)
            confirmed = approved.constraints_confirmed
            resolved = set(approved.resolved_uncertainty_ids)
        unresolved = [u for u in intent.uncertainties if u.id not in resolved]
        constraints = intent.constraints
        pending = ([constraints.time_range] if constraints.time_range else []) + constraints.filters + constraints.metric_requirements + constraints.analysis_limits
        if coverage == "complete" and ((pending and not confirmed) or any(u.action == "defer" for u in unresolved)):
            coverage = "partial"
        limitations = ["结论仅适用于上传样本与本次分析范围，不能直接代表整体市场或总体人群。",
            "业务解释和行动建议采用谨慎表述，未经过严格事实验证，也不构成因果结论。"]
        if execution.source == "imported":
            limitations.append("计算结果由上游导入；报告模块核对版本、结构与证据一致性，未复算源数据。")
        limitations.extend(issue.message[:2000] for issue in profile.quality_issues[:20])
        used_metrics = {metric.field for desc in descriptions.values() for metric in desc.metrics.values() if metric.field}
        limitations.extend(f'上传范围内，{field.display_name[:100]}有 {field.missing_count} 条缺失；这不是本任务筛选范围的有效样本量，指标有效记录以执行口径为准。'
            for field in profile.fields if field.field_id in used_metrics and field.missing_count)
        limitations.extend(f'未完成任务：{t.title[:300]}；{t.reason[:600]}' for t in uncompleted)
        limitations.extend(f"待解决事项：{u.description}"[:2000] for u in unresolved)
        limitations.extend(f"需求约束尚需对照执行口径确认：{item.raw_text}"[:2000] for item in pending if not confirmed)
        for t in execution.tasks:
            if t.result and t.result.truncated:
                limitations.append(f"{tasks[t.task_id].title[:200]}：仅返回部分结果，不能据此推断未返回分组的排名或总体占比。")
            if t.result and any(step.operation == "top_n" for step in tasks[t.task_id].steps):
                limitations.append(f"{tasks[t.task_id].title[:200]}：任务含 Top N 选择，不能仅凭返回表格确认所有分组均已覆盖。")
        charts = VisualizationBuilder().build(execution, descriptions, evidence, tasks, intent)
        charts.sort(key=lambda chart: (tasks[chart.task_id].priority, chart.chart_id))
        from app.review.presentation import PlanPresentationMapper
        mapper = PlanPresentationMapper(profile)
        llm, insights, rejected_insights, text_validation = None, [], [], []
        missing_core_metrics = []
        if evidence:
            # Only bounded structured evidence, never all result rows / raw dataset.
            selected = select_evidence(evidence, tasks)
            payload = {"analysis_goal": intent.analysis_goal.model_dump(), "goal_coverage": coverage,
                "original_query": (original_query or intent.analysis_goal.business_goal or '')[:2000],
                "constraints": intent.constraints.model_dump(), "constraints_confirmed": confirmed,
                "scope_context": [{"task_id": t.task_id, "approved_steps": mapper.steps(t)} for t in tasks.values()],
                "fields": [{"field_id": f.field_id, "name": f.display_name, "logical_type": f.logical_type,
                            "upload_missing_count": f.missing_count} for f in profile.fields],
                "uncompleted_tasks": [t.model_dump() for t in uncompleted],
                "task_sample_context": [{"task_id": t.task_id, "status": t.status,
                    "valid_sample_count": t.valid_sample_count, "sample_definition": t.sample_definition,
                    "metric_valid_counts": t.execution_metadata.metric_valid_counts if t.execution_metadata else {}}
                    for t in execution.tasks],
                "tasks": [{"task_id": t.task_id, "priority": t.priority, "business_question": t.business_question}
                          for t in tasks.values() if t.task_id in evidenced_tasks],
                "evidence": [item.model_dump() for item in selected],
                "evidence_groups": [{"task_id": tid, "data_ref": ref, "result_field": field,
                    "evidence_ids": [e.evidence_id for e in selected if (e.task_id, e.data_ref, e.result_field) == (tid, ref, field)]}
                    for tid, ref, field in dict.fromkeys((e.task_id, e.data_ref, e.result_field) for e in selected)],
                "limitations": limitations}
            instruction = json.dumps(payload, ensure_ascii=False)
            if len(instruction.encode()) > 160 * 1024:
                raise AppError("REPORT_CONTEXT_TOO_LARGE", "证据上下文过大，未调用模型。", 422)
            request = LLMRequest(purpose="report_insights_v1", system_prompt=SYSTEM_PROMPT,
                instruction=instruction, response_schema=request_schema(selected), enable_thinking=self.enable_thinking)
            with trace.span('insight_generator', {'purpose': request.purpose, 'input_bytes': len(instruction.encode()),
                    'selected_evidence_count': len(selected), 'evidence_refs': [e.evidence_id for e in selected], 'candidate_count': None,
                    'timeout_seconds': self.timeout_seconds, 'enable_thinking': self.enable_thinking}) as generation:
                try:
                    if self.prompt_source:
                        request = request.model_copy(update={'call_binding':self.prompt_source.binding(uuid4().hex,trace=trace)})
                    generation.event('llm.started', purpose=request.purpose)
                    response = await asyncio.wait_for(self.provider.generate(request), timeout=self.timeout_seconds)
                    trace.snapshot('llm_output',response.text,lambda:llm_projection(response))
                    generation.event('llm.returned', provider=response.provider, model=response.model,
                        is_mock=response.is_mock, output_bytes=len(response.text.encode()),
                        call_id=response.call_id,request_snapshot_id=response.request_snapshot_id,
                        template_snapshot_id=response.template_snapshot_id)
                except TimeoutError:
                    raise AppError("LLM_TIMEOUT", "报告洞察生成超时，未用虚构内容替代。", 504) from None
                except AppError:
                    raise
                except Exception:
                    raise AppError("REPORT_LLM_CALL_FAILED", "报告洞察生成失败。", 502) from None
                try:
                    if len(response.text.encode()) > 64 * 1024:
                        raise ValueError("Oversized response")
                    draft = InsightDraft.model_validate(strict_json(response.text))
                except (ValidationError, ValueError, TypeError, AttributeError):
                    raise AppError("REPORT_LLM_INVALID_OUTPUT", "洞察输出不符合结构契约。", 502) from None
                generation.attributes(candidate_count=len(draft.insights), provider=response.provider,
                    model=response.model, is_mock=response.is_mock)
            with trace.span('fact_validator') as validation_stage:
                insights, rejected_insights = materialize_candidates(draft, selected, tasks,
                    {t.result.result_id: t.result for t in execution.tasks if t.status == 'success'}, limitations,
                    diagnostics=text_validation, observer=trace.candidate)
                missing_core_metrics = missing_metrics(evidence, tasks, insights)
                if missing_core_metrics:
                    coverage = 'partial'
                    for tid, field in missing_core_metrics:
                        label = next(c.label for t in execution.tasks if t.task_id == tid for c in t.result.columns if c.field == field)
                        limitations.append(f'核心方向「{tasks[tid].title}」的指标「{label}」尚未形成有效洞察；计算结果仍可查询，目标未完整覆盖。')
                validation_stage.attributes(candidate_count=len(draft.insights), accepted_count=len(insights),
                    rejected_count=len(rejected_insights))
            llm = LLMMetadata(provider=response.provider, model=response.model, is_mock=response.is_mock)
        else:
            with trace.span('insight_generator', {'skip_reason': 'NO_EVIDENCE', 'candidate_count': 0}, skip=True):
                pass
            with trace.span('fact_validator', {'skip_reason': 'NO_EVIDENCE', 'candidate_count': 0}, skip=True):
                pass
        with trace.span('report_assembler') as assembly:
            status = "unavailable" if not evidence else ("partial" if uncompleted or rejected_insights or missing_core_metrics or execution.execution_status == "partial_success" else "complete")
            if rejected_insights:
                limitations.append(f'有 {len(rejected_insights)} 条模型候选洞察未通过校验，未作为事实或建议输出；本报告为部分生成，拒绝原因保留在技术详情。')
            if not evidence:
                coverage = "blocked"
                limitations.append("没有有效计算证据，未调用模型生成总结。")
            headline = {"complete": "计划内核心任务已有可用结果", "partial": "已有部分发现，核心目标仍有待核实之处", "blocked": "现有结果尚不能回答核心问题"}[coverage]
            if status == "unavailable":
                headline = "暂无可生成报告的有效证据"
            elif coverage == 'complete' and len(core_tasks) == 1:
                headline = core_tasks[0].title
            overview = f"围绕「{(intent.analysis_goal.business_goal or '数据分析')[:500]}」，基于 {len(evidenced_tasks)} 个任务的可用结果整理。"
            names = {f.field_id: f.display_name for f in profile.fields}
            for executed in execution.tasks:
                if executed.status == 'success' and any(s.operation == 'top_n' for s in tasks[executed.task_id].steps):
                    dimensions = descriptions[executed.task_id].dimensions
                    name = names.get(dimensions[0], '分组') if len(dimensions) == 1 else '分组'
                    overview += f' 该任务实际返回 {len(executed.result.rows)} 个{name}；Top N 选择不代表完整总体。'
            if uncompleted:
                overview += f"另有 {len(uncompleted)} 个任务未形成有效报告结果，详见局限性。"
            summary_refs = list(dict.fromkeys(ref for insight in insights[:3] for ref in insight.evidence_refs))
            metrics = []
            for item in evidence:
                if item.evidence_type == "metric":
                    label = next(c.label for t in execution.tasks if t.result and t.result.result_id == item.data_ref for c in t.result.columns if c.field == item.result_field)
                    metrics.append(KeyMetric(label=item.value.get("label", label), value=item.value["value"], unit=item.value["unit"], evidence_ref=item.evidence_id))
                elif item.evidence_type == "coverage" and not any(m.label == "上传数据记录数" for m in metrics):
                    metrics.append(KeyMetric(label="上传数据记录数", value=item.value["dataset_rows"], unit="条", evidence_ref=item.evidence_id))
                    metrics.append(KeyMetric(label="首个核心任务有效样本量" if tasks[item.task_id].priority == "P0" else "首个任务有效样本量",
                        value=item.value["valid_samples"], unit="条", evidence_ref=item.evidence_id))
                elif item.evidence_type == "maximum" and not any(m.label.startswith("返回结果最大值") for m in metrics):
                    unit = next(c.unit for t in execution.tasks if t.result and t.result.result_id == item.data_ref for c in t.result.columns if c.field == item.result_field)
                    metrics.append(KeyMetric(label="返回结果最大值（" + ("缺失分组" if item.value["category"] is None else str(item.value["category"]))[:40] + "）", value=item.value["value"], unit=unit, evidence_ref=item.evidence_id))
                elif item.evidence_type == "proportion" and not any(m.label.startswith("同口径总体占比") for m in metrics):
                    metrics.append(KeyMetric(label="同口径总体占比（" + ("缺失分组" if item.value["category"] is None else str(item.value["category"]))[:40] + "）", value=item.value["percent"], unit="%", evidence_ref=item.evidence_id))
            totals = [m for m in metrics if m.label.startswith("本次返回")]
            metrics = totals + [m for m in metrics if m not in totals]
            comparison_metrics = []
            leaders = []
            for item in evidence:
                if item.evidence_type != 'ranking' or item.value['rank'] != 1 or tasks[item.task_id].priority != 'P0':
                    continue
                desc = descriptions[item.task_id]
                metric = desc.metrics[item.result_field]
                names = {f.field_id: f.display_name for f in profile.fields}
                measure = ('记录数量' if metric.field is None else names.get(metric.field, '指标'))
                if metric.function == 'count' and metric.field:
                    measure += '非空记录数'
                maxima = [e for e in evidence if e.task_id == item.task_id and e.result_field == item.result_field and e.evidence_type == 'maximum']
                if maxima and maxima[0].value['tie_count'] == 1:
                    leaders.append(KeyMetric(label='第一名' + measure, value=item.value['value'], unit=None, evidence_ref=item.evidence_id))
            for item in evidence:
                kind = item.value.get('comparison_kind')
                if tasks[item.task_id].priority != 'P0' or kind not in {'relative_lead', 'returned_concentration'}:
                    continue
                label = (f"{item.value['left']}相对{item.value['right']}领先幅度" if kind == 'relative_lead'
                         else '前两个返回分组占返回合计')
                comparison_metrics.append(KeyMetric(label=label, value=item.value['percent'], unit='%', evidence_ref=item.evidence_id))
            metrics = leaders[:1] + comparison_metrics[:2] + metrics
            if insights:
                overview += ' 比较发现及其依据见下方；业务解释与建议仍需结合实际情况核查。'
            metadata = {t.task_id: {**t.model_dump(exclude={"result"}),
                "insight_generation_version": GENERATION_VERSION,
                "rejected_insights": rejected_insights,
                "text_validation": text_validation,
                "missing_core_metrics": [field for tid, field in missing_core_metrics if tid == t.task_id],
                "approved_scope": mapper.steps(tasks[t.task_id]),
                "original_query": original_query if approved_snapshot is not None else None}
                for t in execution.tasks}
            report_id = "report_" + uuid4().hex
            report = AnalysisReport(report_id=report_id, execution_id=execution.execution_id, plan_version=execution.plan_version,
                dataset_id=profile.dataset_id, dataset_version=profile.dataset_version, dataset_name=profile.file_name,
                dataset_row_count=profile.row_count, analysis_goal=intent.analysis_goal.business_goal or "数据分析",
                execution_source=execution.source, report_status=status, goal_coverage=coverage,
                summary=Summary(headline=headline, overview=overview, evidence_refs=summary_refs),
                key_metrics=metrics[:6], insights=insights, charts=charts,
                recommendations=[Recommendation(text=i.recommendation, evidence_refs=i.evidence_refs) for i in insights],
                limitations=list(dict.fromkeys(limitations)), uncompleted_tasks=uncompleted, evidence=evidence,
                result_data={t.result.result_id: t.result for t in execution.tasks if t.status == "success"},
                execution_metadata=metadata,
                task_metadata=tasks, fact_validation="structured_facts_verified_interpretations_unverified", llm=llm,
                provenance=Provenance(source="mock" if llm and llm.is_mock else ("llm" if llm else "uploaded"),
                    dataset=profile.dataset_id, dataset_version=profile.dataset_version, plan_version=execution.plan_version,
                    notice="事实来自执行结果和确定性证据；解释性陈述未严格验证。"),
                preview_url=f"/reports/{report_id}", download_url=f"/api/v1/reports/{report_id}/download", generated_at=now())
            assembly.attributes(report_status=report.report_status, goal_coverage=report.goal_coverage,
                insight_count=len(report.insights), chart_count=len(report.charts))
        return report
```

## S49 — EvidenceBuilder.build

`backend/app/reporting/evidence.py:38`

```python
def build(self, execution, profile, descriptions: dict[str, ResultDescription]):
        evidence = []
        successful = {task.result.result_id: task for task in execution.tasks if task.status == "success"}
        def add(task, field, kind, value, rows, statement, calculation, related=()):
            item = Evidence(evidence_id=f"E{len(evidence) + 1:04d}", task_id=task.task_id,
                data_ref=task.result.result_id, result_field=field, evidence_type=kind, value=value,
                source_row_indices=rows, related_result_refs=list(related), scope=task.scope,
                calculation=(task.calculation[:1000] + "；" + calculation)[:2000], statement=statement)
            evidence.append(item)
        for task in execution.tasks:
            if task.status != "success":
                continue
            table, desc = task.result, descriptions[task.task_id]
            columns = {c.field: c for c in table.columns}
            usable = any(value is not None for row in table.rows for value in row.values())
            if desc.metrics and not any(number(row[field]) for row in table.rows for field in desc.metrics):
                usable = False
            if not usable:
                continue
            if task.valid_sample_count is not None:
                percent = arithmetic(task.valid_sample_count, profile.row_count, "percentage")
                add(task, "$execution.valid_sample_count", "coverage",
                    {"valid_samples": task.valid_sample_count, "effective_rows": task.effective_row_count,
                     "dataset_rows": profile.row_count, "coverage_percent": percent}, [],
                    f"该任务有效样本量为 {fmt(task.valid_sample_count)}，占上传数据行数约 {fmt(percent)}%。",
                    f"{task.sample_definition}；有效样本量 / 画像总行数 × 100；有效行数由执行模块提供。")
            dimension = desc.dimensions[0] if len(desc.dimensions) == 1 else None
            for field, metric in desc.metrics.items():
                column = columns[field]
                pairs = [(index, row[field]) for index, row in enumerate(table.rows) if number(row[field])]
                if not pairs:
                    continue
                label = column.label[:100]
                if not desc.dimensions and len(table.rows) == 1:
                    add(task, field, "metric", {"value": pairs[0][1], "unit": column.unit}, [0],
                        f"{label}为 {fmt(pairs[0][1])}{column.unit or ''}。", f"读取已计算指标 {field}，函数 {metric.function}。")
                if dimension:
                    ranked = sorted(pairs, key=lambda pair: -pair[1])
                    scope = "当前返回结果" if table.truncated or not desc.complete_partition else "该任务完整分组结果"
                    for index, value in ranked[:5]:
                        category = table.rows[index][dimension]
                        rank = 1 + sum(other > value for _, other in pairs)
                        add(task, field, "ranking", {"category": category, "value": value, "rank": rank}, [index],
                            f"在{scope}中，{fmt(category)}的{label}为 {fmt(value)}{column.unit or ''}，并列值采用同一名次，排名 {rank}。",
                            f"对已返回的 {field} 降序比较，竞争排名；不推断未返回类别。")
                    for kind, choose, word in [("maximum", max, "最大"), ("minimum", min, "最小")]:
                        target = choose(value for _, value in pairs)
                        indices = [index for index, value in pairs if value == target]
                        add(task, field, kind, {"value": target, "category": table.rows[indices[0]][dimension], "tie_count": len(indices)}, indices,
                            f"{scope}的{label}{word}值为 {fmt(target)}{column.unit or ''}，对应 {fmt(table.rows[indices[0]][dimension])}等 {len(indices)} 个分组。",
                            f"读取 {field} 的{word}值，保留并列来源行。")
                    if len(ranked) >= 2:
                        temporal = dimension in desc.temporal_dimensions
                        time_pairs = [pair for pair in pairs if table.rows[pair[0]][dimension] is not None]
                        def time_key(pair):
                            value = table.rows[pair[0]][dimension]
                            if isinstance(value, (int, float)):
                                return value
                            parsed = parse_temporal(value)
                            if isinstance(parsed, datetime) and parsed.tzinfo is not None:
                                parsed = parsed.astimezone(timezone.utc)
                            return parsed.isoformat()
                        ordered = sorted(time_pairs, key=time_key) if temporal else ranked
                        if len(ordered) < 2:
                            continue
                        first, second = (ordered[-1], ordered[0]) if temporal else (ranked[0], ranked[1])
                        a, b = first[1], second[1]
                        delta = arithmetic(a, b, "difference")
                        left, right = table.rows[first[0]][dimension], table.rows[second[0]][dimension]
                        if delta is not None:
                            add(task, field, "difference", {"left": left, "right": right, "left_value": a, "right_value": b, "difference": delta},
                                [first[0], second[0]], f"在{scope}中，{fmt(left)}与{fmt(right)}的{label}差值为 {fmt(delta)}{column.unit or ''}。",
                                f"已计算值相减：{field}[{first[0]}] - {field}[{second[0]}]；不是因果或显著性检验。")
                        if temporal and b > 0 and delta is not None:
                            rate = arithmetic(delta, b, "percentage")
                            if rate is not None:
                                add(task, field, "change_rate", {"from": right, "to": left, "baseline": b, "current": a, "change_percent": rate},
                                    [second[0], first[0]], f"在已返回时间点中，{label}从 {fmt(right)}至{fmt(left)}变化约 {fmt(rate)}%。",
                                    f"(末期已计算值 - 首期已计算值) / 首期已计算值 × 100；首期分母为正；不保证时间点连续。")
                    total_ref = next((ref for ref in table.total_refs if ref.metric_field == field), None)
                    denominator, related = None, []
                    if total_ref:
                        denominator_task = successful.get(total_ref.result_id)
                        if denominator_task is None:
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母引用的结果不存在或执行失败。", 422)
                        other = descriptions[denominator_task.task_id]
                        other_table = denominator_task.result
                        other_metric = other.metrics.get(total_ref.result_field)
                        denom_column = next((c for c in other_table.columns if c.field == total_ref.result_field), None)
                        valid = (metric.function in {"count", "sum"} and other_metric is not None and
                            (other_metric.function, other_metric.field) == (metric.function, metric.field) and
                            other.scope_key == desc.scope_key and denominator_task.effective_row_count == task.effective_row_count and not other.dimensions and not other_table.truncated and
                            len(other_table.rows) == 1 and denom_column is not None and denom_column.unit == column.unit)
                        if not valid:
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母必须来自同统计范围、同指标口径的成功标量结果。", 422)
                        denominator = other_table.rows[0][total_ref.result_field]
                        related = [other_table.result_id]
                        if not number(denominator) or denominator <= 0 or any(value < 0 or value > denominator for _, value in pairs):
                            raise AppError("REPORT_DENOMINATOR_INVALID", "总体分母无效或小于分组指标。", 422)
                    elif desc.complete_partition and metric.function in {"count", "sum"} and len(pairs) == len(table.rows) and all(value >= 0 for _, value in pairs):
                        summed = sum(Decimal(str(value)) for _, value in pairs)
                        denominator = float(summed)
                        if not math.isfinite(denominator) or denominator <= 0:
                            denominator = None
                    if denominator is not None:
                        for index, value in ranked[:5]:
                            share = arithmetic(value, denominator, "percentage")
                            if share is None:
                                continue
                            category = table.rows[index][dimension]
                            add(task, field, "proportion", {"category": category, "numerator": value, "denominator": denominator, "percent": share}, [index],
                                f"{fmt(category)}的{label}占该任务同口径总体约 {fmt(share)}%。",
                                "已计算分组指标 / 已验证同口径总体分母 × 100；分母来自" + ("显式成功标量引用。" if related else "完整互斥分组之和。"), related)
            # A returned-group sum is NOT a population denominator. Never sum averages,
            # medians or distinct counts, and never treat an incomplete preview as full data.
            if desc.dimensions and not table.truncated and table.row_offset == 0:
                for field, metric in desc.metrics.items():
                    values = [row[field] for row in table.rows]
                    if metric.function not in {"sum", "count"} or not values or not all(number(v) for v in values):
                        continue
                    exact = sum(Decimal(str(v)) for v in values)
                    total = int(exact) if exact == exact.to_integral_value() else float(exact)
                    if not math.isfinite(total):
                        continue
                    column = columns[field]
                    label = "本次返回分组合计（" + column.label[:80] + "）"
                    add(task, field, "metric", {"value": total, "unit": column.unit, "label": label},
                        list(range(len(table.rows))),
                        f"本次返回的 {len(table.rows)} 个分组的{column.label[:100]}合计为 {fmt(total)}{column.unit or ''}。",
                        "仅将当前完整返回表中的可加指标相加；含 Top N 时只代表所选分组，不作为总体占比分母。")
            # Compare already calculated metrics only when their units/bases are compatible.
            if not desc.dimensions and len(table.rows) == 1:
                names = list(desc.metrics)
                if len(names) >= 2:
                    left, right = names[:2]
                    a, b = table.rows[0][left], table.rows[0][right]
                    lm, rm = desc.metrics[left], desc.metrics[right]
                    same_measure = lm.field == rm.field and lm.field is not None and (lm.function in {"count", "distinct_count"}) == (rm.function in {"count", "distinct_count"})
                    same_unit = columns[left].unit is not None and columns[left].unit == columns[right].unit and lm.function == rm.function
                    if number(a) and number(b) and (same_measure or same_unit):
                        delta = arithmetic(a, b, "difference")
                        if delta is not None:
                            add(task, left, "comparison", {"left_field": left, "right_field": right, "left_value": a, "right_value": b, "difference": delta}, [0],
                                f"已计算的{columns[left].label[:80]}与{columns[right].label[:80]}差值为 {fmt(delta)}{columns[left].unit or ''}。",
                                f"比较同口径指标 {left} 与 {right} 的已计算值，不生成新的基础指标。")
        from .comparisons import comparison_evidence
        evidence.extend(comparison_evidence(execution, descriptions, len(evidence)))
        return evidence
```

## S50 — VisualizationBuilder.build

`backend/app/reporting/visualization.py:5`

```python
def build(self, execution, descriptions, evidence, tasks, intent):
        charts = []
        for executed in execution.tasks:
            if executed.status != "success" or not executed.result.rows:
                continue
            table, desc = executed.result, descriptions[executed.task_id]
            refs = [e.evidence_id for e in evidence if e.task_id == executed.task_id]
            if not refs:
                continue
            metrics = list(desc.metrics)
            dimension = desc.dimensions[0] if len(desc.dimensions) == 1 else None
            supported, default, order = ["table"], "table", "original"
            note = "结果已由上游截断；图表和表格仅覆盖返回数据。" if table.truncated else None
            if any(step.operation == "top_n" for step in tasks[executed.task_id].steps):
                note = (note + " " if note else "") + "任务含 Top N 筛选；此处展示选定结果，不推断未返回分组。"
            if not desc.dimensions and len(table.rows) == 1 and len(metrics) == 1:
                supported, default = ["kpi", "table"], "kpi"
            elif dimension and metrics:
                supported, default, order = ["bar", "table"], "bar", "value_desc"
                values = [row[dimension] for row in table.rows if row[dimension] is not None]
                if dimension in desc.temporal_dimensions and len(values) >= 2:
                    supported, default, order = ["line", "bar", "table"], "line", "dimension_asc"
                    note = (note + " " if note else "") + "按已有时间点展示；缺失时间分组仅见表格，不推断连续性。"
                else:
                    share_rows = {i for e in evidence if e.task_id == executed.task_id and e.evidence_type == "proportion" and e.result_field == metrics[0] for i in e.source_row_indices}
                    short_labels = all(len(str(value)) <= 12 for value in values)
                    if len(metrics) == 1 and len(table.rows) <= 5 and short_labels and desc.complete_partition and not table.truncated and len(share_rows) == len(table.rows):
                        supported = ["bar", "pie", "table"]
                        goal = intent.analysis_goal.business_goal or ""
                        if any(word in goal for word in ["占比", "构成", "组成"]):
                            default = "pie"
                if len(table.rows) > 10 and default != "line":
                    note = (note + " " if note else "") + "图表默认展示前 10 个返回分组；完整返回结果可在数据表中查看。"
            charts.append(ChartSpec(chart_id=f"C{len(charts) + 1:03d}", task_id=executed.task_id,
                title=tasks[executed.task_id].title, chart_type=default, dimension=dimension, metrics=metrics,
                data_ref=table.result_id, supported_chart_types=supported, evidence_refs=refs,
                display_limit=10, order=order, note=note))
        return charts
```

## S51 — materialize_candidates

`backend/app/reporting/fact_validation.py:272`

```python
def materialize_candidates(draft, evidence, tasks, result_data, trusted_limitations=(), *, diagnostics=None, observer=None):
    """Isolate rejected candidates visibly. Never repair claims or invent fallback insights."""
    from app.domain.analysis_report import InsightDraft
    def observe(**payload):
        # Telemetry callbacks cannot change validation outcomes.
        if observer:
            try: observer(payload)
            except Exception: pass
    accepted, rejected, seen = [], [], set()
    by_id = {e.evidence_id: e for e in evidence}
    first_error = None
    for index, item in enumerate(draft.insights):
        try:
            candidate = materialize(InsightDraft(insights=[item]), evidence, tasks, result_data,
                require_core=False, trusted_limitations=trusted_limitations, diagnostics=diagnostics)[0]
            key = semantic_key(by_id[item.primary_evidence_id])
            if key in seen:
                raise AppError('REPORT_DUPLICATE_FINDING', '该候选发现重复，没有新增事实。', 502)
            seen.update(semantic_key(by_id[ref]) for ref in item.evidence_refs)
            candidate.insight_id = f'I{len(accepted) + 1:03d}'
            accepted.append(candidate)
            observe(candidate_index=index, candidate_status='accepted', primary_evidence_id=item.primary_evidence_id,
                evidence_refs=item.evidence_refs)
        except AppError as exc:
            first_error = first_error or exc
            # Rejected prose stays outside the saved business report. Keep rule
            # identity and binding diagnostics, never embed a rejected assertion
            # in metadata that might later be mistaken for a valid report fact.
            details = {k: v for k, v in exc.error.details.items() if k not in {'text', 'matches'}}
            if 'matches' in exc.error.details:
                details['triggered_rules'] = list(exc.error.details['matches'])
            rejected.append({'candidate_index': index, 'primary_evidence_id': item.primary_evidence_id,
                             'error_code': exc.error.code, 'details': details})
            observe(candidate_index=index, candidate_status='rejected', primary_evidence_id=item.primary_evidence_id,
                evidence_refs=item.evidence_refs, error_code=exc.error.code, role=details.get('role'),
                rule_ids=([details['rule']] if 'rule' in details else []) + details.get('triggered_rules', []))
    observe(candidate_count=len(draft.insights), accepted_count=len(accepted), rejected_count=len(rejected))
    if not accepted:
        error = first_error or AppError('REPORT_NO_VALID_INSIGHTS', '没有通过校验的洞察。', 502)
        error.error.details['rejected_candidates'] = rejected
        raise error
    missing_core = {e.task_id for e in evidence if tasks[e.task_id].priority == 'P0'} - {i.task_id for i in accepted}
    if missing_core:
        raise AppError('REPORT_CORE_FINDINGS_MISSING', '已有证据的核心任务未形成合法洞察，未保存完整报告。', 502)
    return sorted(accepted, key=lambda i: (tasks[i.task_id].priority, i.insight_id)), rejected
```

## S52 — ReportWorkflow.enqueue

`backend/app/workflow/reporting.py:13`

```python
def enqueue(self, execution_id, expected_attempt=None):
        result = self.executions.get(execution_id)
        if result.source != 'engine' or not result.session_id:
            raise AppError('REPORT_ENGINE_RESULT_REQUIRED', '报告主流程只接受服务端保存的真实计算结果。', 422)
        session = self.sessions.get(result.session_id)
        if session.workflow_kind != 'real_v1':
            raise AppError('REPORT_REAL_WORKFLOW_REQUIRED', '此入口仅用于真实分析会话。', 422)
        record, fresh = self.reports.queue(execution_id, result.session_id, expected_attempt)
        if fresh:
            self.traces.queue(result, record, lambda: self.executions.approved_snapshot(execution_id), self.service,
                input_reader=lambda: (self.executions.complete(execution_id),
                    self.executions.approved_snapshot(execution_id),
                    self.datasets.profile(result.dataset_id,result.dataset_version),session.user_goal))
        return record, fresh
```

## S53 — ReportWorkflow.generate

`backend/app/workflow/reporting.py:28`

```python
async def generate(self, execution_id, attempt):
        if self.reports.start(execution_id, attempt) is None:
            return
        trace = self.traces.start(execution_id, attempt)
        closed = False
        try:
            execution = self.executions.complete(execution_id)
            approval = self.executions.approved_snapshot(execution_id)
            session = self.sessions.get(execution.session_id)
            plan = approval.validated_plan.plan
            if (approval.status != 'approved' or approval.approval_id != execution.approval_id or
                    approval.session_id != execution.session_id or
                    (plan.plan_id, plan.plan_version, plan.dataset_id, plan.dataset_version) !=
                    (execution.plan_id, execution.plan_version, execution.dataset_id, execution.dataset_version)):
                raise AppError('REPORT_APPROVAL_MISMATCH', '执行结果与保存的批准快照不一致。', 422)
            profile = self.datasets.profile(execution.dataset_id, execution.dataset_version)
            trace.verify_inputs(execution,approval,profile,session.user_goal)
            report = await self.service.generate(approval.intent, approval.validated_plan, execution, profile,
                approved_snapshot=approval, original_query=session.user_goal, trace=trace)
            if report.llm and report.llm.is_mock:
                raise AppError('REPORT_MOCK_LLM_REJECTED', '真实报告不能使用 Mock 洞察，计算结果已保留。', 502)
            from app.reporting.prompt import PROMPT_VERSION
            if getattr(self.service,'prompt_source',None):
                PROMPT_VERSION = self.service.prompt_source.version
            with trace.span('report_persistence'):
                accepted = self.reports.finish(execution_id, attempt, report=report, audit={
                    'session_id': execution.session_id, 'execution_id': execution_id,
                    'approval_id': approval.approval_id, 'dataset_id': execution.dataset_id,
                    'dataset_version': execution.dataset_version, 'plan_id': plan.plan_id,
                    'plan_version': plan.plan_version, 'prompt_version': PROMPT_VERSION,
                    'schema_version': 'analysis-report-v1', 'original_query': session.user_goal,
                    'constraints_confirmed': approval.constraints_confirmed})
                if not accepted:
                    raise AppError('REPORT_STALE_CALLBACK', '报告尝试已被替代，未提交旧报告。', 409)
            from app.observability.snapshots import report_projection
            trace.snapshot('report',report,lambda:report_projection(report))
            trace.finish(report.report_status, report=report)
            closed = True
        except AppError as exc:
            error = exc.error.model_copy(update={'retryable': True})
            accepted = False if error.code == 'REPORT_STALE_CALLBACK' else self.reports.finish(execution_id, attempt, error=error)
            if accepted:
                trace.finish('failed', error=exc)
            else:
                trace.event('report.callback_ignored', error_code='REPORT_STALE_CALLBACK')
                trace.finish('interrupted', error=AppError('REPORT_STALE_CALLBACK', '旧报告回调未提交。', 409))
            closed = True
        except Exception:
            accepted = self.reports.finish(execution_id, attempt, error=WorkflowError(
                code='REPORT_GENERATION_FAILED', message='报告生成失败，原始计算结果已保存，可重试。', retryable=True))
            if not accepted:
                trace.event('report.callback_ignored', error_code='REPORT_STALE_CALLBACK')
                trace.finish('interrupted', error=AppError('REPORT_STALE_CALLBACK', '旧报告回调未提交。', 409))
                closed = True
        except BaseException as exc:
            trace.finish('interrupted', error=exc)
            closed = True
            raise
        finally:
            if not closed:
                trace.finish('failed', error=AppError('REPORT_GENERATION_FAILED', '报告尝试未正常完成。'))
```

## S54 — ReportRepository.finish

`backend/app/storage/report_repository.py:65`

```python
def finish(self, execution_id: str, attempt: int, report=None, audit=None, error=None):
        from app.domain.models import ReportGeneration, now
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT record FROM report_generations WHERE execution_id=?', (execution_id,)).fetchone()
            record = ReportGeneration.model_validate_json(row['record']) if row else None
            if not record or record.attempt != attempt or record.status not in {'queued', 'generating'}:
                return False
            if report:
                conn.execute('INSERT INTO analysis_reports VALUES (?, ?, ?)',
                    (report.report_id, report.model_dump_json(), json.dumps(audit, ensure_ascii=False, allow_nan=False)))
                record.report_id = report.report_id
                record.status = 'unavailable' if report.report_status == 'unavailable' else 'completed'
            else:
                record.status, record.error = 'failed', error
            record.finished_at = now()
            self._write_generation(conn, record)
        return True
```

## S55 — ReportRepository.recover_interrupted

`backend/app/storage/report_repository.py:98`

```python
def recover_interrupted(self):
        from app.domain.models import ReportGeneration, WorkflowError, now
        with closing(self.database.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("SELECT record FROM report_generations WHERE status IN ('queued','generating')").fetchall()
            for row in rows:
                record = ReportGeneration.model_validate_json(row['record'])
                record.status, record.finished_at = 'failed', now()
                record.error = WorkflowError(code='REPORT_PROCESS_INTERRUPTED', message='报告生成被服务重启中断，可基于已保存的计算结果重试。', retryable=True)
                self._write_generation(conn, record)
```

## S56 — ExecutionRepository.claim

`backend/app/storage/execution_repository.py:40`

```python
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
            conn.execute("UPDATE sessions SET state=?, updated_at=? WHERE id=?", (state.model_dump_json(), state.updated_at, state.id))
            return {"execution_id": execution_id, "started_at": started_at, "approval": state.engine_approval}
```

## S57 — ExecutionRepository.save_task

`backend/app/storage/execution_repository.py:70`

```python
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
```

## S58 — ExecutionRepository.finish

`backend/app/storage/execution_repository.py:86`

```python
def finish(self, result: ExecutionResultV1):
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute("SELECT status FROM executions WHERE id=?", (result.execution_id,)).fetchone()
            if not record or record["status"] != "running":
                raise AppError("EXECUTION_NOT_RUNNING", "执行记录已结束。", 409)
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
```

## S59 — CompatibleLLMProvider.generate

`backend/app/llm/compatible_provider.py:22`

```python
async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = self.build_payload(request)
        handle = self.capture.begin(request,payload,{'endpoint_sha256':hashlib.sha256(self.url.encode()).hexdigest(),
            'timeout_seconds':self.timeout,'provider':type(self).__name__}) if self.capture else None
        try:
            response = await self._send(payload)
        except BaseException as error:
            if handle: self.capture.finish(handle,error=error)
            raise
        if handle:
            self.capture.finish(handle,response=response)
            response = response.model_copy(update={'call_id':handle[0].call_id,
                'request_snapshot_id':handle[0].request_snapshot_id,'template_snapshot_id':handle[0].template_snapshot_id})
        return response
```

## S60 — CompatibleLLMProvider._send

`backend/app/llm/compatible_provider.py:52`

```python
async def _send(self, payload):
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=False,
                                         trust_env=False) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise AppError("LLM_TIMEOUT", "模型调用超时，请稍后重试。", 504) from None
        except httpx.RequestError:
            raise AppError("LLM_UNAVAILABLE", "无法连接模型服务，请检查配置或稍后重试。", 502) from None
        if response.status_code >= 300:
            code = "LLM_RATE_LIMITED" if response.status_code == 429 else "LLM_HTTP_ERROR"
            raise AppError(code, "模型服务返回错误，未生成意图结果。", 503 if response.status_code == 429 else 502)
        if len(response.content) > 256 * 1024:
            raise AppError("LLM_INVALID_OUTPUT", "模型响应超出大小限制。", 502)
        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            if message.get("refusal"):
                raise AppError("LLM_REFUSED", "模型拒绝处理本次需求，未生成意图结果。", 502)
            if choice.get("finish_reason") != "stop":
                raise AppError("LLM_INCOMPLETE_OUTPUT", "模型输出未完整结束，未生成意图结果。", 502)
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing text content")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise AppError("LLM_INVALID_OUTPUT", "模型响应结构不正确。", 502) from None
        return LLMResponse(text=content, provider="compatible", model=self.model, is_mock=False)
```

## S61 — CallRecorder.begin

`backend/app/llm/capture.py:21`

```python
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
```

## S62 — CallRecorder.finish

`backend/app/llm/capture.py:55`

```python
def finish(self, handle, response=None, error=None):
        call,timer = handle
        status = 'succeeded' if error is None else ('cancelled' if not isinstance(error,Exception) else 'failed')
        code = getattr(getattr(error,'error',None),'code',None) if error else None
        if error and not code: code = 'LLM_CALL_CANCELLED' if status=='cancelled' else 'LLM_CALL_FAILED'
        value = call.model_copy(update={'status':status,'finished_at':datetime.now(timezone.utc).isoformat(),
            'duration_ms':max(0,(perf_counter()-timer)*1000),'error_code':code,
            'response_hash':hashlib.sha256(response.text.encode()).hexdigest() if response else None})
        try: self.repository.finish(value)
        except Exception:
            logger.error('LLM call occurred but terminal capture failed; result withheld',extra={'error_code':'LLM_CAPTURE_FINALIZE_FAILED'})
            raise AppError('LLM_CAPTURE_FINALIZE_FAILED','模型已调用但记录未能完成保存，未将本次调用标记为成功。',503) from None
```

## S63 — TemplateSource.binding

`backend/app/llm/templates.py:143`

```python
def binding(self, operation_id, sequence=1, trace=None, retry_reason=None):
        current = self.build()
        if current.content_hash != self.snapshot.content_hash:
            raise AppError('PROMPT_SOURCE_MISMATCH','运行时组合内容已变化，拒绝使用旧模板标签。',503)
        run_id = trace.run.run_id if trace and trace.run else None
        span_id = trace.active.record.span_id if run_id and trace.active and trace.active.record else None
        return CallBinding(template=self.snapshot,operation_id=operation_id,call_sequence=sequence,
                           retry_index=sequence-1,retry_reason=retry_reason,run_id=run_id,span_id=span_id)
```

## S64 — PromptRegistryRepository.recover

`backend/app/storage/prompt_registry.py:121`

```python
def recover(self):
        # Same single-process recovery boundary as the existing workflow services.
        with closing(self.connect()) as conn, conn:
            rows = conn.execute("SELECT record FROM llm_calls WHERE status='running'").fetchall()
            for row in rows:
                old = LLMCallRecord.model_validate_json(row['record'])
                value = old.model_copy(update={'status':'interrupted','error_code':'LLM_CALL_INTERRUPTED',
                    'finished_at':datetime.now(timezone.utc).isoformat()})
                conn.execute('UPDATE llm_calls SET status=?,record=? WHERE id=?',('interrupted',value.model_dump_json(),old.call_id))
```

## S65 — LLMCallRecord

`backend/app/domain/prompt_registry.py:39`

```python
class LLMCallRecord(RegistryModel):
    call_id: str
    node_id: str
    operation_id: str
    call_sequence: int = Field(ge=1)
    retry_index: int = Field(ge=0)
    retry_reason: str | None = None
    retry_of_call_id: str | None = None
    template_snapshot_id: str
    request_snapshot_id: str
    run_id: str | None = None
    span_id: str | None = None
    status: Literal['running', 'succeeded', 'failed', 'cancelled', 'interrupted']
    outcome_scope: Literal['provider_protocol'] = 'provider_protocol'
    started_at: str
    finished_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    response_hash: str | None = None
```

## S66 — CallBinding

`backend/app/domain/prompt_registry.py:60`

```python
class CallBinding(RegistryModel):
    """Internal only. Never accepted by business HTTP endpoints."""
    template: PromptTemplateSnapshot
    operation_id: str
    call_sequence: int = Field(ge=1)
    retry_index: int = Field(ge=0)
    retry_reason: str | None = None
    run_id: str | None = None
    span_id: str | None = None
```

## S67 — WorkflowPolicyValidatorV12._report_extension

`backend/app/domain/workflow_policy/validator_v12.py:43`

```python
def _report_extension(self, s, c, plan, validation, execution, generation):
        if c.command_id != 'C19-A':
            return False
        report = one(c.facts, 'report')
        same_binding(report.binding, s.binding, REPORT)
        require(one(s.facts, 'report', False) is None and generation.report_id is None,
                'POLICY_REPORT_ALREADY_DELIVERED')
        require(execution.execution_outcome in {'success', 'partial_success'} and
                report.report_status in {'complete', 'partial'} and report.goal_coverage is not None,
                'POLICY_REPORT_INVALID')
        require(bool(report.evidence_ids) and report.valid_core_insight_count > 0 and
                set(report.evidence_ids) <= set(s.validated_evidence_ids), 'POLICY_REPORT_EVIDENCE_INVALID')
        failed_core = {t.task_id for t in execution.tasks if t.status != 'success'} & set(plan.core_task_ids)
        require(not (report.goal_coverage == 'complete' and (validation.coverage != 'complete' or failed_core)),
                'POLICY_REPORT_COVERAGE_INVALID')
        # Presence of an acknowledgement/proof is deliberately not a precondition.
        return True
```

## S68 — WorkflowPolicyValidatorV12._observe

`backend/app/domain/workflow_policy/validator_v12.py:61`

```python
def _observe(self, s, c):
        require(not c.facts and c.next_active_execution_key is None and not c.remove_task_ids and
                not c.acknowledged_warnings, 'POLICY_OBSERVATION_INPUT_INVALID')
        require((c.session_id, c.workflow_id) == (s.session_id, s.workflow_id), 'POLICY_WORKFLOW_MISMATCH')
        require(s.exists and s.control_status == S.COMPLETED, 'POLICY_INVALID_CONTROL_STATE')
        require(s.authorization is not None, 'POLICY_COMMIT_NOT_CONFIRMED')
        auth = s.authorization
        require((auth.session_id, auth.workflow_id, auth.root_run_id) ==
                (s.session_id, s.workflow_id, s.root_run_id), 'POLICY_WORKFLOW_MISMATCH')
        require(c.binding == s.binding == auth.binding, 'POLICY_COMMAND_SUPERSEDED')
        require(c.expected_revision == auth.authorized_revision and c.active_execution_key == auth.authorized_active_key,
                'POLICY_COMMIT_AUTHORIZATION_MISMATCH')
        require(c.request_id == auth.request_id, 'POLICY_COMMIT_AUTHORIZATION_MISMATCH')
        result = reconcile_report_commit(auth, s.commit_records)
        require(result.accepted is True, 'POLICY_COMMIT_NOT_CONFIRMED', result.reason_code)
        require(s.revision >= result.committed_revision, 'POLICY_COMMIT_REVISION_UNCONFIRMED')
        span = s.completion_span
        require(span is not None, 'POLICY_OBSERVATION_MISSING')
        require((span.session_id, span.workflow_id, span.run_id) ==
                (auth.session_id, auth.workflow_id, auth.root_run_id), 'POLICY_OBSERVATION_MISMATCH')
        require(span.node_key == 'report_persistence' and span.parent_span_id is None,
                'POLICY_SPAN_NOT_DIRECT_ROOT')
        require(auth.persistence_span_id is not None and span.span_id == auth.persistence_span_id and
                span.binding == auth.binding and span.report_id == auth.report_id and
                span.report_digest == auth.report_digest and span.commit_request_id == auth.request_id and
                span.commit_payload_hash == auth.payload_hash and span.authorized_revision == auth.authorized_revision and
                span.authorized_active_key == auth.authorized_active_key, 'POLICY_OBSERVATION_MISMATCH')
        if span.status == 'complete':
            return PolicyDecision(decision='allow', reason_code='POLICY_OBSERVATION_ALREADY_COMPLETE', action='replay',
                policy_scope=s.policy_scope, command_id=c.command_id, replay_ref=span.span_id)
        require(span.status == 'running', 'POLICY_OBSERVATION_TERMINAL')
        spec = self.command_specs['C19-B']
        return PolicyDecision(decision='allow', reason_code='POLICY_OBSERVATION_ALLOWED', action='observe',
            policy_scope=s.policy_scope, command_id=c.command_id,
            expected_transition=ExpectedTransition(owner='span', source='running', target='complete'),
            required_evidence=(spec.required_evidence,))
```

## S69 — reconcile_report_commit

`backend/app/domain/workflow_policy/report_commit.py:78`

```python
def reconcile_report_commit(authorization: ReportAuthorization, records: CommitRecords | None) -> CommitReconciliation:
    """Resolve an acknowledged or lost-ack commit using only persistent evidence.

    Missing acknowledgement is not an input, because it proves neither commit nor
    rollback. Absence is conclusive only under a transactional read after fencing
    the writer; otherwise the verdict remains unknown.
    """
    a = ReportAuthorization.model_validate(authorization)
    r = CommitRecords.model_validate(records) if records is not None else None
    def verdict(status, accepted, code):
        return CommitReconciliation(status=status, accepted=accepted, reason_code=code,
            report_id=a.report_id if accepted else None,
            committed_revision=r.metadata.committed_revision if accepted and r and r.metadata else None)
    if r is None or r.read_consistency != 'transactional':
        return verdict('unknown', None, 'COMMIT_READ_UNCONFIRMED')
    if any(getattr(a.binding, key) is None for key in REFERENCE_FIELDS):
        return verdict('inconsistent', None, 'COMMIT_REFERENCE_MISSING')
    if r.report is None and r.ownership is None and r.metadata is None:
        g = r.generation
        if (r.writer_isolated and g is not None and g.kind == 'generation' and
                (g.session_id, g.workflow_id) == (a.session_id, a.workflow_id) and
                g.binding == a.binding and g.operation_key == a.authorized_active_key and
                g.generation_status == 'generating' and g.report_id is None):
            return verdict('not_committed', False, 'COMMIT_ABSENCE_VERIFIED')
        return verdict('unknown', None, 'COMMIT_ABSENCE_UNCONFIRMED')
    if any(x is None for x in (r.report, r.generation, r.ownership, r.metadata)):
        return verdict('inconsistent', None, 'COMMIT_RECORD_MISSING')
    report, generation, link, metadata = r.report, r.generation, r.ownership, r.metadata
    if metadata.authorization != a or metadata.committed_revision != a.authorized_revision + 1:
        return verdict('inconsistent', None, 'COMMIT_METADATA_MISMATCH')
    if (report.kind != 'report' or generation.kind != 'generation' or
            (report.session_id, report.workflow_id) != (a.session_id, a.workflow_id) or
            (generation.session_id, generation.workflow_id) != (a.session_id, a.workflow_id) or
            (link.session_id, link.workflow_id) != (a.session_id, a.workflow_id)):
        return verdict('inconsistent', None, 'COMMIT_OWNER_MISMATCH')
    if (report.binding != a.binding or generation.binding != a.binding or
            link.execution_id != a.binding.execution_id or link.accepted_report_attempt != a.binding.report_attempt):
        return verdict('inconsistent', None, 'COMMIT_BRANCH_MISMATCH')
    if (report.fact_id != a.report_id or generation.report_id != a.report_id or link.report_id != a.report_id or
            report.digest != a.report_digest or report.operation_key != a.authorized_active_key or
            generation.operation_key != a.authorized_active_key or generation.generation_status != 'completed' or
            report.report_status not in {'complete', 'partial'} or not report.evidence_ids or
            report.valid_core_insight_count < 1 or report.goal_coverage is None):
        return verdict('inconsistent', None, 'COMMIT_REPORT_MISMATCH')
    return verdict('accepted', True, 'COMMIT_PERSISTED')
```

## S70 — WorkflowReader.observation_links

`backend/app/storage/workflow_reader.py:142`

```python
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
```

## S71 — create_router

`backend/app/api/routes.py:32`

```python
def create_router(repository: SessionRepository, files: FileStore,
                  workflow: WorkflowOrchestrator, review: PlanReviewService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(session_guard(repository.database))])

    @router.get("/health")
    def health():
        return {"status": "ok", "service": "insightflow", "mode": "real", "version": "0.1.0",
                "capabilities": {"data_profiler": "real", "intent_parser": "v1", "analysis_planner": "v1_real_workflow",
                                 "plan_validator": "v1", "report_module": "v1_standalone", "planning_and_reports": "real_planning_report_not_connected", "chat_planning_and_reports": "real_until_execution_result", "legacy_chat": "mock_isolated",
                                 "hitl": "v1_real", "analysis_engine": "v1_real", "new_ui": "real_workflow_v1",
                                 "workflow": "v1_real_until_execution_result"}}

    @router.get("/sessions")
    def sessions(request: Request):
        return visible_sessions(repository.database, repository.list(), request)

    @router.post("/sessions", response_model=SessionState, status_code=201)
    async def create_session(file: Annotated[UploadFile, File()], background_tasks: BackgroundTasks,
                             goal: Annotated[str, Form(max_length=2000)] = "",
                             manual_review: Annotated[bool, Form()] = False,
                             real_workflow: Annotated[bool, Form()] = False,
                             mode: Annotated[AnalysisMode, Form()] = AnalysisMode.GOAL_DRIVEN,
                             header_row: Annotated[int, Form(ge=1, le=100_001)] = 1,
                             sheet_name: Annotated[str | None, Form(min_length=1, max_length=31)] = None,
                             encoding: Annotated[Literal["utf-8-sig", "gb18030"], Form()] = "utf-8-sig",
                             delimiter: Annotated[Literal[",", ";", "\t", "|"], Form()] = ","):
        if manual_review and real_workflow:
            raise AppError("WORKFLOW_MODE_CONFLICT", "不能同时选择人工导入与自动真实Workflow。", 422)
        if manual_review and not goal.strip():
            raise AppError("ANALYSIS_GOAL_REQUIRED", "真实审核会话需要明确业务目标，请填写后上传。", 422)
        metadata = await files.save(file)
        options = ProfileOptions(header_row=header_row, sheet_name=sheet_name, encoding=encoding, delimiter=delimiter)
        state = SessionState(title=goal.strip()[:28] or "未命名分析", file=metadata, user_goal=goal, analysis_mode=mode,
                             workflow_kind="real_v1" if real_workflow else "manual_review" if manual_review else "legacy_mock",
                             profile_options=options, data_source="uploaded" if real_workflow or manual_review else "mock",
                             review_status="awaiting_review" if real_workflow else None,
                             messages=[Message(role="user", content=goal)])
        try:
            repository.create(state)
        except Exception:
            files.remove(metadata)
            raise
        if real_workflow:
            workflow.trace_created(state)
        token = issue_session_token(repository.database, state.id) if manual_review or real_workflow else None
        if real_workflow:
            background_tasks.add_task(workflow.prepare, state.id, real_workflow=True)
            return JSONResponse(status_code=201, content={**state.model_dump(mode="json"), "review_access_token": token})
        result = await workflow.prepare(state.id, options, manual_review=manual_review)
        if token:
            return JSONResponse(status_code=201, content={**result.model_dump(mode="json"), "review_access_token": token})
        return result

    @router.get("/sessions/{session_id}", response_model=SessionState)
    def get_session(session_id: str):
        return repository.get(session_id)

    @router.get("/sessions/{session_id}/plans")
    def get_plans(session_id: str):
        state = repository.get(session_id)
        return review.audit.versions(session_id) if state.review_plan else state.plans

    @router.post("/sessions/{session_id}/plans", response_model=SessionState)
    def save_plan(session_id: str, request: SavePlanRequest):
        if repository.get(session_id).workflow_kind == "real_v1":
            raise AppError("GENERATED_PLAN_MANAGED_BY_WORKFLOW", "真实主流程的初始计划由服务端模型生成；不能用人工JSON替换。", 409)
        return review.save_v1(session_id, request)

    @router.get("/sessions/{session_id}/plan", response_model=PlanVersion)
    def current_plan(session_id: str):
        record = repository.get(session_id).review_plan
        if record is None:
            raise AppError("REAL_PLAN_NOT_AVAILABLE", "该会话尚无真实 V1 计划。", 404)
        return record

    @router.get('/sessions/{session_id}/review', response_model=ReviewPresentation)
    def review_presentation(session_id: str):
        return review.review_presentation(session_id)

    @router.get('/sessions/{session_id}/constraint-audits')
    def constraint_audits(session_id: str):
        repository.get(session_id)
        return review.audit.constraint_audits(session_id)

    @router.get("/sessions/{session_id}/plans/{version}", response_model=PlanVersion)
    def plan_version(session_id: str, version: int):
        repository.get(session_id)
        for record in review.audit.versions(session_id):
            if record.plan_version == version:
                return record
        raise AppError("PLAN_VERSION_NOT_FOUND", "本会话没有此计划版本。", 404)

    @router.get("/sessions/{session_id}/approvals")
    def approvals(session_id: str):
        repository.get(session_id)
        return [{**record.model_dump(mode="json"),
                 "execution_ids": [eid for eid in repository.get(session_id).engine_execution_ids
                    if review_execution_approval(eid) == record.approval_id]}
                for record in review.audit.approvals(session_id)]

    def review_execution_approval(execution_id):
        # Includes unfinished executions; the immutable execution snapshot already exists at claim time.
        from contextlib import closing
        import json
        with closing(repository.database.connect()) as conn:
            row = conn.execute("SELECT approval FROM executions WHERE id=?", (execution_id,)).fetchone()
        return json.loads(row["approval"])["approval_id"] if row else None

    @router.post("/sessions/{session_id}/clarifications", response_model=SessionState)
    async def clarify_intent(session_id: str, request: ClarificationRequest, background_tasks: BackgroundTasks):
        if repository.get(session_id).workflow_kind == "real_v1":
            state = workflow.begin_real_clarification(session_id, request.answer, request.expected_revision)
            background_tasks.add_task(workflow.prepare_real, session_id)
            return state
        return await workflow.clarify(session_id, request.answer, request.expected_revision)

    @router.post("/sessions/{session_id}/retry-preparation", response_model=SessionState)
    async def retry_preparation(session_id: str, request: RetryPreparationRequest, background_tasks: BackgroundTasks):
        state = workflow.begin_real_retry(session_id, request.expected_revision)
        background_tasks.add_task(workflow.prepare_real, session_id)
        return state

    @router.post("/sessions/{session_id}/plan-revisions", response_model=SessionState)
    def revise_plan(session_id: str, request: RevisionRequest):
        return review.revise(session_id, request)

    @router.post("/sessions/{session_id}/approvals", response_model=SessionState)
    def approve_plan(session_id: str, request: ApprovalRequest):
        return review.approve(session_id, request)

    @router.post("/sessions/{session_id}/execute", response_model=SessionState)
    async def execute(session_id: str, request: ApprovalRequest):
        return await workflow.execute(session_id, request)

    def completed_report(session_id: str):
        state = repository.get(session_id)
        if state.status != SessionStatus.COMPLETED or not state.report:
            raise AppError("REPORT_NOT_READY", "报告尚未生成，请先确认并执行分析计划。")
        return state.report

    @router.get("/sessions/{session_id}/report")
    def get_report(session_id: str):
        return completed_report(session_id)

    @router.get("/sessions/{session_id}/report/preview", response_class=HTMLResponse)
    def preview_report(session_id: str):
        return HTMLResponse(render_report(completed_report(session_id)))

    @router.get("/sessions/{session_id}/report/download", response_class=HTMLResponse)
    def download_report(session_id: str):
        report = completed_report(session_id)
        return HTMLResponse(render_report(report), headers={
            "Content-Disposition": f'attachment; filename="insightflow-report-{session_id}.html"'
        })

    return router
```

## S72 — create_execution_router

`backend/app/api/executions.py:16`

```python
def create_execution_router(engine, executions, reporting=None):
    router = APIRouter(prefix="/api/v1/executions",tags=["Analysis Engine V1"], dependencies=[Depends(session_guard(executions.database))])

    @router.post("",response_model=ExecutionResultV1)
    def execute(request: ExecutionRequest, background: BackgroundTasks):
        # Only four identifiers are accepted. Plan bodies, paths and approval flags are forbidden.
        result = engine.execute(request)
        if reporting and reporting.sessions.get(request.session_id).workflow_kind == "real_v1":
            record, fresh = reporting.enqueue(result.execution_id)
            if fresh:
                background.add_task(reporting.generate, result.execution_id, record.attempt)
        return result

    @router.get("/{execution_id}",response_model=ExecutionResultV1)
    def get(execution_id: str, view: Literal["preview","complete"]="preview"):
        return executions.complete(execution_id) if view == "complete" else executions.get(execution_id)

    @router.get("/{execution_id}/results/{result_id}",response_model=ResultTable)
    def table(execution_id: str,result_id: str,offset: int=Query(0,ge=0),limit: int=Query(5000,ge=1,le=5000)):
        return executions.get_table(execution_id,result_id,offset,limit)

    if reporting:
        @router.get("/{execution_id}/report", response_model=ReportGeneration | None)
        def report_status(execution_id: str):
            executions.get(execution_id)
            return reporting.reports.generation(execution_id)

        @router.post("/{execution_id}/report", response_model=ReportGeneration, status_code=202)
        def generate_report(execution_id: str, request: GenerateExecutionReport, background: BackgroundTasks):
            record, fresh = reporting.enqueue(execution_id, request.expected_attempt)
            if fresh:
                background.add_task(reporting.generate, execution_id, record.attempt)
            return record

    return router
```

## S73 — create_app

`backend/app/main.py:41`

```python
def create_app(settings: Settings | None = None, provider: LLMProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = SessionRepository(Database(settings.data_dir))
    files = FileStore(settings.data_dir, settings.max_upload_bytes)
    datasets = DatasetRepository(repository.database)
    profiler = DataProfilerService(files, datasets)
    llm = provider or create_provider(settings)
    captures = CallRecorder(retention_days=settings.llm_request_retention_days)
    try:
        captures.repository = PromptRegistryRepository(settings.data_dir / 'prompt_registry')
    except Exception:
        import logging
        logging.getLogger('app.llm.capture').error('Prompt registry unavailable; HTTP LLM requests will be blocked')
    if isinstance(llm,CompatibleLLMProvider):
        llm.capture = captures
    parser = IntentParserService(llm, settings.llm_timeout_seconds, max_attempts=settings.intent_max_attempts,
                                 enable_thinking=settings.intent_enable_thinking)
    registry = CapabilityRegistry()
    planner = AnalysisPlannerService(llm, registry, settings.llm_timeout_seconds,
        max_attempts=settings.planner_max_attempts, enable_thinking=settings.planner_enable_thinking)
    report_service = AnalysisReportService(llm, registry, settings.llm_timeout_seconds, settings.report_enable_thinking)
    prompt_sources={key:service.prompt_source for key,service in
        [('intent_parser',parser),('analysis_planner',planner),('insight_generator',report_service)] if service.prompt_source}
    reports = ReportRepository(repository.database)
    executions = ExecutionRepository(repository.database)
    traces = TraceRecorder()
    if settings.trace_enabled:
        try:
            traces.repository = TraceRepository(settings.data_dir / 'observability')
        except Exception:
            import logging
            traces.degraded = True
            logging.getLogger('app.trace').warning('Trace initialization failed; business remains available; observations may be missing')
    reporting = ReportWorkflow(repository, datasets, executions, reports, report_service, traces)
    engine = AnalysisEngineService(repository,datasets,files,executions,registry)
    review = PlanReviewService(repository, datasets, registry)
    workflow = WorkflowOrchestrator(repository, parser, profiler, planner, review, traces)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        engine.recover_interrupted()
        workflow.recover_interrupted()
        reports.recover_interrupted()
        traces.recover()
        if captures.repository:
            try:
                captures.repository.recover()
                captures.repository.prune_expired()
            except Exception:
                import logging
                logging.getLogger('app.llm.capture').error('Prompt registry recovery failed; HTTP calls blocked')
                captures.repository = None
        app.state.prompt_registration = register_loaded_templates(captures.repository, prompt_sources)
        yield

    app = FastAPI(title="InsightFlow", version="0.1.0", lifespan=lifespan,
                  description="Real Workflow V1: profile → intent → planner → validation → HITL → engine. real_workflow=true; manual_review=true retains manual import; legacy sessions stay isolated.")
    app.state.traces = traces
    app.state.llm_captures = captures
    app.state.repository = repository
    app.state.workflow = workflow
    app.state.datasets = datasets
    app.state.profiler = profiler
    app.state.intent_parser = parser
    app.state.analysis_planner = planner
    app.state.capability_registry = registry
    app.state.report_service = report_service
    app.state.reports = reports
    app.state.report_workflow = reporting
    app.state.executions = executions
    app.state.analysis_engine = engine
    app.state.plan_review = review
    app.include_router(create_router(repository, files, workflow, review))
    app.include_router(create_dataset_router(files, datasets, profiler, repository))
    app.include_router(create_intent_router(parser, datasets))
    app.include_router(create_plan_router(planner, datasets, registry))
    app.include_router(create_report_router(report_service, datasets, reports, executions))
    app.include_router(create_execution_router(engine,executions,reporting))
    runtime_templates={key:source.snapshot.template_snapshot_id for key,source in prompt_sources.items()}
    lifecycle = LifecycleService(LifecycleReader(repository.database.path, settings.data_dir / 'observability' / 'trace.sqlite3'))
    app.state.lifecycle = lifecycle
    admin_router = create_admin_router(traces, reports, settings.admin_read_token,captures,settings.admin_snapshot_token,runtime_templates,
                                      local_test_mode=settings.admin_local_test_mode, lifecycle=lifecycle)
    app.include_router(admin_router)
    app.include_router(admin_router, prefix='/api/v1', include_in_schema=False)
    install_error_handlers(app)
    return app
```
