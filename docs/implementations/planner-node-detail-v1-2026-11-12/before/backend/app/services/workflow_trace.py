"""Read-only Workflow ID entrypoint. Physical observations never synthesize missing nodes."""
from contextlib import closing
import json
from app.domain.errors import AppError
from app.domain.models import SessionState


class WorkflowTraceService:
    def __init__(self,sessions,traces,captures):
        self.sessions,self.traces,self.captures=sessions,traces,captures

    def get(self,workflow_id):
        with closing(self.sessions.database.connect()) as conn:
            conn.execute('BEGIN')
            wf=conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?',(workflow_id,)).fetchone()
            if not wf:raise AppError('BUSINESS_WORKFLOW_NOT_FOUND','未登记此 Workflow。',404)
            state=SessionState.model_validate_json(conn.execute('SELECT state FROM sessions WHERE id=?',(wf['session_id'],)).fetchone()[0])
            if (state.workflow_id,state.root_run_id)!=(workflow_id,wf['root_run_id']):
                raise AppError('WORKFLOW_IDENTITY_MISMATCH','业务身份不一致，不能选择其他流程代替。',409)
            plans=[dict(r) for r in conn.execute('SELECT plan_version_id,plan_id,plan_version,dataset_id,dataset_version,payload_hash FROM workflow_plan_versions WHERE workflow_id=?',(workflow_id,))]
            approvals=[dict(r) for r in conn.execute('SELECT approval_id,plan_version_id,client_request_id,snapshot_hash FROM workflow_approval_links WHERE workflow_id=?',(workflow_id,))]
            executions=[]
            for row in conn.execute('SELECT l.*,e.status,e.result,e.progress FROM workflow_execution_links l JOIN executions e ON e.id=l.execution_id WHERE l.workflow_id=?',(workflow_id,)):
                item=dict(row);result=json.loads(item.pop('result')) if item['result'] else None
                item.pop('progress')
                item['outcome']=result['execution_status'] if result else None
                item['result_ref']=item['execution_id']
                item['errors']=result['errors'] if result else []
                executions.append(item)
            reports=[]
            for row in conn.execute('SELECT l.*,r.audit,r.report FROM workflow_report_links l JOIN analysis_reports r ON r.id=l.report_id WHERE l.workflow_id=?',(workflow_id,)):
                item=dict(row);audit=json.loads(item.pop('audit'));saved_report=json.loads(item.pop('report'))
                item['commit_receipt']=audit.get('commit_receipt')
                item['report_status']=saved_report['report_status'];item['goal_coverage']=saved_report['goal_coverage']
                reports.append(item)
            # Reuse the existing read contract (including its canonical snapshot digest).
            from app.storage.workflow_reader import WorkflowReader
            reader=WorkflowReader(self.sessions.database.path)
            for plan in plans:reader._plan(conn,workflow_id,identity=plan['plan_version_id'])
            for approval in approvals:reader._approval(conn,workflow_id,approval['approval_id'])
            for execution in executions:reader._execution(conn,workflow_id,execution['execution_id'])
            for report in reports:reader.report(workflow_id,report['report_id'])
            generations=[]
            for execution in executions:
                row=conn.execute('SELECT record FROM report_generations WHERE execution_id=?',(execution['execution_id'],)).fetchone()
                if row:generations.append(json.loads(row['record']))
        gaps=[];root=None;nodes=[];events=[];artifacts=[];calls=[]
        if state.engine_approval and not any(a['approval_id']==state.engine_approval.approval_id for a in approvals):
            gaps.append({'code':'APPROVAL_OWNERSHIP_NOT_REGISTERED','approval_id':state.engine_approval.approval_id})
        registered={e['execution_id'] for e in executions}
        for eid in state.engine_execution_ids:
            if eid not in registered:gaps.append({'code':'EXECUTION_OWNERSHIP_NOT_REGISTERED','execution_id':eid})
        ok,root=self.traces.call(lambda:self.traces.repository.get(wf['root_run_id']))
        if not ok or root is None:gaps.append({'code':'ROOT_NOT_COLLECTED','root_run_id':wf['root_run_id']})
        elif root.manifest.bindings.get('workflow_id')!=workflow_id:
            raise AppError('WORKFLOW_TRACE_IDENTITY_MISMATCH','Root Manifest 与业务身份不一致。',409)
        else:
            ok,nodes=self.traces.call(lambda:self.traces.repository.spans(root.run_id))
            if not ok:nodes=[];gaps.append({'code':'SPANS_UNAVAILABLE'})
            ok,events=self.traces.call(lambda:self.traces.repository.run_events(root.run_id))
            if not ok:events=[];gaps.append({'code':'EVENTS_UNAVAILABLE'})
            if root.integrity=='incomplete':gaps.append({'code':'RECORDED_COLLECTION_GAP'})
        for output in state.node_runs:
            if not any(s.name=={'analysis_planner_v1':'analysis_planner'}.get(output.node_name,output.node_name) for s in nodes):
                gaps.append({'code':'NODE_NOT_COLLECTED','node_key':output.node_name,'business_node_run_id':output.run_id})
        for execution in executions:
            if not any(s.name=='analysis_engine' and s.attributes.get('execution_id')==execution['execution_id'] for s in nodes):
                gaps.append({'code':'EXECUTION_SPAN_NOT_COLLECTED','execution_id':execution['execution_id']})
        ok,runs=self.traces.call(lambda:self.traces.repository.related_reports(wf['root_run_id']))
        if ok:
            actual_ids={e['execution_id'] for e in executions}
            artifacts=[r.model_dump(mode='json') for r in runs if r.execution_id in actual_ids]
            for item in artifacts:
                if item['integrity']=='incomplete':gaps.append({'code':'REPORT_ARTIFACT_COLLECTION_GAP','run_id':item['run_id']})
        else:gaps.append({'code':'REPORT_RUNS_UNAVAILABLE'})
        for report in reports:
            if not any(s.name=='report_persistence' and s.attributes.get('report_id')==report['report_id'] and s.status=='success' for s in nodes):
                gaps.append({'code':'REPORT_COMMIT_SPAN_NOT_COLLECTED','report_id':report['report_id']})
        for approval in approvals:
            if not any(s.name=='hitl' and s.attributes.get('approval_id')==approval['approval_id'] for s in nodes):
                gaps.append({'code':'APPROVAL_SPAN_NOT_COLLECTED','approval_id':approval['approval_id']})
        if self.captures.repository:
            try:
                calls=[c.model_dump(mode='json') for c in self.captures.repository.calls(run_id=wf['root_run_id'])]
            except Exception:gaps.append({'code':'LLM_CALLS_UNAVAILABLE'})
        else:gaps.append({'code':'LLM_CALLS_UNAVAILABLE'})
        for node in nodes:
            if node.name in {'intent_parser','analysis_planner','insight_generator'} and node.status!='skipped' and not any(c['span_id']==node.span_id for c in calls):
                gaps.append({'code':'LLM_CALL_NOT_COLLECTED','span_id':node.span_id})
        dumped=[s.model_dump(mode='json') for s in nodes]
        # Saved business artifact only. It is not a new model call and does not change the Planner contract.
        parse_id=getattr(state.intent,'parse_id',None)
        if parse_id:
            saved=state.intent.model_dump(mode='json')
            for node in dumped:
                if node.get('name')=='intent_parser' and (node.get('attributes') or {}).get('operation_id')==parse_id:
                    node['intent_result']=saved
        return {'workflow_id':workflow_id,'root_run_id':wf['root_run_id'],'session_id':wf['session_id'],
            'session_status':state.status.value,'root_observation_scope':'preparation_checkpoint_not_business_lifecycle',
            'root':root.model_dump(mode='json') if root else None,
            'nodes':dumped,'events':[e.model_dump(mode='json') for e in events],
            'plan_versions':plans,'approvals':approvals,'executions':executions,'report_generations':generations,
            'reports':reports,'llm_calls':calls,'report_artifact_runs':artifacts,
            'collection':{'status':'incomplete' if gaps else 'observed','gaps':gaps,
                          'notice':'Cross-store reads are best-effort, not an atomic multi-database snapshot.'}}
