"""Explicit versioned scope clarification never bypasses approval or mutates source data."""
import json
import pytest
from app.domain.dataset_profile import DatasetProfile
from app.review.confirmed_scope import decode,PREFIX
from app.review.constraint_audit import ConstraintAuditor
from app.planning.validator import PlanValidator
from app.planning.capabilities import CapabilityRegistry
from planning_fixtures import plan,task,step
from intent_fixtures import intent_payload
from hitl_fixtures import approval,execution


def create_scope(client,extra=False,values=None):
    goal='分析AI产品经理岗位分布'
    raw='岗位名称,城市\nAI产品经理,北京\nai产品经理,上海\nAI 产品经理（客服）,上海\n高级AI产品经理,杭州\nAIGC产品经理,北京\n数据分析师,上海\n'
    r=client.post('/api/v1/sessions',data={'manual_review':'true','goal':goal},files={'file':('scope.csv',raw.encode(),'text/csv')});s=r.json();client.headers['X-Session-Token']=s.pop('review_access_token')
    specs=[step('filter',{'conditions':[{'field':'field_0001','operator':'in','value':values or ['AI产品经理']}]}),step('group_aggregate',{'dimensions':['field_0002'],'metrics':[{'function':'count','alias':'n'}]},'S2')]
    proposed=plan([task(specs)],DatasetProfile.model_validate(s['profile']))
    intent=intent_payload(business_goal=goal);intent['constraints']['filters']=[{'raw_text':'AI产品经理','validation_status':'unverified'}]
    if extra:intent['constraints']['analysis_limits']=[{'raw_text':'未指定薪资口径','validation_status':'unverified'}]
    r=client.post(f'/api/v1/sessions/{s["id"]}/plans',json={'expected_revision':s['revision'],'plan':proposed,'intent':intent});assert r.status_code==200,r.text
    return r.json()


def request(s,mode='normalized_contains'):
    r=s['review_plan'];return {'expected_revision':s['revision'],'plan_id':r['plan_id'],'plan_version':r['plan_version'],'field_id':'field_0001','filter_index':0,'keyword':'AI产品经理','mode':mode}


def preview(client,s,mode='normalized_contains'):
    return client.post(f'/api/v1/sessions/{s["id"]}/scope-preview',json=request(s,mode))


def confirm(client,s,mode='normalized_contains'):
    r=preview(client,s,mode);assert r.status_code==200,r.text
    return client.post(f'/api/v1/sessions/{s["id"]}/scope-confirmations',json={**request(s,mode),'preview_digest':r.json()['preview_digest']})


def test_normalized_variants_preview_is_read_only_and_does_not_expand_to_synonyms(client):
    s=create_scope(client);r=preview(client,s);assert r.status_code==200,r.text
    p=r.json();assert p['matched_row_count']==4 and p['dataset_row_count']==6
    assert p['scope']['values']==['AI产品经理','ai产品经理','AI 产品经理（客服）','高级AI产品经理']
    assert client.get(f'/api/v1/sessions/{s["id"]}').json()==s
    assert preview(client,s,'exact').json()['matched_row_count']==1


def test_confirmation_creates_immutable_version_and_executes_only_after_new_approval(client):
    s=create_scope(client);sid=s['id'];old=s['review_plan'];r=confirm(client,s);assert r.status_code==200,r.text
    current=r.json();assert current['current_plan_version']==2 and current['engine_approval'] is None
    assert current['review_plan']['change_type']=='scope_confirmed'
    assert client.get(f'/api/v1/sessions/{sid}/plans/1').json()==old
    assert client.post('/api/v1/executions',json=execution(current)).status_code==409
    view=client.get(f'/api/v1/sessions/{sid}/review').json()
    assert view['can_approve'] and view['audit']['all_verified'] and view['audit']['audit_version']=='2.3'
    assert '忽略英文大小写及空白' in view['conditions'][0]['text'] and PREFIX not in view['conditions'][0]['text']
    approved=client.post(f'/api/v1/sessions/{sid}/approvals',json=approval(current)).json()
    out=client.post('/api/v1/executions',json=execution(approved));assert out.status_code==200,out.text
    result=out.json();assert result['execution_status']=='success'
    values=result['tasks'][0]['result']['rows'];assert sum(row['n'] for row in values)==4


def test_confirmation_cannot_clear_other_constraints_or_accept_stale_preview(client):
    s=create_scope(client,True);p=preview(client,s).json()
    bad=client.post(f'/api/v1/sessions/{s["id"]}/scope-confirmations',json={**request(s),'preview_digest':'0'*64})
    assert bad.status_code==409 and client.get(f'/api/v1/sessions/{s["id"]}').json()==s
    current=confirm(client,s).json();view=client.get(f'/api/v1/sessions/{s["id"]}/review').json();assert not view['can_approve']
    assert client.post(f'/api/v1/sessions/{s["id"]}/scope-confirmations',json={**request(s),'preview_digest':p['preview_digest']}).status_code==409
    response=client.post(f'/api/v1/sessions/{s["id"]}/approvals',json=approval(current));assert response.status_code==409


def test_wrong_field_or_constraint_source_is_not_silently_selected(client):
    s=create_scope(client)
    for change in [{'field_id':'field_0002'},{'keyword':'其他岗位'},{'filter_index':9}]:
        r=client.post(f'/api/v1/sessions/{s["id"]}/scope-preview',json={**request(s),**change})
        assert r.status_code==409
    assert len(client.get(f'/api/v1/sessions/{s["id"]}/plans').json())==1


def test_model_guessed_names_are_aligned_on_the_review_page(client):
    s=create_scope(client,values=['AI产品经理','人工智能产品经理']);view=client.get(f'/api/v1/sessions/{s["id"]}/review').json()
    assert view['scope_questions']==[{'filter_index':0,'keyword':'AI产品经理','field_id':'field_0001','field_name':'岗位名称'}]
    assert not view['can_approve'] and any('本页预览' in item['next_step'] for item in view['issues'])
    current=confirm(client,s).json();values=current['review_plan']['validated_plan']['plan']['tasks'][0]['steps'][0]['params']['conditions'][0]['value']
    assert values==['AI产品经理','ai产品经理','AI 产品经理（客服）','高级AI产品经理'] and '人工智能产品经理' not in values
    assert client.get(f'/api/v1/sessions/{s["id"]}/review').json()['can_approve']


def test_unrelated_membership_is_not_offered_as_a_scope_question(client):
    s=create_scope(client,values=['北京','上海']);view=client.get(f'/api/v1/sessions/{s["id"]}/review').json()
    assert view['scope_questions']==[] and preview(client,s).status_code==409
    assert all('重新提出需求' in item['next_step'] for item in view['issues'] if item['code']=='UNVERIFIED_CONSTRAINTS')


def test_exact_confirmation_does_not_silently_include_variants(client):
    s=create_scope(client);r=confirm(client,s,'exact');assert r.status_code==200,r.text
    values=r.json()['review_plan']['validated_plan']['plan']['tasks'][0]['steps'][0]['params']['conditions'][0]['value']
    assert values==['AI产品经理']


def test_canonical_scope_cannot_authorize_extra_values_and_punctuation_is_not_split(client):
    s=create_scope(client);profile=DatasetProfile.model_validate(s['profile'])
    good=PREFIX+json.dumps({'field_id':'field_0001','keyword':'AI产品经理','mode':'normalized_contains','values':['AI 产品经理（客服,运营）']},ensure_ascii=False)
    assert decode(good,profile) is not None
    bad=good.replace('AI 产品经理（客服,运营）','数据分析师');assert decode(bad,profile) is None
    assert ConstraintAuditor(profile).parse(good,'filters')[0].value['value']==['AI 产品经理（客服,运营）']
    assert ConstraintAuditor(profile).parse(good,'analysis_limits') is None
