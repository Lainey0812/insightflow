"""V1.2 checkpoints, durable reconciliation and compatibility; no runtime wiring."""
from hashlib import sha256
import json
from pathlib import Path
import pytest

from app.domain.workflow_policy import WorkflowPolicyValidator, WorkflowPolicyValidatorV12, PolicySnapshotV12
from app.domain.workflow_policy.catalogue import SPECS
from app.domain.workflow_policy.catalogue_v12 import SPECS_V12, CONTRACT_TABLE_SHA256
from app.domain.workflow_policy.models import Bindings
from app.domain.workflow_policy.report_commit import reconcile_report_commit
from workflow_policy_fixtures import case, replace_fact
from workflow_policy_v12_fixtures import authorization_case, observation_case

p=WorkflowPolicyValidatorV12()


@pytest.mark.parametrize('code',[x for x in SPECS if x!='C19'])
def test_all_31_inherited_commands_keep_their_allow_transition(code):
    old,c=case(code)
    new=PolicySnapshotV12.model_validate({**old.model_dump(mode='json'),'policy_scope':'native_v1.2'})
    a,b=WorkflowPolicyValidator().validate(old,c),p.validate(new,c)
    assert a.decision==b.decision=='allow'
    assert a.expected_transition==b.expected_transition
    assert a.required_evidence==b.required_evidence and b.policy_scope=='native_v1.2'


@pytest.mark.parametrize('report_status',['complete','partial'])
@pytest.mark.parametrize('outcome',['success','partial_success'])
def test_c19a_precommit_permission_without_receipt(report_status,outcome):
    s,c=authorization_case(report_status,outcome)
    assert s.commit_records is None and s.authorization is None
    before=(s.model_dump_json(),c.model_dump_json())
    r=p.validate(s,c)
    assert r.decision=='allow',r
    assert r.action=='execute' and r.expected_transition.owner=='generation' and r.expected_transition.source=='generating'
    assert r.expected_transition.target=='completed'
    assert before==(s.model_dump_json(),c.model_dump_json())


@pytest.mark.parametrize('change,expected',[
 ({'workflow_id':'other'},'POLICY_WORKFLOW_MISMATCH'),
 ({'expected_revision':6},'POLICY_STALE_REVISION'),
 ({'active_execution_key':'old'},'POLICY_STALE_ACTIVE_KEY'),
])
def test_c19a_fencing(change,expected):
    s,c=authorization_case()
    assert p.validate(s,c.model_copy(update=change)).reason_code==expected


@pytest.mark.parametrize('field,value',[('execution_id','old-execution'),('report_attempt',9),('dataset_version','old-version')])
def test_c19a_current_binding(field,value):
    s,c=authorization_case()
    report=c.facts[0].model_copy(update={'binding':c.binding.model_copy(update={field:value})})
    assert p.validate(s,c.model_copy(update={'facts':(report,)})).reason_code=='POLICY_REFERENCE_MISMATCH'


@pytest.mark.parametrize('state',['queued','completed','failed','unavailable'])
def test_c19a_only_generating_is_valid(state):
    s,c=authorization_case();g=next(f for f in s.facts if f.kind=='generation')
    s=s.model_copy(update={'facts':replace_fact(s.facts,'generation',g.model_copy(update={'generation_status':state}))})
    assert p.validate(s,c).reason_code=='POLICY_INVALID_GENERATION_STATE'


@pytest.mark.parametrize('change,expected',[
 ({'evidence_ids':()},'POLICY_REPORT_EVIDENCE_INVALID'),
 ({'evidence_ids':('invented',)},'POLICY_REPORT_EVIDENCE_INVALID'),
 ({'valid_core_insight_count':0},'POLICY_REPORT_EVIDENCE_INVALID'),
 ({'report_status':'unavailable'},'POLICY_REPORT_INVALID'),
])
def test_c19a_requires_verified_report(change,expected):
    s,c=authorization_case()
    assert p.validate(s,c.model_copy(update={'facts':(c.facts[0].model_copy(update=change),)})).reason_code==expected


def test_c19a_failed_core_cannot_claim_full_goal():
    s,c=authorization_case(execution_outcome='partial_success')
    plan=next(f for f in s.facts if f.kind=='plan')
    s=s.model_copy(update={'facts':replace_fact(s.facts,'plan',plan.model_copy(update={'core_task_ids':('A','B')}))})
    assert p.validate(s,c).reason_code=='POLICY_REPORT_COVERAGE_INVALID'


@pytest.mark.parametrize('report_status',['complete','partial'])
def test_c19b_requires_persistent_success_and_only_completes_span(report_status):
    s,c=observation_case(report_status)
    before=s.model_dump_json()
    r=p.validate(s,c)
    assert r.decision=='allow' and r.action=='observe',r
    assert r.expected_transition.model_dump()=={'owner':'span','source':'running','target':'complete'}
    assert s.model_dump_json()==before
    assert s.active_execution_key is None and s.revision>c.expected_revision


def test_no_raw_accepted_boolean_or_trace_success_can_replace_persistent_facts():
    s,c=observation_case()
    raw=c.model_dump(mode='json');raw['accepted']=True
    assert p.validate(s,raw).reason_code=='POLICY_INVALID_INPUT'
    s=s.model_copy(update={'commit_records':None,'observed_root_status':'complete'})
    assert p.validate(s,c).reason_code=='POLICY_COMMIT_NOT_CONFIRMED'


@pytest.mark.parametrize('field',['report','generation','ownership','metadata'])
def test_incomplete_durable_commit_is_not_accepted(field):
    s,c=observation_case();records=s.commit_records.model_copy(update={field:None})
    result=reconcile_report_commit(s.authorization,records)
    assert result.accepted is None and result.status=='inconsistent'
    assert p.validate(s.model_copy(update={'commit_records':records}),c).reason_code=='POLICY_COMMIT_NOT_CONFIRMED'


@pytest.mark.parametrize('field',['read_consistency'])
@pytest.mark.parametrize('state',['unavailable','unknown'])
def test_read_failure_is_unknown_not_rollback(field,state):
    s,c=observation_case();records=s.commit_records.model_copy(update={field:state})
    r=reconcile_report_commit(s.authorization,records)
    assert r.accepted is None and r.status=='unknown'


@pytest.mark.parametrize('field,value',[
 ('workflow_id','other'),('report_id','other-report'),('run_id','other-root'),
 ('span_id','another-identical-span'),('authorized_active_key','other-key'),
 ('commit_payload_hash','b'*64),('commit_request_id','other-request'),
])
def test_c19b_exact_span_not_another_span(field,value):
    s,c=observation_case();span=s.completion_span.model_copy(update={field:value})
    assert p.validate(s.model_copy(update={'completion_span':span}),c).reason_code=='POLICY_OBSERVATION_MISMATCH'


def test_new_span_must_be_direct_root_and_correct_node():
    s,c=observation_case()
    for values in [{'parent_span_id':'parent-span'},{'node_key':'insight_generator'}]:
        assert p.validate(s.model_copy(update={'completion_span':s.completion_span.model_copy(update=values)}),c).reason_code=='POLICY_SPAN_NOT_DIRECT_ROOT'


def test_completed_root_is_not_reopened_by_span_confirmation():
    s,c=observation_case();s=s.model_copy(update={'observed_root_status':'complete'})
    r=p.validate(s,c)
    assert r.decision=='allow' and r.expected_transition.owner=='span'
    assert s.observed_root_status=='complete'
    old,a=authorization_case()
    assert p.validate(old.model_copy(update={'observed_root_status':'complete'}),a).reason_code=='POLICY_ROOT_CLOSED'


@pytest.mark.parametrize('terminal',['interrupted','failed','partial','skipped'])
def test_terminal_span_retained_after_successful_business_commit(terminal):
    s,c=observation_case();s=s.model_copy(update={'completion_span':s.completion_span.model_copy(update={'status':terminal})})
    assert reconcile_report_commit(s.authorization,s.commit_records).accepted is True
    assert p.validate(s,c).reason_code=='POLICY_OBSERVATION_TERMINAL'


def test_repeat_observation_is_readonly_and_missing_trace_is_gap():
    s,c=observation_case()
    completed=s.model_copy(update={'completion_span':s.completion_span.model_copy(update={'status':'complete'})})
    r=p.validate(completed,c)
    assert r.decision=='allow' and r.action=='replay' and r.expected_transition is None
    assert p.validate(s.model_copy(update={'completion_span':None}),c).reason_code=='POLICY_OBSERVATION_MISSING'


def test_old_v11_c19_remains_blocked_and_v12_requires_explicit_new_checkpoint():
    old,c=case('C19')
    assert WorkflowPolicyValidator().validate(old,c).reason_code=='POLICY_CONTRACT_CONFLICT'
    s=PolicySnapshotV12.model_validate({**old.model_dump(mode='json'),'policy_scope':'native_v1.2'})
    assert p.validate(s,c).reason_code=='POLICY_CONTRACT_SUPERSEDED'
    assert p.validate(s.model_copy(update={'policy_scope':'legacy_session_v1'}),c).reason_code=='POLICY_LEGACY_DELEGATED'


def test_v12_only_changes_c19_and_keeps_all_other_frozen_rows():
    root=Path(__file__).resolve().parents[2]
    v11=json.loads((root/'docs/designs/lifecycle-contract-v1.1-2026-10-31/contract-tables.json').read_text())
    path=root/'docs/designs/lifecycle-contract-v1.2-2026-10-31/contract-tables.json'
    v12=json.loads(path.read_text())
    assert len(v12['commands'])==len(SPECS_V12)==33
    assert sha256(path.read_bytes()).hexdigest()==CONTRACT_TABLE_SHA256
    assert [r for r in v11['commands'] if r['id']!='C19']==[r for r in v12['commands'] if not r['id'].startswith('C19-')]
    assert {k:v for k,v in SPECS.items() if k!='C19'}=={k:v for k,v in SPECS_V12.items() if not k.startswith('C19-')}


@pytest.mark.parametrize('target,field,value,expected',[
 ('report','workflow_id','other','COMMIT_OWNER_MISMATCH'),
 ('generation','workflow_id','other','COMMIT_OWNER_MISMATCH'),
 ('ownership','workflow_id','other','COMMIT_OWNER_MISMATCH'),
 ('generation','report_id','other','COMMIT_REPORT_MISMATCH'),
 ('generation','generation_status','failed','COMMIT_REPORT_MISMATCH'),
 ('ownership','accepted_report_attempt',9,'COMMIT_BRANCH_MISMATCH'),
 ('report','digest','b'*64,'COMMIT_REPORT_MISMATCH'),
 ('report','operation_key','old','COMMIT_REPORT_MISMATCH'),
])
def test_commit_crosschecks_every_persistent_record(target,field,value,expected):
    s,c=observation_case();records=s.commit_records
    altered=getattr(records,target).model_copy(update={field:value})
    records=records.model_copy(update={target:altered})
    r=reconcile_report_commit(s.authorization,records)
    assert r.accepted is None and r.reason_code==expected
    assert p.validate(s.model_copy(update={'commit_records':records}),c).reason_code=='POLICY_COMMIT_NOT_CONFIRMED'


def test_wrong_commit_metadata_and_revision_cannot_be_used_as_receipt():
    s,c=observation_case()
    for update in [
        {'committed_revision':s.authorization.authorized_revision},
        {'authorization':s.authorization.model_copy(update={'request_id':'other'})},
    ]:
        records=s.commit_records.model_copy(update={'metadata':s.commit_records.metadata.model_copy(update=update)})
        assert reconcile_report_commit(s.authorization,records).reason_code=='COMMIT_METADATA_MISMATCH'
    assert p.validate(s.model_copy(update={'revision':s.authorization.authorized_revision}),c).reason_code=='POLICY_COMMIT_REVISION_UNCONFIRMED'


def test_absence_is_not_conclusive_without_a_fenced_writer_and_consistent_branch():
    s,c=observation_case()
    pending=s.commit_records.generation.model_copy(update={'generation_status':'generating','report_id':None})
    records=s.commit_records.model_copy(update={'report':None,'ownership':None,'metadata':None,'generation':pending})
    assert reconcile_report_commit(s.authorization,records).status=='unknown'
    fenced=records.model_copy(update={'writer_isolated':True})
    assert reconcile_report_commit(s.authorization,fenced).accepted is False
    old=fenced.model_copy(update={'generation':pending.model_copy(update={'operation_key':'another-current-writer'})})
    assert reconcile_report_commit(s.authorization,old).status=='unknown'


def test_commit_proof_cannot_authorize_another_current_branch():
    s,c=observation_case()
    binding=s.binding.model_copy(update={'execution_id':'new-execution'})
    assert p.validate(s.model_copy(update={'binding':binding}),c.model_copy(update={'binding':binding})).reason_code=='POLICY_COMMAND_SUPERSEDED'


def test_no_trace_at_commit_is_successful_business_with_observation_gap():
    s,c=observation_case()
    a=s.authorization.model_copy(update={'persistence_span_id':None})
    records=s.commit_records.model_copy(update={'metadata':s.commit_records.metadata.model_copy(update={'authorization':a})})
    s=s.model_copy(update={'authorization':a,'commit_records':records,'completion_span':None})
    assert reconcile_report_commit(a,records).accepted is True
    assert p.validate(s,c).reason_code=='POLICY_OBSERVATION_MISSING'


def test_authorization_stage_alone_never_authorizes_observation():
    s,a=authorization_case()
    assert p.validate(s,a).decision=='allow'
    b=a.model_copy(update={'command_id':'C19-B','facts':()})
    assert p.validate(s,b).reason_code=='POLICY_COMMIT_NOT_CONFIRMED'


def test_observation_cannot_smuggle_a_business_write():
    s,c=observation_case()
    injected=c.model_copy(update={'facts':(s.commit_records.report,)})
    assert p.validate(s,injected).reason_code=='POLICY_OBSERVATION_INPUT_INVALID'
    assert p.validate(s,c.model_copy(update={'next_active_execution_key':'new-key'})).reason_code=='POLICY_OBSERVATION_INPUT_INVALID'


def test_c19a_completed_request_replays_no_new_transaction():
    from app.domain.workflow_policy.models import IdempotencyFact
    s,c=authorization_case()
    saved=IdempotencyFact(session_id=s.session_id,workflow_id=s.workflow_id,request_id=c.request_id,
        command_id=c.command_id,payload_hash=c.payload_hash(),status='completed',effective_binding=s.binding,response_ref='saved-report')
    s=s.model_copy(update={'idempotency':(saved,),'revision':s.revision+1,'active_execution_key':None,'observed_root_status':'complete'})
    r=p.validate(s,c)
    assert r.action=='replay' and r.expected_transition is None
    assert p.validate(s,c.model_copy(update={'origin_message_id':'different'})).reason_code=='POLICY_IDEMPOTENCY_CONFLICT'


def test_span_authorization_revision_and_original_key_are_checked_not_current_key():
    s,c=observation_case()
    assert s.active_execution_key is None and p.validate(s,c).action=='observe'
    assert p.validate(s,c.model_copy(update={'expected_revision':s.revision})).reason_code=='POLICY_COMMIT_AUTHORIZATION_MISMATCH'
    assert p.validate(s,c.model_copy(update={'active_execution_key':'new-current-key'})).reason_code=='POLICY_COMMIT_AUTHORIZATION_MISMATCH'


def test_c19b_cannot_accept_another_workflow_or_attempt():
    s,c=observation_case()
    assert p.validate(s,c.model_copy(update={'workflow_id':'other'})).reason_code=='POLICY_WORKFLOW_MISMATCH'
    assert p.validate(s,c.model_copy(update={'binding':c.binding.model_copy(update={'report_attempt':2})})).reason_code=='POLICY_COMMAND_SUPERSEDED'
