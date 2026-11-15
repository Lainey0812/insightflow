"""C19 protocol facts. No production writer or real data."""
from app.domain.workflow_policy.models import PolicyCommand
from app.domain.workflow_policy.validator_v12 import PolicySnapshotV12
from app.domain.workflow_policy.report_commit import (
    CommitMetadata, CommitRecords, CompletionSpan, ReportAuthorization, ReportOwnership)
from workflow_policy_fixtures import case, replace_fact


def authorization_case(report_status='complete', execution_outcome='success'):
    old, command = case('C19')
    snapshot = PolicySnapshotV12.model_validate({**old.model_dump(mode='json'),
        'policy_scope':'native_v1.2','validated_evidence_ids':['E1']})
    proposed = command.facts[0].model_copy(update={'report_status':report_status,
        'goal_coverage':'complete' if report_status=='complete' else 'partial'})
    command = command.model_copy(update={'command_id':'C19-A','request_id':'commit-report-1','facts':(proposed,)})
    if execution_outcome=='partial_success':
        execution = next(f for f in snapshot.facts if f.kind=='execution')
        tasks=(execution.tasks[0],execution.tasks[1].model_copy(update={'status':'failed','result_ref':None,'error_code':'TASK_FAILED'}))
        snapshot=snapshot.model_copy(update={'facts':replace_fact(snapshot.facts,'execution',
             execution.model_copy(update={'tasks':tasks,'execution_outcome':'partial_success'}))})
    return snapshot,command


def observation_case(report_status='complete'):
    snapshot,command = authorization_case(report_status)
    report = command.facts[0]
    auth = ReportAuthorization(session_id=snapshot.session_id,workflow_id=snapshot.workflow_id,
        root_run_id=snapshot.root_run_id,binding=snapshot.binding,report_id=report.fact_id,report_digest=report.digest,
        persistence_span_id='span-persistence-1',request_id=command.request_id,payload_hash=command.payload_hash(),
        authorized_revision=snapshot.revision,authorized_active_key=snapshot.active_execution_key)
    generation = next(f for f in snapshot.facts if f.kind=='generation').model_copy(update={
        'generation_status':'completed','report_id':report.fact_id})
    records=CommitRecords(read_consistency='transactional',report=report,generation=generation,
        ownership=ReportOwnership(session_id=snapshot.session_id,workflow_id=snapshot.workflow_id,
            execution_id=snapshot.binding.execution_id,report_id=report.fact_id,
            accepted_report_attempt=snapshot.binding.report_attempt),
        metadata=CommitMetadata(authorization=auth,committed_revision=snapshot.revision+1))
    span=CompletionSpan(span_id=auth.persistence_span_id,run_id=snapshot.root_run_id,session_id=snapshot.session_id,
        workflow_id=snapshot.workflow_id,node_key='report_persistence',status='running',binding=snapshot.binding,
        report_id=report.fact_id,report_digest=report.digest,commit_request_id=auth.request_id,
        commit_payload_hash=auth.payload_hash,authorized_revision=auth.authorized_revision,
        authorized_active_key=auth.authorized_active_key)
    committed=snapshot.model_copy(update={'facts':replace_fact(snapshot.facts,'generation',generation)+(report,),
        'revision':snapshot.revision+1,'active_execution_key':None,'authorization':auth,'commit_records':records,
        'completion_span':span})
    observation=PolicyCommand(command_id='C19-B',session_id=snapshot.session_id,workflow_id=snapshot.workflow_id,
        request_id=auth.request_id,expected_revision=auth.authorized_revision,
        active_execution_key=auth.authorized_active_key,binding=auth.binding)
    return committed,observation
