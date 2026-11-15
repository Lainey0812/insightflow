import asyncio
import copy
import json
from pathlib import Path

import pytest

from app.domain.errors import AppError
from app.domain.intent import ParsedIntent
from app.planning.capabilities import CapabilityRegistry
from app.planning.output import request_schema, validate_draft
from app.planning.evaluation import score, signature
from app.services.analysis_planner import AnalysisPlannerService
from intent_fixtures import intent_payload
from planning_fixtures import PlannerProvider, recruiting_profile, task, step


def test_provider_schema_nonblank_equivalence_without_domain_change():
    registry=CapabilityRegistry(); original=registry.request_schema()
    normalized=request_schema(registry)
    assert normalized['$defs']['AnalysisTask']['properties']['title']['pattern']==r'[\s\S]*\S[\s\S]*'
    assert registry.request_schema()==original
    assert original['$defs']['AnalysisTask']['properties']['title']['pattern']==r'\S'


@pytest.mark.parametrize('text,code',[('{"tasks":[],"tasks":[]}','PLANNER_INVALID_JSON'),
    ('NaN','PLANNER_INVALID_JSON'),('[]','PLANNER_SCHEMA_INVALID'),
    ('x'*131073,'PLANNER_OUTPUT_TOO_LARGE')])
def test_stages_reject_invalid_outputs(text,code):
    with pytest.raises(AppError) as caught:validate_draft(text,CapabilityRegistry())
    assert caught.value.error.code==code
    assert caught.value.error.details['stage'] in ('json','schema')


def test_duplicate_task_ids_do_not_escape_as_internal_error():
    with pytest.raises(AppError) as caught:
        validate_draft(json.dumps({'tasks':[task(),task()]}),CapabilityRegistry())
    assert caught.value.error.code=='PLANNER_SCHEMA_INVALID'


def test_total_deadline_shared_by_retries():
    class Slow(PlannerProvider):
        cancelled=False
        async def generate(self,request):
            self.requests.append(request)
            try:await asyncio.sleep(.03)
            except asyncio.CancelledError:self.cancelled=True;raise
            from app.llm.base import LLMResponse
            return LLMResponse(text='bad',provider='scripted',is_mock=True)
    p=Slow();service=AnalysisPlannerService(p,CapabilityRegistry(),.05)
    with pytest.raises(AppError) as caught:
        asyncio.run(service.plan(ParsedIntent.model_validate(intent_payload()),recruiting_profile()))
    assert caught.value.error.code=='LLM_TIMEOUT'
    assert len(p.requests)==2 and p.cancelled


def test_business_error_never_runs_auto_repair():
    p=PlannerProvider({'tasks':[task(priority='P1')]})
    with pytest.raises(AppError) as caught:
        asyncio.run(AnalysisPlannerService(p,CapabilityRegistry()).plan(ParsedIntent.model_validate(intent_payload()),recruiting_profile()))
    assert caught.value.error.code=='PLANNER_BUSINESS_INVALID' and len(p.requests)==1


def test_constraints_and_uncertainty_preserved_in_existing_contract():
    raw=intent_payload();raw['constraints']['filters']=[{'raw_text':'不包括上海','validation_status':'unverified'}]
    raw['uncertainties']=[{'id':'quality','issue':'样本范围待说明','reason':'影响解释','action':'annotate','resolve_at':'before_execution'}]
    intent=ParsedIntent.model_validate(raw);p=PlannerProvider()
    out=asyncio.run(AnalysisPlannerService(p,CapabilityRegistry(),enable_thinking=False).plan(intent,recruiting_profile()))
    assert out.intent_snapshot==intent
    assert any('不包括上海' in r.description for r in out.plan.core_requirements)
    assert out.unmet_core_requirements and out.coverage_status=='partial'
    assert p.requests[0].enable_thinking is False
    context=json.loads(p.requests[0].instruction)
    assert context['intent']['uncertainties'][0]['action']=='annotate'
    assert not {'rows','samples','semantic_tags'} & set(context['profile'])


@pytest.mark.parametrize('kwargs',[{'max_attempts':0},{'max_attempts':True},{'max_attempts':4},{'enable_thinking':'false'}])
def test_constructor_rejects_invalid_config(kwargs):
    with pytest.raises(ValueError):AnalysisPlannerService(PlannerProvider(),CapabilityRegistry(),**kwargs)


def test_safe_provider_error_does_not_echo_credentials():
    p=PlannerProvider(AppError('LLM_HTTP_ERROR','private-key-value',502,details={'body':'private-key-value'}))
    with pytest.raises(AppError) as caught:
        asyncio.run(AnalysisPlannerService(p,CapabilityRegistry()).plan(ParsedIntent.model_validate(intent_payload()),recruiting_profile()))
    assert 'private-key-value' not in str(caught.value.error.model_dump())
    assert caught.value.error.details['stage']=='call' and len(p.requests)==1


def test_eval_detects_extra_metrics_and_forbidden_fields():
    profile=recruiting_profile()
    candidate=task([step(params={'dimensions':['field_0001'],'metrics':[{'function':'count','field':None,'alias':'n'},{'function':'avg','field':'field_0003','alias':'salary'}]})])
    out=asyncio.run(AnalysisPlannerService(PlannerProvider({'tasks':[candidate]}),CapabilityRegistry()).plan(ParsedIntent.model_validate(intent_payload()),profile))
    case={'expected':{'metrics':[{'field':None,'function':'count'}],'dimensions':['城市'],'forbidden_fields':['薪资']}}
    result=score(case,out,profile)
    assert not result['passed']
    assert {'no_unrequested_metrics','no_forbidden_field'} <= {c['kind'] for c in result['failures']}


def test_signatures_ignore_generated_aliases_not_priority_or_operations():
    out=asyncio.run(AnalysisPlannerService(PlannerProvider(),CapabilityRegistry()).plan(ParsedIntent.model_validate(intent_payload()),recruiting_profile()))
    changed=copy.deepcopy(out);changed.plan.tasks[0].steps[0].params['metrics'][0]['alias']='another'
    assert signature(out)==signature(changed)
    changed.plan.tasks[0].priority='P1'
    assert signature(out)!=signature(changed)


def test_eval_fixture_covers_four_topics_and_known_fields():
    from app.profiling.profiler import build_profile
    suite=json.loads((Path(__file__).parents[1]/'evaluation/planner_cases_v1.json').read_text())
    assert len(suite['cases'])==25 and len(suite['datasets'])==4
    assert not suite['human_reviewed']
    assert len({c['id'] for c in suite['cases']})==25
    for c in suite['cases']:
        ParsedIntent.model_validate(c['intent'])
        d=suite['datasets'][c['dataset']];profile=build_profile(d['csv'].encode(),'.csv','e',d['filename'])
        names={f.display_name for f in profile.fields}
        assert set(c['expected'].get('dimensions',[])) <= names
        assert all(m['field'] is None or m['field'] in names for m in c['expected'].get('metrics',[]))
