"""Replay preserved real candidates and verify safety independently of new model quality."""
import asyncio
import copy
import json
from pathlib import Path
import pytest
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.dataset_profile import DatasetProfile
from app.domain.execution import ExecutionResultV1, ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
from app.domain.errors import AppError
from app.reporting.draft_v2 import InsightSelection, selection_schema, allowed_finding_types
from app.reporting.materialize_v2 import materialize_selection, invalid_candidates
from app.reporting.presentation import build_presentation
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from app.llm.base import LLMResponse
from report_fixtures import ReportProvider, report_case
from test_report_draft_v2 import context, choice

BASE=Path(__file__).resolve().parents[2]/'docs/evaluations/direction-first-acceptance-v1-2026-11-09/runs/frozen-baseline-01'


def replay(cid):
    folder=BASE/cid
    state=json.loads((folder/'prepared-session.json').read_text())
    approved=json.loads((folder/'approval-response.json').read_text())['engine_approval']
    intent=ParsedIntent.model_validate(state['review_plan']['validated_plan']['intent_snapshot'])
    validated=ValidatedAnalysisPlan.model_validate(state['review_plan']['validated_plan'])
    execution=ExecutionResultV1.model_validate_json((folder/'execution-complete.json').read_text())
    profile=DatasetProfile.model_validate_json((folder/'profile.json').read_text())
    outputs=[]
    for file in sorted(folder.glob('http-*-response.json')):
        raw=json.loads(file.read_text())['text']
        try:value=json.loads(raw)
        except ValueError:continue
        if 'insights' in value:outputs.append(raw)
    class SavedOutput:
        calls=0
        async def generate(self,request):
            value=outputs[self.calls];self.calls+=1
            return LLMResponse(text=value,provider='saved-real-output-replay',model='qwen3.8-flash-recording',is_mock=True)
    provider=SavedOutput()
    result=asyncio.run(AnalysisReportService(provider,CapabilityRegistry()).generate(intent,validated,execution,profile,
        approved_snapshot=ApprovedExecutionSnapshot.model_validate(approved),original_query=state['user_goal']))
    assert provider.calls==len(outputs)  # No new call or fallback repair loop.
    return result,execution,profile


def test_request_schema_cannot_pair_difference_primary_with_concentration():
    ctx=context();schema=selection_schema(ctx[0],ctx[4],ctx[5],[])
    difference=next(e for e in ctx[0] if e.evidence_type=='difference')
    assert 'concentration' not in allowed_finding_types(difference)
    branches=schema['$defs']['SelectedInsight']['anyOf']
    assert not any('concentration' in b['properties']['finding_type']['enum'] and difference.evidence_id in b['properties']['primary_evidence_id']['enum'] for b in branches)
    concentration=next(e for e in ctx[0] if e.evidence_type=='proportion')
    assert any('concentration' in b['properties']['finding_type']['enum'] and concentration.evidence_id in b['properties']['primary_evidence_id']['enum'] for b in branches)


def test_saved_duplicate_rejection_is_fully_validated_redundancy_not_report_failure():
    report,execution,_=replay('T01')
    assert report.report_status=='complete' and report.goal_coverage=='complete'
    assert len(report.insights)==2
    metadata=next(iter(report.execution_metadata.values()))
    assert metadata['rejected_insights'][0]['disposition']=='redundant'
    assert metadata['report_batches'][0]['redundant_count']==1 and metadata['report_batches'][0]['invalid_count']==0
    assert execution.execution_status=='success'


@pytest.mark.parametrize('cid,missing',[('R05',{'T3','T4'}),('T05',{'T03','T04'})])
def test_saved_auxiliary_direction_omission_cannot_be_silently_complete(cid,missing):
    report,execution,_=replay(cid)
    assert report.report_status=='partial'
    assert missing <= {t.task_id for t in report.uncompleted_tasks}
    assert all(report.execution_metadata[tid]['interpretation_status']=='missing' for tid in missing)
    assert missing <= {c.task_id for c in report.charts}
    assert missing <= {t.task_id for t in execution.tasks if t.status=='success'}
    assert all('计算已完成' in t.reason for t in report.uncompleted_tasks if t.task_id in missing)


@pytest.mark.parametrize('cid',['P03','T05'])
def test_saved_invalid_type_remains_rejected_without_numeric_or_type_rewrite(cid):
    report,_,_=replay(cid)
    assert report.report_status=='partial'
    rejected=next(iter(report.execution_metadata.values()))['rejected_insights']
    assert any(r['error_code']=='REPORT_INVALID_EVIDENCE_TYPE' for r in invalid_candidates(rejected))
    assert all(not m['candidate_repairs'] for m in report.execution_metadata.values())


@pytest.mark.parametrize('fault',['recommendation','limitations','operand'])
def test_duplicate_with_invalid_content_is_not_relabelled_harmless(fault):
    ctx=context();good=choice(ctx[0]);bad=copy.deepcopy(good)
    if fault=='recommendation':bad['recommendation_id']='UNKNOWN'
    elif fault=='limitations':bad['limitation_refs']=['UNKNOWN']
    else:
        # The extra source-bound evidence is invalid, even if the primary repeats.
        atom=copy.deepcopy(next(e for e in ctx[0] if e.evidence_id==good['primary_evidence_id']))
        atom.evidence_id='BAD';atom.value['value']=999999
        ctx=([*ctx[0],atom],*ctx[1:]);bad['evidence_refs'].append('BAD')
    accepted,rejected=materialize_selection(InsightSelection.model_validate({'insights':[good,bad]}),*ctx)
    assert len(accepted)==1 and len(invalid_candidates(rejected))==1
    assert not rejected[0].get('validated')


def test_reused_primary_with_new_valid_comparison_is_preserved():
    ctx=context();good=choice(ctx[0]);primary=next(e for e in ctx[0] if e.evidence_id==good['primary_evidence_id'])
    comparison=next(e for e in ctx[0] if e.evidence_type=='difference' and e.task_id==primary.task_id and e.result_field==primary.result_field)
    additional={**good,'evidence_refs':[primary.evidence_id,comparison.evidence_id]}
    accepted,rejected=materialize_selection(InsightSelection.model_validate({'insights':[good,additional]}),*ctx)
    assert len(accepted)==2 and not rejected
    assert comparison.evidence_id in accepted[1].evidence_refs


def test_new_prompt_does_not_reinterpret_saved_v20_presentation():
    report,_,profile=replay('T01')
    for metadata in report.execution_metadata.values():metadata['insight_generation_version']='evidence-selection-v2.0'
    before=report.model_dump_json();view=build_presentation(report,profile)
    assert [f.title for f in view.findings]==[i.finding for i in report.insights]
    assert report.model_dump_json()==before


def test_schema_branches_bind_primary_refs_and_recommendations_to_same_metric_source():
    from test_report_capacity import inputs
    from test_insight_composition import artifacts
    from app.reporting.recommendations import build_catalog
    case=inputs(3);evidence,tasks,_=artifacts(case)
    options=build_catalog(evidence,tasks,case[3],case[0])
    schema=selection_schema(evidence,options,{'L1':'样本限制'},[])
    by_id={e.evidence_id:e for e in evidence}
    for branch in schema['$defs']['SelectedInsight']['anyOf']:
        props=branch['properties'];primary=by_id[props['primary_evidence_id']['enum'][0]]
        binding=lambda e:(e.task_id,e.data_ref,e.result_field,e.value.get('source_scope',e.scope))
        assert all(binding(by_id[identity])==binding(primary) for identity in props['evidence_refs']['items']['enum'])
        assert all(identity=='none' or (options[identity]['task_id'],options[identity]['data_ref'],options[identity]['result_field'])==binding(primary)[:3] for identity in props['recommendation_id']['enum'])


def test_only_exact_reference_duplicates_can_be_audited_as_format_normalization():
    ctx=context();good=choice(ctx[0]);data={**good,'evidence_refs':good['evidence_refs']*2}
    draft=InsightSelection.model_validate({'insights':[data]});before=draft.model_dump_json();repairs=[]
    accepted,rejected=materialize_selection(draft,*ctx,repairs=repairs)
    assert not rejected and accepted[0].evidence_refs==good['evidence_refs']
    assert repairs[0]['rule_id']=='EXACT_DUPLICATE_REFERENCE' and repairs[0]['validated']
    assert draft.model_dump_json()==before
    bad={**data,'recommendation_id':'UNKNOWN'};repairs=[]
    with pytest.raises(AppError):materialize_selection(InsightSelection.model_validate({'insights':[bad]}),*ctx,repairs=repairs)
    assert not repairs  # Format normalization never bypasses full factual/option validation.
