"""V1.1.1 safety invariants; deterministic fixtures are not real-model quality scores."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.analysis_report import AnalysisReport, Evidence, InsightDraft
from app.domain.errors import AppError
from app.domain.execution import ExecutionResultV1
from app.planning.capabilities import CapabilityRegistry
from app.reporting import claims
from app.reporting.fact_validation import materialize, materialize_candidates
from app.reporting.presentation import build_presentation
from app.reporting.export import render_report_v1
from app.services.analysis_report import AnalysisReportService
from report_fixtures import ReportProvider
from test_insight_composition import artifacts, case, draft

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT/'docs/evaluations/insight-generator-v1.1'


def saved(cid):
    entry = next(r for r in json.loads((HISTORY/'final-live.json').read_text())['records'] if r['case_id']==cid)
    fixture = next(c for c in json.loads((HISTORY/'frozen-inputs-v2.json').read_text()) if c['case_id']==cid)['input']
    payload = entry['calls'][0]['input']
    plan = ValidatedAnalysisPlan.model_validate(fixture['validated'])
    execution = ExecutionResultV1.model_validate(fixture['execution'])
    return (InsightDraft.model_validate_json(entry['calls'][0]['raw_output']),
        [Evidence.model_validate(e) for e in payload['evidence']],
        {t.task_id:t for t in plan.plan.tasks},
        {t.result.result_id:t.result for t in execution.tasks if t.status=='success'},payload['limitations'])


@pytest.mark.parametrize('cid,accepted,rejected',[
    ('O01',1,1),('O02',2,0),('R03',1,0),('O03',1,1),('H01',1,1),('H02',2,0),('H03',2,0)])
def test_seven_saved_failures_keep_safe_candidates_and_reject_unsafe_ones(cid,accepted,rejected):
    good,bad=materialize_candidates(*saved(cid))
    assert len(good)==accepted and len(bad)==rejected
    if cid=='O01':assert bad[0]['details']['rule']=='ENDPOINT_NOT_INTERVAL_STABILITY'
    if cid=='O03':assert bad[0]['details']['rule']=='SAME_METRIC_COMPOSITION'
    if cid=='H01':assert 'UNDEFINED_THRESHOLD' in bad[0]['details']['triggered_rules']


@pytest.mark.parametrize('text',[
    '销售额不能证明盈利能力。',
    '当前数据不足以判断造成差异的具体业务原因。',
    '不保证时间点连续，仅比较已返回的首末值。',
    '分母仅为本次完整返回的分组合计，不代表全部筛选范围或整体市场占比。',
    '集中度计算基于返回分组，非总体占比。',
    '不能直接视为总体占比。',
])
def test_negated_boundaries_are_not_affirmative_assertions(text):
    e,t,tables=artifacts();r=next(x for x in e if x.value.get('comparison_kind')=='returned_concentration')
    d=draft(r.evidence_id,[r.evidence_id],'concentration',text)
    audit=[];assert materialize(d,e,t,tables,diagnostics=audit)


@pytest.mark.parametrize('text',[
    '销售额不能证明盈利能力，但济南利润高于南京。',
    '当前数据不足以判断原因，但是已经证实营销导致增长。',
    '这两个城市各有两个订单。',
    '南京销售额为21250。',
    '上海占整个华东销售额的27.1%。',
    '本次返回城市占全部华东城市销售额的大多数。',
    '不能推断因果关系，但资源投入驱动了增长。',
    'Top 30筛选中的城市都更好。',
    '前两名利润更高。',
])
def test_contextual_aliases_do_not_exempt_unverified_claims(text):
    e,t,tables=artifacts();r=next(x for x in e if x.value.get('comparison_kind')=='returned_concentration')
    with pytest.raises(AppError):materialize(draft(r.evidence_id,[r.evidence_id],'concentration',text),e,t,tables)


@pytest.mark.parametrize('change',['scope','metric','task','result','period'])
def test_incompatible_bindings_and_time_scopes_remain_rejected(change):
    e,t,tables=artifacts();r=next(x for x in e if x.value.get('comparison_kind')=='relative_lead');other=copy.deepcopy(r)
    other.evidence_id='EX'
    if change in {'scope','period'}:other.value['source_scope']='2025年度' if change=='period' else '另一筛选范围'
    if change=='metric':other.result_field='profits'
    if change=='task':other.task_id='A02'
    if change=='result':other.data_ref='R002'
    e.append(other)
    with pytest.raises(AppError) as exc:materialize(draft(r.evidence_id,[r.evidence_id,'EX']),e,t,tables)
    assert exc.value.error.code=='REPORT_INVALID_EVIDENCE_REFERENCE'


@pytest.mark.parametrize('change',['rank','category','value','difference','denominator'])
def test_base_fact_bindings_are_rechecked_not_just_ratio_arithmetic(change):
    e,t,tables=artifacts()
    if change in {'rank','category','value'}:
        r=next(x for x in e if x.evidence_type=='ranking');r.value[change]={'rank':9,'category':'另一城市','value':999}[change];kind='highlight'
    elif change=='difference':
        r=next(x for x in e if x.evidence_type=='difference');r.value['difference']=999;kind='difference'
    else:
        _,e,t,tables,_=saved('O02');r=next(x for x in e if x.evidence_type=='proportion');r.value['denominator']=999;kind='concentration'
    with pytest.raises(AppError):materialize(draft(r.evidence_id,[r.evidence_id],kind),e,t,tables)


def test_cross_metric_facts_can_coexist_but_core_metric_omission_is_visible():
    d,e,t,tables,limits=saved('O03')
    good,bad=materialize_candidates(d,e,t,tables,limits)
    assert claims.missing_metrics(e,t,good)==[('A01','tasks')]
    count=next(x for x in e if x.result_field=='tasks' and x.evidence_type=='ranking')
    more=materialize(draft(count.evidence_id,[count.evidence_id],'highlight'),e,t,tables)
    assert claims.missing_metrics(e,t,[*good,*more])==[]
    # Side-by-side facts are supported; we have not declared all cross-metric BI invalid.
    assert {i.task_id for i in [*good,*more]}=={'A01'}


def test_no_valid_candidate_reports_all_reasons_without_empty_success():
    e,t,tables=artifacts();r=next(x for x in e if x.evidence_type=='ranking')
    d=draft(r.evidence_id,[r.evidence_id],'highlight','利润高于其他城市。')
    d.insights.append(copy.deepcopy(d.insights[0]))
    with pytest.raises(AppError) as exc:materialize_candidates(d,e,t,tables)
    assert len(exc.value.error.details['rejected_candidates'])==2


def test_saved_report_fact_finding_and_summary_are_not_three_copies():
    inputs=case();e,t,tables=artifacts(inputs);r=next(x for x in e if x.value.get('comparison_kind')=='relative_lead')
    absolute=next(x for x in e if x.evidence_type=='difference')
    d=draft(r.evidence_id,[absolute.evidence_id,r.evidence_id])
    selection={'insights':[{'primary_evidence_id':r.evidence_id,'evidence_refs':[absolute.evidence_id,r.evidence_id],'finding_type':'difference','recommendation_id':'none','limitation_refs':[]}]}
    report=asyncio.run(AnalysisReportService(ReportProvider(selection),CapabilityRegistry()).generate(*inputs))
    insight=report.insights[0]
    assert insight.finding.count('1,000')==1
    assert insight.finding not in report.summary.overview
    assert insight.fact!=insight.finding and '差值=' in insight.fact
    view=build_presentation(report,inputs[3]);html=render_report_v1(report,view)
    from app.domain.report_presentation import ReportPresentation
    assert ReportPresentation.model_validate(view.model_dump())==view
    assert view.findings[0].title==insight.finding and view.findings[0].body==insight.implication
    assert html.count(insight.finding)==1 and html.count(insight.recommendation)==0


def test_old_saved_v11_report_keeps_unified_saved_source_not_legacy_v_evidence():
    raw=json.loads((HISTORY/'sales-report.json').read_text());report=AnalysisReport.model_validate(raw)
    before=report.model_dump_json();view=build_presentation(report)
    assert view.presentation_version=='business-report-v1.1' and view.evidence==[]
    assert [i.title for i in view.findings]==[i.finding for i in report.insights]
    assert report.model_dump_json()==before


def test_tie_boundary_does_not_add_an_ordinal_and_tiny_values_are_not_rounded_to_zero():
    d,e,t,tables,limits=saved('R03')
    d.insights[0].implication='当前返回分组数量相同，符合不编造唯一名次的要求。'
    assert materialize_candidates(d,e,t,tables,limits)[0]
    from app.reporting.evidence import fmt
    assert fmt(0.00000019)=='0.00000019'
    assert not claims.same(0,0.00000019)
    assert not claims.same(100000000000001,100000000000000)


@pytest.mark.parametrize('kind',['ranking','difference','change_rate'])
def test_interval_stability_is_not_accepted_by_switching_the_primary_evidence(kind):
    _,e,t,tables,limits=saved('O01');r=next(x for x in e if x.evidence_type==kind)
    d=draft(r.evidence_id,[r.evidence_id],{'ranking':'highlight','difference':'difference','change_rate':'trend'}[kind],
            '整个期间稳定，无需验证。')
    with pytest.raises(AppError) as exc:materialize(d,e,t,tables,trusted_limitations=limits)
    assert exc.value.error.details['rule']=='ENDPOINT_NOT_INTERVAL_STABILITY'
