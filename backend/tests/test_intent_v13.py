import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.domain.errors import AppError
from app.domain.intent import ParsedIntent, IntentArtifact
from app.intent.reliable_evaluation import score_case, summary, goal_stances
from app.intent.validation import validate_output
from app.services.intent_parser import IntentParserService
from tests.intent_fixtures import intent_payload, StubProvider

ROOT=Path(__file__).parents[2]
SUITES=[json.loads((ROOT/'backend/evaluation'/name).read_text()) for name in
 ['intent_regression_v13.json','intent_previous28_v13.json','intent_heldout_v13.json','intent_negation_v13.json','intent_combinations_v13.json']]
CASES={c['id']:c for s in SUITES for c in s['cases']}


def payload(metrics=(), limits=(), filters=(), time=None, goal='分析数据'):
    p=intent_payload(business_goal=goal)
    for category,texts in [('metric_requirements',metrics),('analysis_limits',limits),('filters',filters)]:
        p['constraints'][category]=[{'raw_text':s,'validation_status':'unverified'} for s in texts]
    if time:p['constraints']['time_range']={'raw_text':time,'validation_status':'unverified'}
    return p


@pytest.mark.parametrize('case_id',['N07','N10','N11'])
def test_real_v12_high_risk_outputs_remain_detected(case_id):
    old=json.loads((ROOT/'docs/evaluations/intent-v1.2/heldout-live.json').read_text())
    r=next(r for r in old['records'] if r['case_id']==case_id)
    result=IntentArtifact.model_validate(r['result'])
    assert score_case(CASES[case_id],result)['negation_error']


@pytest.mark.parametrize('case_id,p',[
 ('N07',payload(['点击次数'],goal='计算点击次数')),
 ('N10',payload(['平均响应分钟'],goal='计算平均响应分钟')),
 ('N11',payload(['薪资中位数'],['不排除北京'],goal='比较各城市薪资中位数，不排除北京')),
])
def test_correct_fixed_regressions_keep_same_schema_and_literal_grounding(case_id,p):
    result=validate_output(json.dumps(p,ensure_ascii=False),[CASES[case_id]['query']])
    assert score_case(CASES[case_id],result)['passed']


@pytest.mark.parametrize('text,expected',[
 ('计算成交金额','required'),('不要求计算成交金额','optional'),
 ('成交金额尚未指定','unspecified'),('不要计算成交金额','prohibited'),
 ('可以不计算成交金额','optional'),('明确排除成交金额的计算','prohibited'),
 ('探索成交金额（口径未指定）','required'),
 ('成交金额没有指定','unspecified'),
])
def test_four_stances_and_parenthetical_escape(text,expected):
    assert goal_stances(text,['成交金额'])[0]['stance']==expected


def test_prohibition_cannot_be_weakened_to_optional_in_goal():
    p=payload(['薪资中位数'],['不要计算薪资均值'],goal='比较薪资中位数，薪资均值为可选分析')
    assert score_case(CASES['N01'],ParsedIntent.model_validate(p))['negation_error']


def test_sort_context_is_valid_only_when_metric_also_present_independently():
    p=payload(['销售额'],['按销售额排名，取前五名'],['华东地区','已完成订单'],'2026年')
    assert score_case(CASES['S04'],ParsedIntent.model_validate(p))['passed']
    p['constraints']['metric_requirements']=[]
    r=score_case(CASES['S04'],ParsedIntent.model_validate(p))
    assert not r['passed'] and r['matched_constraints']<r['required_constraints']


def test_ordering_cannot_be_satisfied_only_inside_metric():
    p=payload(['按销售额排名'],['前五名'],['华东地区','已完成'],'2026年')
    r=score_case(CASES['S04'],ParsedIntent.model_validate(p))
    assert not r['prediction_checks'][3]['reference_aligned']  # time, two filters, metric
    assert not r['passed']


def test_equivalent_top_n_fragment_requires_explicit_result_context():
    p=payload(['平均响应分钟'],['升序排名','展示前四类'],goal='按平均响应分钟对工单类别排名')
    assert score_case(CASES['O03'],ParsedIntent.model_validate(p))['passed']
    p['analysis_goal']['business_goal']='按平均响应分钟排名'
    assert not score_case(CASES['O03'],ParsedIntent.model_validate(p))['passed']


def test_redundancy_mixed_long_clauses_and_meaningless_actions_lower_precision():
    p=payload(['销售额','销售额'],['比较','按销售额排名，取前五名'],['只看2026年华东地区的已完成订单'],'2026年')
    before=copy.deepcopy(p)
    r=score_case(CASES['S04'],ParsedIntent.model_validate(p))
    assert not r['passed'] and summary([r])['metrics']['constraint_precision']<1
    assert p==before
    assert any(i['duplicate'] for i in r['prediction_checks'])


def test_known_unrequested_core_goal_is_detected_even_with_correct_constraints():
    p=payload(['销售额'],goal='比较各地区销售额，并计算成本')
    r=score_case(CASES['S06'],ParsedIntent.model_validate(p))
    assert r['unrequested_core_goal'] and not r['passed']


def test_c07_explanations_may_paraphrase_but_constraint_values_must_be_real_spans():
    query=CASES['C07']['query'];p=intent_payload('goal_driven','clarify',business_goal='对若干客户的响应耗时进行比较')
    p['constraints']['filters']=[{'raw_text':'指定客户','validation_status':'unverified'}]
    p['constraints']['metric_requirements']=[{'raw_text':'响应时长','validation_status':'unverified'}]
    p['uncertainties'][0]['description']='尚无客户名称，无法确定子集。'
    assert validate_output(json.dumps(p,ensure_ascii=False),[query]).next_action=='clarify'
    for fabricated in ['指定客户还没告诉你','客户A','上海']:
        p['constraints']['filters'][0]['raw_text']=fabricated
        with pytest.raises(AppError) as caught:validate_output(json.dumps(p,ensure_ascii=False),[query])
        assert caught.value.error.code=='LLM_UNGROUNDED_OUTPUT'
        assert caught.value.error.details['validation_errors'][0]['path']==['constraints','filters',0,'raw_text']
        assert fabricated not in json.dumps(caught.value.error.details,ensure_ascii=False)


def test_constraints_cannot_join_separate_clarification_sources():
    p=payload(['销售额'],filters=['华东已完成'])
    with pytest.raises(AppError):validate_output(json.dumps(p,ensure_ascii=False),['只看华东，分析销售额','只看已完成'])


def test_grounding_retry_explains_span_policy_without_returning_bad_values():
    from app.profiling.profiler import build_profile
    query=CASES['C07']['query'];good=intent_payload('goal_driven','clarify')
    good['constraints']['filters']=[{'raw_text':'指定客户','validation_status':'unverified'}]
    bad=copy.deepcopy(good);bad['constraints']['filters'][0]['raw_text']='private-fabricated-client'
    class Sequential(StubProvider):
        async def generate(self,request):
            self.payload=bad if not self.requests else good
            return await super().generate(request)
    provider=Sequential();profile=build_profile(SUITES[0]['datasets']['support']['csv'].encode(),'.csv','t','support.csv')
    result=asyncio.run(IntentParserService(provider).parse(query,profile))
    assert result.llm_attempts==2
    retry=json.loads(provider.requests[1].instruction)['validation_feedback']
    assert '连续原话' in retry['instruction'] and 'private-fabricated-client' not in json.dumps(retry)


def test_all_new_references_are_grounded_unique_and_not_prompt_examples():
    SYSTEM_PROMPT=(ROOT/'docs/evaluations/intent-v1.3/prompt.txt').read_text()
    assert [len(s['cases']) for s in SUITES]==[40,28,20,12,8]
    all_cases=[c for s in SUITES for c in s['cases']]
    # Original ambiguous phrase occurs against two different datasets; preserve it.
    assert len({(c['dataset'],c['query']) for c in all_cases})==108
    prior_queries={c['query'] for s in SUITES[:2] for c in s['cases']}
    new_queries=[c['query'] for s in SUITES[2:] for c in s['cases']]
    assert len(set(new_queries))==40 and not prior_queries & set(new_queries)
    for suite in SUITES:
        assert suite['human_reviewed'] is False
        for c in suite['cases']:
            assert all(u['text'] in c['query'] for u in c['focused_units'])
    assert all(c['query'] not in SYSTEM_PROMPT for s in SUITES[2:] for c in s['cases'])
    assert ParsedIntent.model_json_schema()==json.loads((ROOT/'docs/intent-output.schema.json').read_text())


def test_v12_frozen_source_can_still_be_verified_after_new_prompt_revision():
    folder=ROOT/'docs/evaluations/intent-v1.2'
    for path,digest in json.loads((folder/'freeze-manifest.json').read_text())['sha256'].items():
        assert hashlib.sha256((folder/'frozen-source'/path).read_bytes()).hexdigest()==digest


def test_call_error_is_failure_and_negation_is_not_verified():
    r=score_case(CASES['N07'],error={'code':'LLM_TIMEOUT'})
    result=summary([r])
    assert result['metrics']['call_success_rate']==0 and result['metrics']['constraint_precision'] is None
    assert result['negation_unassessed_count']==1 and not result['semantic_acceptance_passed']


def test_eval_recorder_keeps_invalid_attempts_but_redacts_key():
    from scripts.evaluate_intent import EvaluationRecorder
    from app.llm.base import LLMResponse
    class Provider:
        async def generate(self,request):return LLMResponse(text='bad JSON private-key',provider='test',model='fixture',is_mock=True)
    recorder=EvaluationRecorder(Provider(),'private-key')
    asyncio.run(recorder.generate(None))
    assert recorder.attempts[0]['text']=='bad JSON [REDACTED]'
    assert 'private-key' not in json.dumps(recorder.attempts)
