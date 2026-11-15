"""Policy-only tests; no migration, live Workflow, database or LLM call."""
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
from pathlib import Path

import pytest
from app.domain.enums import SessionStatus as S
from app.domain.workflow_policy import WorkflowPolicyValidator
from app.domain.workflow_policy.catalogue import CONTRACT_TABLE_SHA256, SPECS
from app.domain.workflow_policy.models import Bindings, IdempotencyFact, TaskFact
from workflow_policy_fixtures import case, digest, fact, replace_fact

ALL = tuple(SPECS)
ACTIVE = tuple(c for c in ALL if c != 'C19')
policy = WorkflowPolicyValidator()


@pytest.mark.parametrize('code', ALL)
def test_frozen_mapping_and_positive_or_explicit_contract_block(code):
    s,c=case(code)
    before=(s.model_dump_json(),c.model_dump_json())
    decision=policy.validate(s,c)
    assert before==(s.model_dump_json(),c.model_dump_json())
    if code=='C19':
        assert decision.decision=='deny' and decision.reason_code=='POLICY_CONTRACT_CONFLICT'
        assert decision.expected_transition is None
    else:
        assert decision.decision=='allow',decision
        assert decision.action=='execute'
        assert (decision.expected_transition.owner,decision.expected_transition.source,decision.expected_transition.target)==(
            SPECS[code].owner,SPECS[code].source,SPECS[code].target)
        assert decision.required_evidence==(SPECS[code].required_evidence,)


@pytest.mark.parametrize('code',ACTIVE)
@pytest.mark.parametrize('mutation,reason',[
 ('workflow','POLICY_WORKFLOW_MISMATCH'),('session','POLICY_WORKFLOW_MISMATCH'),
 ('revision','POLICY_STALE_REVISION'),('key','POLICY_STALE_ACTIVE_KEY'),
 ('binding','POLICY_REFERENCE_MISMATCH'),('missing','POLICY_MISSING_EVIDENCE'),
])
def test_all_commands_reject_bad_owner_revision_key_references_and_missing_evidence(code,mutation,reason):
    s,c=case(code)
    changes={
        'workflow':{'workflow_id':'other'},'session':{'session_id':'other'},
        'revision':{'expected_revision':s.revision+1},'key':{'active_execution_key':'old-key'},
        'binding':{'binding':c.binding.model_copy(update={'dataset_id':'other'})},'missing':{'facts':()},
    }
    if mutation == 'missing' and code.startswith('C16-'):
        s=s.model_copy(update={'facts':replace_fact(s.facts,'failure',None)})
    result=policy.validate(s,c.model_copy(update=changes[mutation]))
    assert result.decision=='deny' and result.reason_code==reason,result


@pytest.mark.parametrize('code',ACTIVE)
def test_all_commands_reject_cross_workflow_evidence(code):
    s,c=case(code)
    if c.facts:
        changed=c.facts[0].model_copy(update={'workflow_id':'other'})
        c=c.model_copy(update={'facts':(changed,)+c.facts[1:]})
    else:
        changed=s.facts[0].model_copy(update={'workflow_id':'other'})
        s=s.model_copy(update={'facts':(changed,)+s.facts[1:]})
    result=policy.validate(s,c)
    assert result.reason_code=='POLICY_WORKFLOW_MISMATCH'


@pytest.mark.parametrize('code',ACTIVE)
def test_all_commands_reject_root_reopen_without_requiring_trace_presence(code):
    s,c=case(code)
    assert policy.validate(s.model_copy(update={'observed_root_status':'complete'}),c).reason_code=='POLICY_ROOT_CLOSED'
    assert policy.validate(s.model_copy(update={'observed_root_status':None}),c).decision=='allow'


@pytest.mark.parametrize('code',ACTIVE)
def test_wrong_state_or_generation_is_rejected(code):
    s,c=case(code)
    if SPECS[code].owner=='control':
        s=s.model_copy(update={'control_status':S.COMPLETED if s.control_status!=S.COMPLETED else S.CREATED})
        expected='POLICY_INVALID_CONTROL_STATE'
    elif code=='C24':
        s=s.model_copy(update={'exists':True})
        expected='POLICY_WORKFLOW_ALREADY_EXISTS'
    else:
        s=s.model_copy(update={'control_status':S.APPROVED})
        expected='POLICY_INVALID_CONTROL_STATE'
    assert policy.validate(s,c).reason_code==expected


@pytest.mark.parametrize('code',ACTIVE)
def test_all_commands_idempotent_replay_has_no_transition_and_conflicts_deny(code):
    s,c=case(code)
    record=IdempotencyFact(session_id=s.session_id,workflow_id=s.workflow_id,request_id=c.request_id,
        command_id=code,payload_hash=c.payload_hash(),status='completed',effective_binding=s.binding,response_ref='saved-response')
    committed=s.model_copy(update={'revision':s.revision+1,'active_execution_key':'changed-key',
                                  'observed_root_status':'complete','idempotency':(record,)})
    decision=policy.validate(committed,c)
    assert decision.decision=='allow' and decision.action=='replay' and decision.expected_transition is None
    assert decision.replay_ref=='saved-response'
    conflict=policy.validate(committed,c.model_copy(update={'origin_message_id':'different-payload'}))
    assert conflict.reason_code=='POLICY_IDEMPOTENCY_CONFLICT'
    pending=committed.model_copy(update={'idempotency':(record.model_copy(update={'status':'in_progress'}),)})
    assert policy.validate(pending,c).reason_code=='POLICY_COMMAND_IN_PROGRESS'


def test_mapping_is_exactly_the_immutable_32_frozen_rows():
    path=Path(__file__).resolve().parents[2]/'docs/designs/lifecycle-contract-v1.1-2026-10-31/contract-tables.json'
    assert sha256(path.read_bytes()).hexdigest()==CONTRACT_TABLE_SHA256
    rows=json.loads(path.read_text())['commands']
    assert set(SPECS)=={r['id'] for r in rows} and len(SPECS)==32
    for r in rows:
        spec=SPECS[r['id']]
        assert (spec.name,spec.owner,spec.source,spec.target,spec.preconditions,spec.required_evidence)==(
            r['name'],r['owner'],r['source'],r['target'],r['guard'],r['persistent_evidence'])
    with pytest.raises(TypeError):SPECS['X']=SPECS['C01']
    with pytest.raises(FrozenInstanceError):SPECS['C01'].target='RUNNING'


@pytest.mark.parametrize('code',ALL)
def test_legacy_scope_is_explicitly_delegated_and_not_changed(code):
    s,c=case(code)
    decision=policy.validate(s.model_copy(update={'policy_scope':'legacy_session_v1'}),c)
    assert decision.reason_code=='POLICY_LEGACY_DELEGATED' and decision.policy_scope=='legacy_session_v1'
    assert decision.decision=='deny' and decision.expected_transition is None


@pytest.mark.parametrize('name',['RESUME_ENGINE','RESUME_ENGINE_TASK','RESUME_ENGINE_STEP','RESUME_REPORT','RESUME_REPORT_CANDIDATE','REOPEN_ROOT'])
def test_unsupported_resume_and_reopen(name):
    s,c=case('C01')
    assert policy.validate(s,c.model_copy(update={'command_id':name})).reason_code=='POLICY_UNSUPPORTED_OPERATION'


def test_unknown_and_invalid_input_not_llm_trace_or_ui_status():
    s,c=case('C01')
    assert policy.validate(s,c.model_copy(update={'command_id':'not-a-command'})).reason_code=='POLICY_UNKNOWN_COMMAND'
    raw=s.model_dump(mode='json');raw['business_lifecycle']='running'
    assert policy.validate(raw,c).reason_code=='POLICY_INVALID_INPUT'
    raw=s.model_dump(mode='json');raw['control_status']='running'
    assert policy.validate(raw,c).reason_code=='POLICY_INVALID_INPUT'
    for source in ['frontend','llm','trace']:
        raw=c.model_dump(mode='json');raw['facts'][0]['source']=source
        assert policy.validate(s,raw).reason_code=='POLICY_INVALID_INPUT'


def change_current(s, kind, **updates):
    current=next(f for f in s.facts if f.kind==kind)
    return s.model_copy(update={'facts':replace_fact(s.facts,kind,current.model_copy(update=updates))})


def change_proposed(c, kind, **updates):
    current=next(f for f in c.facts if f.kind==kind)
    return c.model_copy(update={'facts':replace_fact(c.facts,kind,current.model_copy(update=updates))})


@pytest.mark.parametrize('code',['C03','C04'])
def test_intent_direction_questions_and_original_goal_are_bound(code):
    s,c=case(code)
    assert policy.validate(s,change_proposed(c,'intent',goal_hash=digest('invented goal'))).reason_code=='POLICY_INPUT_CHANGED'
    assert policy.validate(s,change_proposed(c,'intent',next_action='clarify' if code=='C03' else 'proceed')).reason_code=='POLICY_INTENT_DECISION_MISMATCH'
    assert policy.validate(s,change_proposed(c,'intent',artifact_origin='code')).reason_code=='POLICY_REAL_LLM_ARTIFACT_REQUIRED'


@pytest.mark.parametrize('field',['content_hash','profile_options_hash','input_file_id'])
def test_profile_actual_input_and_header_options_cannot_change(field):
    s,c=case('C02')
    assert policy.validate(s,change_proposed(c,'profile',**{field:'changed'})).reason_code=='POLICY_INPUT_CHANGED'


@pytest.mark.parametrize('field',['intent_hash','capability_version'])
def test_old_planner_cannot_commit_after_intent_or_capability_change(field):
    s,c=case('C06')
    assert policy.validate(s,change_proposed(c,'candidate',**{field:'old'})).reason_code=='POLICY_CANDIDATE_MISMATCH'


def test_saved_f0_core_gap_must_not_be_silently_removed():
    s,c=case('C07')
    blocked=dict(executable_task_ids=('B',),blocked_task_ids=('A',),coverage='partial',unmet_requirement_ids=('missing A',))
    invalid=change_proposed(c,'validation',**blocked)
    assert policy.validate(s,invalid).reason_code=='POLICY_CORE_REQUIREMENT_LOST'
    valid=change_proposed(invalid,'validation',unmet_core_task_ids=('A',))
    assert policy.validate(s,valid).decision=='allow'
    assert policy.validate(s,change_proposed(valid,'plan',core_task_ids=())).decision=='deny'


@pytest.mark.parametrize('code',['C08','C09'])
def test_revision_preserves_remaining_tasks_and_new_version(code):
    s,c=case(code)
    invalid=change_proposed(c,'plan',task_ids=('A','B'))
    invalid=change_proposed(invalid,'validation',executable_task_ids=('A','B'))
    assert policy.validate(s,invalid).reason_code=='POLICY_TASK_SELECTION_INVALID'
    assert policy.validate(s,c.model_copy(update={'remove_task_ids':()})).reason_code=='POLICY_TASK_SELECTION_INVALID'
    new=next(f for f in c.facts if f.kind=='plan')
    oldbinding=new.binding.model_copy(update={'plan_version':1})
    invalid=change_proposed(c,'plan',binding=oldbinding)
    invalid=change_proposed(invalid,'validation',binding=oldbinding)
    assert policy.validate(s,invalid).reason_code=='POLICY_PLAN_VERSION_INVALID'


@pytest.mark.parametrize('updates,reason',[
 ({'constraints_verified':False},'POLICY_APPROVAL_BLOCKED'),
 ({'blocking_uncertainty_ids':('U1',)},'POLICY_APPROVAL_BLOCKED'),
 ({'warning_ids':('partial_coverage',)},'POLICY_WARNINGS_NOT_ACKNOWLEDGED'),
 ({'coverage':'blocked'},'POLICY_COVERAGE_BLOCKED'),
])
def test_approval_cannot_bypass_constraints_uncertainties_warnings_or_coverage(updates,reason):
    s,c=case('C10')
    assert policy.validate(change_current(s,'validation',**updates),c).reason_code==reason


@pytest.mark.parametrize('field',['dataset_version','plan_version_id','validation_version','approval_id','execution_id','execution_request_id'])
def test_internal_execution_reference_mismatch_rejected_even_when_command_and_snapshot_binding_match(field):
    s,c=case('C13')
    execution=next(f for f in s.facts if f.kind=='execution')
    altered=execution.binding.model_copy(update={field:'other'})
    s=change_current(s,'execution',binding=altered)
    assert policy.validate(s,c).reason_code=='POLICY_REFERENCE_MISMATCH'


def test_partial_execution_cannot_be_promoted_to_success_or_erase_saved_task():
    s,c=case('C13')
    assert policy.validate(s,c).expected_transition.target=='COMPLETED'
    assert policy.validate(s,change_proposed(c,'execution',execution_outcome='success')).reason_code=='POLICY_EXECUTION_INVALID'
    execution=next(f for f in c.facts if f.kind=='execution')
    saved=execution.tasks[0].model_copy(update={'result_ref':'already-saved-different-result'})
    assert policy.validate(change_current(s,'execution',tasks=(saved,)),c).reason_code=='POLICY_SAVED_TASK_CHANGED'


def test_empty_result_can_be_success_with_real_result_reference():
    s,c=case('C12')
    # No row-count inference: a persisted empty table is still a result reference.
    assert policy.validate(s,c).decision=='allow'
    result=next(f for f in c.facts if f.kind=='execution')
    rows=(result.tasks[0].model_copy(update={'result_ref':None}),)+result.tasks[1:]
    assert policy.validate(s,change_proposed(c,'execution',tasks=rows)).reason_code=='POLICY_MISSING_EVIDENCE'


def test_duplicate_task_progress_requires_idempotent_record_not_new_write():
    s,c=case('C23')
    row=next(f for f in c.facts if f.kind=='task').tasks[0]
    assert policy.validate(change_current(s,'execution',tasks=(row,)),c).reason_code=='POLICY_TASK_ALREADY_RECORDED'


@pytest.mark.parametrize('code',['C17','C18','C20','C21-queued','C21-generating','C22'])
@pytest.mark.parametrize('outcome',['success','partial_success','failed'])
def test_reporting_accepts_truthful_execution_outcome_without_reclassifying_it(code,outcome):
    s,c=case(code)
    execution=next(f for f in s.facts if f.kind=='execution')
    rows=tuple(TaskFact(task_id=t.task_id,status='success' if outcome=='success' or (outcome=='partial_success' and t.task_id=='A') else 'failed',
              result_ref='result-'+t.task_id if outcome=='success' or (outcome=='partial_success' and t.task_id=='A') else None,
              error_code=None if outcome=='success' or (outcome=='partial_success' and t.task_id=='A') else 'TASK_FAILURE') for t in execution.tasks)
    s=change_current(s,'execution',tasks=rows,execution_outcome=outcome)
    s=s.model_copy(update={'control_status':S.FAILED if outcome=='failed' else S.COMPLETED})
    before=s.model_dump_json()
    result=policy.validate(s,c)
    assert result.decision=='allow',result
    assert s.model_dump_json()==before
    assert result.expected_transition.owner=='generation'
    assert result.expected_transition.target==SPECS[code].target


@pytest.mark.parametrize('terminal',['unavailable','completed'])
def test_terminal_reports_never_retry(terminal):
    s,c=case('C22')
    assert policy.validate(change_current(s,'generation',generation_status=terminal),c).reason_code=='POLICY_REPORT_RETRY_UNSUPPORTED'


def test_report_attempt_missing_or_old_execution_cannot_commit():
    s,c=case('C20')
    report=next(f for f in c.facts if f.kind=='report')
    assert policy.validate(s,change_proposed(c,'report',binding=report.binding.model_copy(update={'report_attempt':9}))).reason_code=='POLICY_REFERENCE_MISMATCH'
    assert policy.validate(s,change_proposed(c,'report',binding=report.binding.model_copy(update={'execution_id':'old-execution'}))).reason_code=='POLICY_REFERENCE_MISMATCH'
    s,c=case('C18')
    no_attempt=s.binding.model_copy(update={'report_attempt':None})
    assert policy.validate(s.model_copy(update={'binding':no_attempt}),c.model_copy(update={'binding':no_attempt})).reason_code=='POLICY_MISSING_REFERENCE'


def test_unavailable_must_not_disguise_valid_core_insights():
    s,c=case('C20')
    assert policy.validate(s,change_proposed(c,'report',report_status='complete')).reason_code=='POLICY_REPORT_UNAVAILABLE_INVALID'
    assert policy.validate(s,change_proposed(c,'report',evidence_ids=('E1',),valid_core_insight_count=1)).reason_code=='POLICY_REPORT_UNAVAILABLE_INVALID'


@pytest.mark.parametrize('code',['C15-PLANNING','C21-generating'])
def test_recover_requires_proven_worker_fence_and_never_resumes_computation(code):
    s,c=case(code)
    recovered=c.model_copy(update={'recovery':True,'next_active_execution_key':'recovery-key'})
    assert policy.validate(s,recovered).reason_code=='POLICY_MISSING_EVIDENCE'
    fence=fact('worker_fence',operation_key=s.active_execution_key)
    recovered=recovered.model_copy(update={'facts':recovered.facts+(fence,)})
    result=policy.validate(s,recovered)
    assert result.decision=='allow' and result.expected_transition.target in {'FAILED','failed'}
    old=fence.model_copy(update={'operation_key':'old-instance-key'})
    assert policy.validate(s,recovered.model_copy(update={'facts':replace_fact(recovered.facts,'worker_fence',old)})).reason_code=='POLICY_WORKER_NOT_FENCED'


@pytest.mark.parametrize('code',['C16-PROFILING','C16-PARSING_INTENT','C16-PLANNING','C16-VALIDATING'])
def test_prepare_retry_requires_failed_prepare_and_appropriate_checkpoint(code):
    s,c=case(code)
    assert policy.validate(change_current(s,'failure',retryable=False),c).reason_code=='POLICY_NOT_RETRYABLE'
    assert policy.validate(change_current(s,'failure',failed_phase=S.RUNNING),c).reason_code=='POLICY_NOT_RETRYABLE'
    s=s.model_copy(update={'facts':s.facts+(fact('execution'),)})
    assert policy.validate(s,c).reason_code=='POLICY_PREPARATION_RETRY_FORBIDDEN'


def test_creation_does_not_require_future_entities_but_does_require_message_and_input_scope():
    s,c=case('C24')
    assert s.binding==Bindings() and policy.validate(s,c).decision=='allow'
    assert policy.validate(s,c.model_copy(update={'origin_message_id':'other-message'})).reason_code=='POLICY_ORIGIN_MESSAGE_MISMATCH'
    assert policy.validate(s.model_copy(update={'authorized_input_file_ids':()}),c).reason_code=='POLICY_INPUT_NOT_AUTHORIZED'
    assert policy.validate(s,c.model_copy(update={'parent_workflow_id':c.workflow_id})).reason_code=='POLICY_PARENT_WORKFLOW_MISMATCH'
    assert policy.validate(s.model_copy(update={'reserved_root_ids':(s.root_run_id,)}),c).reason_code=='POLICY_CREATION_CONFLICT'


def test_superseded_or_cross_workflow_idempotency_records_not_replayed():
    s,c=case('C10')
    record=IdempotencyFact(session_id=s.session_id,workflow_id=s.workflow_id,request_id=c.request_id,
        command_id=c.command_id,payload_hash=c.payload_hash(),status='completed',effective_binding=s.binding,response_ref='saved')
    cross=record.model_copy(update={'workflow_id':'other'})
    assert policy.validate(s.model_copy(update={'idempotency':(cross,)}),c).reason_code=='POLICY_WORKFLOW_MISMATCH'
    old=record.model_copy(update={'effective_binding':Bindings()})
    assert policy.validate(s.model_copy(update={'idempotency':(old,)}),c).reason_code=='POLICY_COMMAND_SUPERSEDED'


@pytest.mark.parametrize('code',['C12','C23'])
def test_blocked_tasks_never_enter_execution_results_as_success(code):
    s,c=case(code)
    s=change_current(s,'validation',executable_task_ids=('B',),blocked_task_ids=('A',),unmet_core_task_ids=('A',),
                     unmet_requirement_ids=('A missing',),coverage='partial')
    assert policy.validate(s,c).reason_code=='POLICY_BLOCKED_TASK_EXECUTED'


def test_retry_saved_candidate_different_dataset_is_not_a_valid_checkpoint():
    s,c=case('C16-VALIDATING')
    candidate=next(f for f in s.facts if f.kind=='candidate')
    s=change_current(s,'candidate',binding=candidate.binding.model_copy(update={'dataset_version':'old-version'}))
    assert policy.validate(s,c).reason_code=='POLICY_REFERENCE_MISMATCH'


def test_generation_with_unknown_state_is_not_absent():
    s,c=case('C17')
    s=s.model_copy(update={'facts':s.facts+(fact('generation'),)})
    assert policy.validate(s,c).reason_code=='POLICY_MISSING_EVIDENCE'


def test_model_copy_cannot_bypass_enum_and_scope_validation():
    s,c=case('C01')
    assert policy.validate(s.model_copy(update={'control_status':'running'}),c).reason_code=='POLICY_INVALID_INPUT'
    assert policy.validate(s,c.model_copy(update={'expected_revision':True})).reason_code=='POLICY_INVALID_INPUT'


@pytest.mark.parametrize('code',['C08','C09','C10','C11'])
def test_current_capability_snapshot_required_for_new_approval_or_plan(code):
    s,c=case(code)
    assert policy.validate(s.model_copy(update={'capability_version':'new-capability-version'}),c).reason_code=='POLICY_VALIDATION_MISMATCH'


def test_empty_identifiers_and_string_booleans_cannot_be_valid_evidence():
    s,c=case('C10')
    raw=s.model_dump(mode='json');raw['binding']['plan_id']=''
    assert policy.validate(raw,c).reason_code=='POLICY_INVALID_INPUT'
    raw=s.model_dump(mode='json')
    next(f for f in raw['facts'] if f['kind']=='validation')['constraints_verified']='true'
    assert policy.validate(raw,c).reason_code=='POLICY_INVALID_INPUT'


def test_trace_success_cannot_replace_missing_business_result():
    s,c=case('C17')
    no_execution=s.model_copy(update={'facts':replace_fact(s.facts,'execution',None),'observed_root_status':'running'})
    assert policy.validate(no_execution,c).reason_code=='POLICY_MISSING_EVIDENCE'
    assert policy.validate(no_execution.model_copy(update={'observed_root_status':'complete'}),c).decision=='deny'
