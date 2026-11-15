"""Read-only Admin projection. Business status is computed without reading any Span."""
from datetime import datetime
from app.domain.errors import AppError
from app.observability.failures import CATEGORIES, first_failure
from app.observability.quality import quality_signals
from app.services.lifecycle import aggregate
from app.storage.lifecycle_reader import LifecycleReader, readonly


class WorkflowObservabilityService:
    def __init__(self,trace_service):
        self.trace_service=trace_service
        self.path=trace_service.sessions.database.path
        self.reader=LifecycleReader(self.path,self.path.parent/'observability'/'trace.sqlite3')

    def _business(self,wf):
        snapshot=self.reader.read(wf['session_id'],business_only=True)
        model=aggregate(snapshot,wf['session_id'])
        state=snapshot.session or {}
        identity_matches=(state.get('workflow_id'),state.get('root_run_id'))==(wf['workflow_id'],wf['root_run_id'])
        business=model.business_lifecycle.model_dump()
        consistency=model.consistency.model_dump()
        if not identity_matches:
            business['status']='unknown';consistency['status']='inconsistent' if snapshot.session else 'unknown'
            consistency['issues']=list(dict.fromkeys(consistency['issues']+['workflow_identity_mismatch' if snapshot.session else 'business_unavailable']))
        updated=state.get('updated_at') if identity_matches else wf['updated_at']
        refs=model.source_refs.model_dump()
        refs['workflow_id'],refs['root_run_id']=wf['workflow_id'],wf['root_run_id']
        # Exact selected generation/execution from business evidence, never max(timestamp).
        end=None
        if business['status'] in {'succeeded','partially_succeeded','failed','interrupted'}:
            generation=next((g for g in snapshot.generations if g.get('execution_id')==refs['execution_id'] and g.get('attempt')==refs['report_attempt']),None)
            if generation and generation.get('status') in {'completed','unavailable','failed'}:end=generation.get('finished_at')
            elif refs['execution_id']:
                result=next((e.get('result') for e in snapshot.executions if e.get('id')==refs['execution_id']),None)
                if result and business['report_generation_status'] is None:end=result.get('finished_at')
        duration=None
        try:
            start_dt=datetime.fromisoformat(wf['created_at']);end_dt=datetime.fromisoformat(end) if end else None
            if end_dt and start_dt.tzinfo and end_dt.tzinfo and end_dt>=start_dt:duration=(end_dt-start_dt).total_seconds()*1000
        except (ValueError,TypeError):pass
        business_error=(state.get('error') or {}).get('code') if identity_matches and business['status'] in {'failed','interrupted'} else None
        generation=next((g for g in snapshot.generations if g.get('execution_id')==refs['execution_id'] and g.get('attempt')==refs['report_attempt']),None)
        generation_error=((generation or {}).get('error') or {}).get('code') if business['report_generation_status'] in {'failed','unavailable'} else None
        return {'_business_error':business_error,'_generation_error':generation_error,
            'workflow_id':wf['workflow_id'],'session_id':wf['session_id'],'root_run_id':wf['root_run_id'],
            'business_lifecycle':business,'activity':model.activity,
            'reason_codes':[r for r in model.reason_codes if not r.startswith('trace_')],
            'source_refs':refs,'consistency':consistency,'created_at':wf['created_at'],'updated_at':updated,
            'duration_ms':duration,'duration_basis':'Workflow 创建到精确当前业务终态，含人工等待' if duration is not None else None,
            'ended_at':end,'has_exception':(business['status'] in {'failed','partially_succeeded','interrupted','unknown'}
                or business['execution_status'] in {'failed','partial_success'}
                or business['report_generation_status'] in {'failed','unavailable'}
                or business['report_status'] in {'partial','unavailable'})}

    def _find(self,workflow_id):
        with readonly(self.path) as conn:
            row=conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?',(workflow_id,)).fetchone()
        if not row:raise AppError('BUSINESS_WORKFLOW_NOT_FOUND','未登记此 Workflow。',404)
        return dict(row)

    def get(self,workflow_id):
        item=self._business(self._find(workflow_id));findings=[];trace=None
        business_error,generation_error=item.pop('_business_error'),item.pop('_generation_error')
        try:trace=self.trace_service.get(workflow_id)
        except AppError as error:
            findings.append({'category':'inconsistent' if error.status==409 else 'unknown',
                'code':error.error.code,'evidence_refs':[workflow_id]})
        except Exception:
            findings.append({'category':'unknown','code':'TRACE_VIEW_UNAVAILABLE','evidence_refs':[workflow_id]})
        if trace:
            for gap in trace['collection']['gaps']:
                code=gap['code']
                if 'OWNERSHIP' in code or 'MISMATCH' in code:category='inconsistent'
                elif code=='EXECUTION_SPAN_NOT_COLLECTED':
                    execution=next((e for e in trace['executions'] if e['execution_id']==gap.get('execution_id')),None)
                    interrupted=execution and any(e.get('code')=='EXECUTION_INTERRUPTED' for e in execution['errors'])
                    category='executed_trace_missing' if execution and execution['status']=='finished' and execution['outcome'] and not interrupted else 'unknown'
                elif code in {'NODE_NOT_COLLECTED','APPROVAL_SPAN_NOT_COLLECTED'}:category='executed_trace_missing'
                elif code=='REPORT_COMMIT_SPAN_NOT_COLLECTED':
                    present=any(n['name']=='report_persistence' and n.get('attributes',{}).get('report_id')==gap.get('report_id') for n in trace['nodes'])
                    category='observation_incomplete' if present else 'executed_trace_missing'
                elif code in {'RECORDED_COLLECTION_GAP','REPORT_ARTIFACT_COLLECTION_GAP','LLM_CALL_NOT_COLLECTED'}:category='observation_incomplete'
                else:category='unknown'
                findings.append({'category':category,'code':code,'evidence_refs':[str(v) for k,v in gap.items() if k!='code']})
            for event in trace['events']:
                if event['event_type']=='report.node_skipped':
                    findings.append({'category':'not_executed','code':event['payload'].get('skip_reason','SKIP_RECORDED'),
                        'node_key':event['payload'].get('node_name'),'evidence_refs':[event['event_id']]})
            # No result rows, prompts, raw error text, authorization keys or full user content in this view.
            trace={key:trace[key] for key in ('workflow_id','root_run_id','session_id','root','nodes','events','plan_versions','approvals','executions','report_generations','reports','llm_calls','report_artifact_runs')}
            trace['executions']=[{**{k:e[k] for k in ('execution_id','approval_id','plan_version_id','status','outcome','result_ref')},
                'errors':[{k:error.get(k) for k in ('code','task_id','step_id')} for error in e['errors']]} for e in trace['executions']]
            trace['report_generations']=[{k:g.get(k) for k in ('execution_id','status','attempt','report_id','queued_at','started_at','finished_at')} for g in trace['report_generations']]
            trace['reports']=[{k:r.get(k) for k in ('report_id','execution_id','accepted_report_attempt','report_status','goal_coverage')} for r in trace['reports']]
            trace['approvals']=[{k:a.get(k) for k in ('approval_id','plan_version_id')} for a in trace['approvals']]
            trace['plan_versions']=[{k:p.get(k) for k in ('plan_version_id','plan_id','plan_version','dataset_id','dataset_version')} for p in trace['plan_versions']]
            trace['report_artifact_runs']=[{k:r.get(k) for k in ('run_id','execution_id','attempt','status','error_code','retry_of_run_id')} for r in trace['report_artifact_runs']]
            trace['nodes']=sorted(trace['nodes'],key=lambda n:(n.get('started_at') or '\uffff',n['span_id']))
        if item['consistency']['status']!='consistent':findings.append({'category':'inconsistent' if item['consistency']['status']=='inconsistent' else 'unknown','code':'BUSINESS_CONSISTENCY_UNCONFIRMED','evidence_refs':item['consistency']['issues']})
        with readonly(self.path) as conn:
            current=conn.execute("SELECT json_extract(state,'$.revision') FROM sessions WHERE id=?",(item['session_id'],)).fetchone()
        item['consistency']['revision_rechecked']=True
        if not current or current[0]!=item['source_refs']['session_revision']:
            item['consistency']['status']='unknown'
            item['consistency']['issues']=list(dict.fromkeys(item['consistency']['issues']+['session_changed']))
            item['business_lifecycle']['status']='unknown'
            item['business_lifecycle']['report_delivery']='unknown'
            findings.append({'category':'unknown','code':'SESSION_CHANGED_DURING_READ','evidence_refs':[item['session_id']]})
        item['trace']=trace
        item['failure']=first_failure(trace['nodes'] if trace else [],business_error,generation_error)
        item['quality']=quality_signals(trace['nodes'] if trace else [],trace['llm_calls'] if trace else [],
            item['business_lifecycle'],trace['reports'] if trace else [])
        item['collection']={'status':'incomplete' if any(f['category']!='not_executed' for f in findings) else 'observed',
            'findings':findings,'notice':'没有明确证据的缺席节点无法判断是否执行；不补齐预设节点。跨库读取不是分布式原子快照。'}
        item['has_exception']=item['has_exception'] or any(f['category']=='inconsistent' for f in findings) or bool(trace and any(n['status'] in {'error','suspended'} for n in trace['nodes']))
        return {'schema_version':'workflow-observability-v1',**item}

    def list(self,*,workflow_id=None,session_id=None,status=None,failure_category=None,limit=20,offset=0):
        if failure_category is not None and failure_category not in CATEGORIES:
            raise AppError('INVALID_FAILURE_CATEGORY','失败归因类别不存在。',422)
        where=[];args=[]
        for key,value in [('workflow_id',workflow_id),('session_id',session_id)]:
            if value:where.append(key+'=?');args.append(value)
        sql='SELECT * FROM business_workflows'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY created_at DESC,workflow_id ASC'
        with readonly(self.path) as conn:rows=[dict(r) for r in conn.execute(sql,args)]
        matches=[]
        for wf in rows:
            business=self._business(wf)
            if status is None or business['business_lifecycle']['status']==status:matches.append(wf)
        if failure_category is not None:
            # Attribution needs the node view, so this filter reads each candidate in full.
            details=[d for d in (self.get(wf['workflow_id']) for wf in matches) if (d['failure'] or {}).get('category')==failure_category]
            items=details[offset:offset+limit];total=len(details)
            for detail in items:detail.pop('trace',None)
        else:
            items=[];total=len(matches)
            for wf in matches[offset:offset+limit]:
                detail=self.get(wf['workflow_id']);detail.pop('trace',None);items.append(detail)
        return {'schema_version':'workflow-observability-page-v1','items':items,'total':total,'limit':limit,'offset':offset,
            'sort':'created_at DESC, workflow_id ASC','notice':'业务状态只读自 Business DB；Trace 故障不推翻业务结果。'}
