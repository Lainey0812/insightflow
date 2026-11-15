"""Exact business bindings, direct Root nodes and retained legacy Report artifacts."""
from contextlib import closing
from app.domain.errors import AppError
from app.observability.context import bind_trace
from app.observability.recorder import TraceContext, SpanHandle
from app.observability.workflow import preparation_context
from app.storage.workflow_identity import WorkflowIdentity


class DownstreamObserver:
    def __init__(self,sessions,executions,recorder):
        self.sessions,self.executions,self.recorder=sessions,executions,recorder

    def context(self,execution_id):
        with closing(self.sessions.database.connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_execution_links'").fetchone():return None
            link=conn.execute('SELECT * FROM workflow_execution_links WHERE execution_id=?',(execution_id,)).fetchone()
            if link is None:return None
            wf=conn.execute('SELECT * FROM business_workflows WHERE workflow_id=?',(link['workflow_id'],)).fetchone()
            if not wf or wf['session_id']!=link['session_id']:raise ValueError('Workflow execution ownership mismatch')
            identity=WorkflowIdentity(wf['session_id'],wf['workflow_id'],wf['root_run_id'])
        trace=preparation_context(self.recorder,identity.session_id,identity,explicit_only=True)
        trace.bindings={'execution_id':execution_id,'approval_id':link['approval_id'],
                        'plan_version_id':link['plan_version_id'],'result_ref':execution_id}
        return trace

    def execute(self,claim,action):
        ok,trace=self.recorder.call(lambda:self.context(claim['execution_id']))
        if not ok or trace is None or trace.run is None:
            if claim.get('workflow_binding'):self.recorder.workflow_gap(claim['approval'].session_id)
            return action()
        _,handle=self.recorder.call(lambda:SpanHandle(trace,'analysis_engine'))
        trace.active=handle
        with bind_trace(trace):
            try:result=action()
            except BaseException as error:
                if handle:self.recorder.call(lambda:handle.finish(error))
                raise
            def complete():
                stored=self.executions.get(result.execution_id)
                if stored!=result:raise ValueError('Execution commit not verified')
                if handle:
                    handle.attributes(execution_status=result.execution_status,result_ref=result.execution_id,
                        result_refs=[t.result_id for t in result.tasks if t.result_id],
                        rule_ids=[e.code for e in result.errors])
                    if result.errors and handle.record:
                        handle.record.error_code=result.errors[0].code
                    handle.terminal_status={'success':'complete','partial_success':'partial','failed':'failed'}[result.execution_status]
                    handle.finish()
            accepted,_=self.recorder.call(complete)
            if not accepted:
                self.recorder.workflow_gap(result.session_id)
                if handle:self.recorder.call(lambda:handle.finish(AppError('TRACE_COMMIT_UNVERIFIED','执行观测核验失败。')))
            return result

    def reporting(self,execution_id,attempt,artifact,binding=None):
        ok,trace=self.recorder.call(lambda:self.context(execution_id))
        if not ok or trace is None:
            if not binding:return artifact
            # A native collection failure cannot silently create nodes under an artifact Run.
            trace=TraceContext(self.recorder)
            trace.workflow_identity=WorkflowIdentity(binding['session_id'],binding['workflow_id'],binding['root_run_id'])
            trace.bindings={key:binding[key] for key in ('execution_id','approval_id','plan_version_id')}
            self.recorder.call(lambda:self.recorder.repository.mark_collection_gap(binding['root_run_id']))
        if trace.run is None:
            self.recorder.workflow_gap(trace.workflow_identity.session_id)
        return WorkflowReportTrace(trace,artifact,attempt)


class WorkflowReportTrace(TraceContext):
    """Report Run retains manifests/snapshots; actual Node Spans belong only to Workflow Root."""
    def __init__(self,trace,artifact,attempt):
        super().__init__(trace.owner,trace.run)
        self.workflow_identity=trace.workflow_identity
        self.bindings={**trace.bindings,'report_attempt':attempt,
                       'report_run_id':artifact.run.run_id if artifact.run else None}
        self.artifact=artifact
    def verify_inputs(self,*args):return self.artifact.verify_inputs(*args)
    def snapshot(self,*args):return self.artifact.snapshot(*args)
    def finish(self,status,report=None,error=None):
        self.event('report.'+status,report_status=getattr(report,'report_status',None),
                   report_id=getattr(report,'report_id',None),**self.bindings)
        if self.gaps:self.artifact.gaps+=self.gaps
        self.artifact.finish(status,report=report,error=error)
