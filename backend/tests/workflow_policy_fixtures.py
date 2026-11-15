"""Synthetic trusted domain facts; no DB, Provider or production adapters."""
from hashlib import sha256
from app.domain.enums import SessionStatus as S
from app.domain.workflow_policy.catalogue import SPECS
from app.domain.workflow_policy.models import (Bindings, BusinessFact, PolicyCommand, PolicySnapshot, TaskFact)


def digest(value):
    return sha256(value.encode()).hexdigest()


def fact(kind, binding=None, **values):
    data = dict(kind=kind, session_id='session-1', workflow_id='workflow-1', fact_id=kind+'-1',
                digest=digest(kind), binding=binding or Bindings())
    data.update(values)
    return BusinessFact(**data)


def replace_fact(facts, kind, replacement):
    return tuple(f for f in facts if f.kind != kind) + ((replacement,) if replacement else ())


def case(code):
    spec = SPECS[code]
    ds = Bindings(dataset_id='file-1', dataset_version='v1')
    pb = ds.model_copy(update=dict(plan_version_id='plan-version-1', plan_id='plan-1', plan_version=1, validation_version='val-1'))
    ab = pb.model_copy(update={'approval_id': 'approval-1'})
    eb = ab.model_copy(update={'execution_id': 'execution-1', 'execution_request_id': 'execution-request-1'})
    rb = eb.model_copy(update={'report_attempt': 1})
    key, new_key = 'active-key-1', 'new-key-2'
    inp = fact('input', input_file_id='file-1', content_hash=digest('content'), goal_hash=digest('goal'),
               profile_options_hash=digest('options'), answers_hash=digest('answers'))
    profile = fact('profile', ds, input_file_id=inp.input_file_id, content_hash=inp.content_hash,
                   profile_options_hash=inp.profile_options_hash)
    intent = fact('intent', ds, artifact_origin='llm', next_action='proceed', goal_hash=inp.goal_hash,
                  answers_hash=inp.answers_hash)
    candidate = fact('candidate', ds.model_copy(update={'plan_id': 'plan-1', 'plan_version': 1}),
                     artifact_origin='llm', intent_hash=intent.digest, capability_version='cap-1',
                     task_ids=('A', 'B'), core_task_ids=('A',))
    plan = fact('plan', pb, fact_id=pb.plan_version_id, intent_hash=intent.digest,
                task_ids=('A', 'B'), core_task_ids=('A',))
    validation = fact('validation', pb, candidate_hash=plan.digest, source_candidate_hash=candidate.digest,
                      capability_version='cap-1', executable_task_ids=plan.task_ids, coverage='complete', constraints_verified=True)
    approved = fact('approval', ab, fact_id='approval-1', approval_status='approved',intent_hash=intent.digest)
    execution = fact('execution', eb, fact_id='execution-1', execution_outcome='running', operation_key=key)
    generation = fact('generation', rb, generation_status=spec.source if spec.owner=='generation' else 'queued', operation_key=key)
    all_facts = (inp, profile, intent, plan, validation, approved, execution)
    facts, proposed, binding = (inp,), (), Bindings()
    state = S(spec.source) if spec.owner=='control' else S.COMPLETED
    root = 'running'
    if code == 'C01':
        proposed = (inp,)
    elif code == 'C02':
        proposed = (profile.model_copy(update={'operation_key': key}),)
    elif code in {'C03', 'C04'}:
        facts, binding = (inp, profile), ds
        proposed = (intent.model_copy(update={'next_action': 'proceed' if code=='C03' else 'clarify',
                    'questions': () if code=='C03' else ('请明确目标',), 'operation_key': key}),)
    elif code == 'C05':
        facts, binding = (inp, profile, intent.model_copy(update={'next_action':'clarify','questions':('请明确',)})), ds
        proposed = (fact('answer', ds, goal_hash=inp.goal_hash, answers_hash=digest('new answers')),)
    elif code == 'C06':
        facts, binding = (inp, profile, intent), ds
        proposed = (candidate.model_copy(update={'operation_key':key}),)
    elif code == 'C07':
        facts, binding = (inp, profile, intent, candidate), ds
        proposed = (plan.model_copy(update={'operation_key':key}), validation.model_copy(update={'operation_key':key}))
    elif code in {'C08','C09'}:
        binding = pb if code=='C08' else ab
        facts = (inp, profile, intent, plan, validation) + ((approved,) if code=='C09' else ())
        new_pb = pb.model_copy(update={'plan_version':2,'plan_version_id':'plan-version-2'})
        new_plan = plan.model_copy(update={'binding':new_pb,'fact_id':'plan-version-2','task_ids':('A',), 'digest':digest('new-plan')})
        new_validation = validation.model_copy(update={'binding':new_pb,'candidate_hash':new_plan.digest,'executable_task_ids':('A',)})
        proposed = (new_plan,new_validation)
    elif code == 'C10':
        facts, binding, proposed = (inp, profile, intent, plan, validation), pb, (approved,)
    elif code == 'C11':
        facts, binding = (inp, profile, intent, plan, validation, approved), ab
        proposed = (execution.model_copy(update={'operation_key':new_key}),)
    elif code in {'C12','C13','C14','C23'}:
        facts, binding = all_facts, eb
        if code=='C23':
            proposed = (fact('task', eb, operation_key=key, tasks=(TaskFact(task_id='A',status='success',result_ref='result-A'),)),)
        else:
            rows = tuple(TaskFact(task_id=t, status='success' if code=='C12' or (code=='C13' and t=='A') else 'failed',
                                  result_ref='result-'+t if code=='C12' or (code=='C13' and t=='A') else None,
                                  error_code=None if code=='C12' or (code=='C13' and t=='A') else 'TASK_ERROR') for t in plan.task_ids)
            proposed = (execution.model_copy(update={'tasks':rows,'execution_outcome':{'C12':'success','C13':'partial_success','C14':'failed'}[code]}),)
    elif code.startswith('C15-'):
        proposed = (fact('failure', error_code='NODE_FAILED',failed_phase=state,operation_key=key),)
    elif code.startswith('C16-'):
        target=spec.target
        facts=(inp,fact('failure',failed_phase=S.PLANNING,retryable=True,error_code='LLM_TIMEOUT'))
        if target!='PROFILING':
            facts+=(profile,);binding=ds
        if target in {'PLANNING','VALIDATING'}: facts+=(intent,)
        if target=='VALIDATING':facts+=(candidate,)
        root='failed'
    elif spec.owner=='generation':
        execution = execution.model_copy(update={'execution_outcome':'success','tasks':tuple(
            TaskFact(task_id=t,status='success',result_ref='result-'+t) for t in plan.task_ids)})
        facts=(inp,profile,intent,plan,validation,approved,execution)
        binding=eb if code=='C17' else rb
        if code!='C17':facts+=(generation,)
        if code in {'C17','C18','C22'}:
            new_binding=rb.model_copy(update={'report_attempt':2 if code=='C22' else 1})
            proposed=(generation.model_copy(update={'binding':new_binding,'generation_status':spec.target,
                       'operation_key':new_key if code in {'C17','C22'} else key}),)
        elif code.startswith('C21-'):
            proposed=(fact('failure',rb,error_code='REPORT_FAILED',operation_key=key),)
        else:
            proposed=(fact('report',rb,report_status='complete' if code=='C19' else 'unavailable',
                      goal_coverage='complete' if code=='C19' else 'blocked',
                      evidence_ids=('E1',) if code=='C19' else (),valid_core_insight_count=1 if code=='C19' else 0,
                      error_code=None if code=='C19' else 'NO_VALID_EVIDENCE',operation_key=key),)
        if code=='C22':root='partial'
    elif code=='C24':
        state=None;root=None
        proposed=(inp,fact('message',fact_id='message-1'))
    s=PolicySnapshot(session_id='session-1',workflow_id='workflow-1',root_run_id='root-1',control_status=state,
                     revision=0 if code=='C24' else 7,exists=code!='C24',binding=binding,facts=facts,
                     active_execution_key=None if code=='C24' else key,observed_root_status=root,
                     capability_version='cap-1',origin_message_id='message-1',authorized_input_file_ids=('file-1',),existing_workflow_ids=('workflow-parent',))
    c=PolicyCommand(command_id=code,session_id=s.session_id,workflow_id=s.workflow_id,request_id='execution-request-1' if code=='C11' else 'request-'+code,
                    expected_revision=s.revision,active_execution_key=s.active_execution_key,
                    next_active_execution_key=new_key if code in {'C01','C05','C11','C17','C22'} or code.startswith('C16-') else None,
                    binding=binding,facts=proposed,remove_task_ids=('B',) if code in {'C08','C09'} else (),
                    origin_message_id='message-1' if code=='C24' else None)
    return s,c
