"""Deterministic read model. Never calls review, Validator, Workflow or runtime services."""
from pydantic import ValidationError
from app.domain.lifecycle import LifecycleReadModel, SourceRefs, ObservedSpan
from app.domain.models import SessionState, ReportGeneration
from app.domain.dataset_profile import DatasetProfile
from app.domain.plan_review import PlanVersion, ReviewApproval
from app.domain.execution import ExecutionResultV1, ExecutionRequest, ApprovedExecutionSnapshot
from app.domain.tracing import TraceRun, TraceSpan
from app.storage.lifecycle_reader import LifecycleReader, LifecycleSnapshot


def aggregate(snapshot: LifecycleSnapshot, session_id: str) -> LifecycleReadModel:
    out = LifecycleReadModel(source_refs=SourceRefs(session_id=session_id))
    def reason(code):
        if code not in out.reason_codes:
            out.reason_codes.append(code)
    def problem(code, inconsistent=True):
        reason(code)
        if code not in out.consistency.issues:
            out.consistency.issues.append(code)
        if inconsistent or out.consistency.status != 'inconsistent':
            out.consistency.status = 'inconsistent' if inconsistent else 'unknown'
    def state(status, activity):
        out.business_lifecycle.status, out.activity = status, activity
    def finish():
        if snapshot.changed:
            problem('session_changed', False)
        if out.consistency.issues:
            state('unknown','unknown')
            out.business_lifecycle.report_delivery = 'unknown'
        return out

    if not snapshot.business_available:
        problem('business_store_unavailable',False)
        return finish()
    out.consistency.business_snapshot = 'transactional'
    out.consistency.revision_rechecked = snapshot.revision_rechecked
    out.consistency.status = 'consistent'
    try:
        s = SessionState.model_validate(snapshot.session)
        if s.id != session_id:
            problem('branch_mismatch')
            return finish()
        out.source_refs.session_revision = s.revision
        if s.workflow_kind != 'real_v1' or s.data_source != 'uploaded':
            problem('unsupported_workflow',False)
            return finish()
        if snapshot.missing_tables:
            problem('record_missing',False)
        plans = [PlanVersion.model_validate(p) for p in snapshot.plans]
        approvals = [ReviewApproval.model_validate(a) for a in snapshot.approvals]
        generations = [ReportGeneration.model_validate(g) for g in snapshot.generations]
        # Schema parsing checks persisted shapes only, NOT a new PlanValidator run.
        if any(p.session_id != session_id for p in plans) or any(a.session_id != session_id for a in approvals):
            problem('branch_mismatch')
        if s.dataset_ref:
            ref = s.dataset_ref
            out.source_refs.dataset_id, out.source_refs.dataset_version = ref.dataset_id, ref.dataset_version
            profiles = [DatasetProfile.model_validate(p) for p in snapshot.profiles]
            if not profiles or not snapshot.files:
                problem('record_missing',False)
            elif (len(profiles) != 1 or len(snapshot.files) != 1 or
                  profiles[0].dataset_id != ref.dataset_id or profiles[0].dataset_version != ref.dataset_version or
                  snapshot.files[0].get('id') != ref.dataset_id or s.file.id != ref.dataset_id or
                  (snapshot.files[0].get('content_sha256') and snapshot.files[0]['content_sha256'] != profiles[0].content_sha256) or
                  (s.file.content_sha256 and profiles[0].content_sha256 != s.file.content_sha256) or
                  (s.profile is not None and s.profile.model_dump() != profiles[0].model_dump())):
                problem('branch_mismatch')
        elif s.review_plan or s.engine_approval or s.engine_execution_ids:
            problem('record_missing',False)
        elif s.status.value in {'PARSING_INTENT','PLANNING','VALIDATING','WAITING_FOR_CLARIFICATION','AWAITING_APPROVAL','APPROVED','RUNNING','COMPLETED'}:
            problem('record_missing',False)

        current = s.review_plan
        if current:
            if s.status.value in {'CREATED','PREPARING','PROFILING','PARSING_INTENT','PLANNING','VALIDATING','WAITING_FOR_CLARIFICATION'}:
                problem('business_state_conflict')
            out.source_refs.plan_id, out.source_refs.plan_version = current.plan_id, current.plan_version
            out.source_refs.validation_version = current.validation_version
            embedded = current.validated_plan.plan
            if (not s.dataset_ref or current.session_id != session_id or
                (current.dataset_id,current.dataset_version) != (s.dataset_ref.dataset_id,s.dataset_ref.dataset_version) or
                (embedded.plan_id,embedded.plan_version,embedded.dataset_id,embedded.dataset_version) !=
                (current.plan_id,current.plan_version,current.dataset_id,current.dataset_version) or
                current.validation_version != current.validated_plan.validation_version or
                s.current_plan_version != current.plan_version):
                problem('branch_mismatch')
            if not plans:
                problem('record_missing',False)
            elif max(plans,key=lambda p:p.plan_version) != current or sum(p.plan_version==current.plan_version for p in plans)!=1:
                problem('branch_mismatch')
            if current.validated_plan.unmet_core_requirements or current.validated_plan.coverage_status != 'complete':
                reason('core_requirements_unmet')
        elif plans or s.current_plan_version is not None or s.engine_approval:
            problem('branch_mismatch')

        approval = s.engine_approval
        if approval:
            if s.status.value=='AWAITING_APPROVAL':
                problem('business_state_conflict')
            out.source_refs.approval_id = approval.approval_id
            durable = [a for a in approvals if a.approval_id == approval.approval_id]
            if not durable:
                problem('record_missing',False)
            elif (len(durable)!=1 or durable[0].snapshot!=approval or not current or
                  approval.validated_plan!=current.validated_plan or approval.status!='approved' or
                  approval.session_id!=session_id or s.approved_plan_version!=current.plan_version or
                  (durable[0].plan_id,durable[0].plan_version,durable[0].dataset_id,durable[0].dataset_version,durable[0].validation_version)!=
                  (current.plan_id,current.plan_version,current.dataset_id,current.dataset_version,current.validation_version)):
                problem('branch_mismatch')
            intent = approval.intent
            constraints = intent.constraints
            if (intent.next_action!='proceed' or
                any(u.action=='defer' and u.id not in approval.resolved_uncertainty_ids for u in intent.uncertainties) or
                ((constraints.time_range or constraints.filters or constraints.metric_requirements or constraints.analysis_limits)
                    and not approval.constraints_confirmed)):
                problem('business_state_conflict')
            if not approval.validated_plan.executable_task_ids or approval.validated_plan.coverage_status=='blocked':
                problem('business_state_conflict')
            if (approval.validated_plan.intent_snapshot is not None and approval.validated_plan.intent_snapshot!=intent) or not set(approval.resolved_uncertainty_ids)<={u.id for u in intent.uncertainties}:
                problem('branch_mismatch')
        elif s.approved_plan_version is not None:
            problem('record_missing',False)
        if s.intent and any(getattr(u,'action',None)=='defer' and
            (not approval or u.id not in approval.resolved_uncertainty_ids) for u in getattr(s.intent,'uncertainties',[])):
            reason('uncertainties_unresolved')

        accepted = set(s.engine_execution_ids)
        if len(accepted)!=len(s.engine_execution_ids):
            problem('execution_ambiguous')
        if accepted - {r['id'] for r in snapshot.executions}:
            problem('record_missing',False)
        candidates = []
        for row in snapshot.executions:
            request = ExecutionRequest.model_validate(row['request'])
            saved_approval = ApprovedExecutionSnapshot.model_validate(row['approval'])
            if row['session_id']!=session_id or request.session_id!=session_id or row['request_id']!=request.execution_request_id:
                problem('branch_mismatch')
            matches = bool(current and approval and saved_approval==approval and
                request.plan_id==current.plan_id and request.plan_version==current.plan_version)
            if matches:
                if row['id'] not in accepted:
                    problem('branch_mismatch')
                candidates.append(row)
            else:
                reason('historical_branch_ignored')
        if len(candidates)>1:
            problem('execution_ambiguous')
        execution = candidates[0] if len(candidates)==1 else None
        if execution:
            out.source_refs.execution_id = execution['id']
            if execution['status']=='running':
                if execution['result'] is not None or s.status.value!='RUNNING':
                    problem('business_state_conflict')
                out.business_lifecycle.execution_status='running'
                state('running','executing')
            elif execution['status']=='finished':
                if execution['result'] is None:
                    problem('record_missing',False)
                else:
                    result = ExecutionResultV1.model_validate(execution['result'])
                    if (result.source!='engine' or result.session_id!=session_id or
                        result.execution_id!=execution['id'] or result.approval_id!=approval.approval_id or
                        result.execution_request_id!=execution['request_id'] or
                        (result.plan_id,result.plan_version,result.approved_plan_version,result.dataset_id,result.dataset_version)!=
                        (current.plan_id,current.plan_version,current.plan_version,current.dataset_id,current.dataset_version) or
                        {t.task_id for t in result.tasks}!={t.task_id for t in current.validated_plan.plan.tasks} or
                        any(t.status!='skipped' and t.task_id in current.validated_plan.blocked_task_ids for t in result.tasks)):
                        problem('branch_mismatch')
                    out.business_lifecycle.execution_status=result.execution_status
                    expected_session = 'FAILED' if result.execution_status=='failed' else 'COMPLETED'
                    if s.status.value!=expected_session:
                        problem('business_state_conflict')
                    interrupted = any(e.code=='EXECUTION_INTERRUPTED' for e in result.errors)
                    if result.execution_status=='failed':
                        state('failed','finished'); reason('execution_failed')
                    else:
                        state('partially_succeeded' if result.execution_status=='partial_success' else 'running','report_not_started')
                        if result.execution_status=='partial_success': reason('execution_partial')
                    current_gens = [g for g in generations if g.execution_id==result.execution_id]
                    if len(current_gens)>1:
                        problem('branch_mismatch')
                    generation = current_gens[0] if len(current_gens)==1 else None
                    if generation:
                        out.source_refs.report_attempt=generation.attempt
                        out.source_refs.report_id=generation.report_id
                        out.business_lifecycle.report_generation_status=generation.status
                        mirrored=[g for g in s.report_generations if g.execution_id==result.execution_id]
                        if mirrored!=[generation] or generation.session_id!=session_id:
                            problem('branch_mismatch')
                        if generation.attempt>1: reason('report_retry')
                        if generation.status in {'queued','generating'}:
                            if generation.report_id: problem('branch_mismatch')
                            state('running','report_queued' if generation.status=='queued' else 'reporting')
                            reason('report_not_delivered')
                        elif generation.status=='failed':
                            if generation.report_id: problem('branch_mismatch')
                            state('partially_succeeded' if result.execution_status!='failed' else 'failed','finished')
                            reason('report_failed'); reason('report_not_delivered')
                            if generation.error and generation.error.code=='REPORT_PROCESS_INTERRUPTED':
                                reason('process_interrupted')
                        else:
                            reports=[r for r in snapshot.reports if r['id']==generation.report_id]
                            if not reports:
                                problem('record_missing',False)
                            else:
                                report=reports[0]; audit=report['audit']
                                if ((report['report_id'],report['execution_id'],report['dataset_id'],report['dataset_version'],report['plan_version'],report['execution_source'])!=
                                    (generation.report_id,result.execution_id,current.dataset_id,current.dataset_version,current.plan_version,'engine') or
                                    any(audit.get(k)!=v for k,v in {'session_id':session_id,'execution_id':result.execution_id,
                                        'approval_id':approval.approval_id,'dataset_id':current.dataset_id,'dataset_version':current.dataset_version,
                                        'plan_id':current.plan_id,'plan_version':current.plan_version}.items()) or
                                    report['report_status'] not in {'complete','partial','unavailable'} or
                                    report['goal_coverage'] not in {'complete','partial','blocked'} or
                                    (generation.status=='unavailable')!=(report['report_status']=='unavailable')):
                                    problem('branch_mismatch')
                                out.business_lifecycle.report_status=report['report_status']
                                out.business_lifecycle.goal_coverage=report['goal_coverage']
                                if report['report_status']=='unavailable':
                                    state('partially_succeeded' if result.execution_status!='failed' else 'failed','finished')
                                    reason('report_unavailable'); reason('report_not_delivered')
                                else:
                                    out.business_lifecycle.report_delivery='delivered'
                                    partial=(result.execution_status!='success' or report['report_status']!='complete' or
                                        report['goal_coverage']!='complete' or current.validated_plan.coverage_status!='complete')
                                    if current.validated_plan.coverage_status!='complete' and report['goal_coverage']=='complete':
                                        problem('business_state_conflict')
                                    state('failed' if result.execution_status=='failed' else ('partially_succeeded' if partial else 'succeeded'),'finished')
                                    if report['report_status']=='partial': reason('report_partial')
                                    if report['goal_coverage']!='complete': reason('goal_not_fully_covered')
                    else:
                        if any(g.execution_id==result.execution_id for g in s.report_generations): problem('record_missing',False)
                        reason('report_not_started'); reason('report_not_delivered')
                        if interrupted:
                            state('interrupted','finished'); reason('process_interrupted')
                    if out.business_lifecycle.report_delivery!='delivered':
                        out.business_lifecycle.report_delivery='not_delivered'
            else:
                problem('record_invalid')
        else:
            status=s.status.value
            if status=='CREATED': state('created','not_started')
            elif status in {'PREPARING','PROFILING','PARSING_INTENT','PLANNING','VALIDATING'}:
                state('running',{'PREPARING':'preparing','PROFILING':'profiling','PARSING_INTENT':'parsing_intent','PLANNING':'planning','VALIDATING':'validating'}[status])
            elif status=='WAITING_FOR_CLARIFICATION':
                if not s.intent or getattr(s.intent,'next_action',None)!='clarify': problem('record_missing',False)
                state('waiting_input','clarification'); reason('clarification_required')
            elif status=='AWAITING_APPROVAL':
                if not current: problem('record_missing',False)
                state('waiting_approval','review'); reason('approval_required')
            elif status=='APPROVED':
                if not approval: problem('record_missing',False)
                state('running','approved_not_started'); reason('approved_not_started')
            elif status=='FAILED':
                if not s.error: problem('record_missing',False)
                state('interrupted' if s.error and s.error.code=='PROCESS_INTERRUPTED' else 'failed','finished')
                if out.business_lifecycle.status=='interrupted': reason('process_interrupted')
            else:
                problem('record_missing',False)
            if generations and not snapshot.executions:
                problem('record_missing',False)
        # No historical report/execution can finish a newly revised plan.
        if any(g.execution_id!=out.source_refs.execution_id for g in generations):
            reason('historical_branch_ignored')
        _collection(snapshot, out, problem, reason)
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError):
        problem('record_invalid',False)
    return finish()


def _collection(snapshot, out, problem, reason):
    c, refs = out.collection, out.source_refs
    if not snapshot.trace_available:
        c.availability='unavailable'; reason('trace_unavailable')
        if snapshot.trace_invalid: problem('record_invalid',False)
        return
    try:
        runs=[TraceRun.model_validate(r) for r in snapshot.runs]
        if refs.execution_id and any(r.kind=='report_generation' and r.execution_id==refs.execution_id and
            (refs.report_attempt is None or r.attempt>refs.report_attempt) for r in runs):
            problem('trace_binding_mismatch')
        roots=[r for r in runs if r.kind=='workflow']
        if len(roots)>1:
            problem('trace_binding_mismatch'); return
        root=roots[0] if roots else None
        reports=[r for r in runs if r.kind=='report_generation' and r.execution_id==refs.execution_id and r.attempt==refs.report_attempt]
        if len(reports)>1:
            problem('trace_binding_mismatch'); return
        report=reports[0] if reports else None
        selected=[r for r in (root,report) if r]
        if not selected:
            c.availability='not_collected'
            reason('trace_not_collected'); return
        c.availability='available'; c.integrity='incomplete'
        reason('trace_incomplete')
        if root:
            refs.workflow_run_id=root.run_id
            c.root_status=root.status; c.capture_scope=root.manifest.capture_scope
            c.root_business_revision=root.business_revision
            if root.session_id!=refs.session_id or root.manifest.bindings.get('session_id')!=refs.session_id:
                problem('trace_binding_mismatch')
            if refs.dataset_id and root.manifest.bindings.get('file_id') not in (None,refs.dataset_id):
                problem('trace_binding_mismatch')
            if root.business_revision is None or root.business_revision<refs.session_revision:
                reason('trace_stale')
            elif root.business_revision>refs.session_revision:
                problem('trace_binding_mismatch')
            elif ((root.status=='error' and out.business_lifecycle.status in {'running','waiting_input','waiting_approval'}) or
                  (root.status=='suspended' and root.error_code and out.business_lifecycle.status=='running')):
                problem('trace_state_conflict')
        else:
            reason('trace_not_collected')
        if report:
            refs.report_run_id=report.run_id; c.report_trace_status=report.status
            bindings=report.manifest.bindings
            expected={'session_id':refs.session_id,'execution_id':refs.execution_id,'approval_id':refs.approval_id,
                      'dataset_id':refs.dataset_id,'dataset_version':refs.dataset_version,'plan_id':refs.plan_id,'plan_version':refs.plan_version}
            if report.session_id!=refs.session_id or (root and report.workflow_run_id not in (None,root.run_id)):
                problem('trace_binding_mismatch')
            # Missing historical bindings are gaps; contradictory recorded bindings are inconsistency.
            if any(k in bindings and bindings[k]!=v for k,v in expected.items()):
                problem('trace_binding_mismatch')
            from app.observability.trace_status import normalize_status
            gen=out.business_lifecycle.report_generation_status
            terminal={'success','error','suspended','skipped'}
            expected_raw={'completed':out.business_lifecycle.report_status,'failed':'failed','unavailable':'unavailable'}.get(gen)
            expected_trace=normalize_status(expected_raw) if expected_raw else None
            recovery_interrupted=(report.status=='suspended' and gen=='failed')
            if (report.status in terminal and not recovery_interrupted and expected_trace and report.status!=expected_trace) or (report.report_id and report.report_id!=refs.report_id):
                problem('trace_state_conflict')
            if gen in {'completed','failed','unavailable'} and report.status=='running':
                reason('trace_stale')
        selected_ids={r.run_id for r in selected}
        for raw in snapshot.spans:
            if raw.get('run_id') in selected_ids:
                span=TraceSpan.model_validate(raw)
                c.observed_spans.append(ObservedSpan(span_id=span.span_id,run_id=span.run_id,node=span.name,
                    node_key=span.node_key,node_attempt=span.node_attempt,status=span.status))
        c.event_count=sum(snapshot.event_counts.get(r,0) for r in selected_ids)
    except (ValidationError, ValueError, TypeError, KeyError):
        c.availability='unavailable'; reason('trace_unavailable')
        problem('record_invalid',False)


class LifecycleService:
    def __init__(self, reader: LifecycleReader):
        self.reader=reader

    def get(self, session_id: str) -> LifecycleReadModel:
        return aggregate(self.reader.read(session_id),session_id)
