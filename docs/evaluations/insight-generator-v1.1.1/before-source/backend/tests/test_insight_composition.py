"""Safety and source-of-truth regression; fixtures do not measure model quality."""
import asyncio
import copy
import json
from pathlib import Path
from decimal import Decimal

import pytest
from app.domain.analysis_report import InsightDraft
from app.domain.errors import AppError
from app.planning.capabilities import CapabilityRegistry
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.reporting.fact_validation import materialize
from app.reporting.presentation import build_presentation
from app.reporting.prompt import request_schema
from app.reporting.selection import select_evidence
from app.reporting.export import render_report_v1
from app.services.analysis_report import AnalysisReportService
from planning_fixtures import step, task
from report_fixtures import report_case, ReportProvider


def case(values=(21250,20250,5760), *, function='sum', top=3):
    raw=('城市,销售额\n'+'\n'.join(f'{name},{value}' for name,value in zip(['济南','南京','上海'],values))+'\n').encode()
    operations=[step('group_aggregate',{'dimensions':['field_0001'],'metrics':[
        {'function':function,'field':'field_0002','alias':'sales'}]}),
        step('top_n',{'field':'sales','direction':'desc','n':top},'S02')]
    inputs=report_case([task(operations)],raw)
    inputs[2].tasks[0].result.columns[1].label='销售额 · 合计'
    return inputs


def artifacts(inputs=None):
    i,v,x,p=inputs or case();_,desc=prepare(i,v,x,p,CapabilityRegistry())
    evidence=EvidenceBuilder().build(x,p,desc)
    return evidence,{t.task_id:t for t in v.plan.tasks},{t.result.result_id:t.result for t in x.tasks if t.result}


def draft(primary, refs, kind='difference', text='该差异值得结合参与记录进一步评估。'):
    return InsightDraft.model_validate({'insights':[{'primary_evidence_id':primary,'evidence_refs':refs,
        'finding_type':kind,'implication':text,'recommendation':'比较对应分组的记录数量和金额分布，核查结构关联。','limitations':[]}]})


def test_sales_comparisons_exact_operands_scope_and_bounded_generation():
    e,_,_=artifacts();c={x.value['comparison_kind']:x for x in e if x.value.get('comparison_kind')}
    assert set(c)=={'relative_lead','relative_ratio','returned_concentration'}
    assert c['relative_lead'].value['difference']=='1000'
    assert c['relative_lead'].value['percent']=='4.9'
    assert c['relative_ratio'].value['percent']=='27.1'
    assert c['returned_concentration'].value['percent']=='87.8'
    assert c['returned_concentration'].value['numerator']=='41500'
    assert c['returned_concentration'].value['denominator']=='47260'
    assert c['returned_concentration'].value['denominator_scope']=='returned_groups_only'
    assert '不是全部筛选范围' in c['returned_concentration'].scope
    assert all(x.result_field=='sales' and x.data_ref=='R001' and x.source_row_indices for x in c.values())


def test_multi_evidence_is_expressed_in_saved_fact_and_finding():
    e,t,tables=artifacts();relative=next(x for x in e if x.value.get('comparison_kind')=='relative_lead')
    ranks=[x for x in e if x.evidence_type=='ranking']
    actual=materialize(draft(relative.evidence_id,[ranks[0].evidence_id,ranks[1].evidence_id,relative.evidence_id]),e,t,tables)[0]
    assert all(term in actual.finding for term in ['济南','南京','21,250','20,250','1,000','4.9%'])
    assert '待验证' in actual.implication and '尚未执行' in actual.recommendation
    assert actual.fact != actual.finding


@pytest.mark.parametrize('mutation',['denominator','percent','source_rows','object','result_field','scope'])
def test_comparison_and_reference_tampering_is_rejected(mutation):
    e,t,tables=artifacts();relative=next(x for x in e if x.value.get('comparison_kind')=='relative_lead')
    ranking=next(x for x in e if x.evidence_type=='ranking')
    if mutation=='denominator':relative.value['denominator']='1'
    if mutation=='percent':relative.value['percent']='99.9'
    if mutation=='source_rows':relative.source_row_indices=[2]
    if mutation=='object':relative.value['left']='不存在城市'
    if mutation=='result_field':relative.result_field='other'
    if mutation=='scope':relative.value['source_scope']='其他筛选范围'
    with pytest.raises(AppError):
        materialize(draft(relative.evidence_id,[ranking.evidence_id,relative.evidence_id]),e,t,tables)


@pytest.mark.parametrize('text',[
    '济南利润高于南京，可以增加投入。','济南销售额源自当地促销补贴。',
    'The profit share is ninety percent.','Sales are higher because marketing improved.',
    '已经证实订单结构解释了销售额差异。','上海仅占整个华东销售额的27.1%。',
    '可能是营销投入驱动了这次增长。','排名第一。','这就保证未来业绩增长。',
])
def test_unsupported_explanations_fail_closed(text):
    e,t,tables=artifacts();r=next(x for x in e if x.evidence_type=='ranking')
    with pytest.raises(AppError) as exc:materialize(draft(r.evidence_id,[r.evidence_id],'highlight',text),e,t,tables)
    assert exc.value.error.code=='REPORT_UNVERIFIED_FACT'


def test_safe_inference_boundary_and_numeric_fact_are_separated():
    e,t,tables=artifacts();r=next(x for x in e if x.evidence_type=='ranking')
    assert materialize(draft(r.evidence_id,[r.evidence_id],'highlight','销售额不能证明盈利能力。'),e,t,tables)
    # Even a known number in unconstrained prose does not certify object/metric binding.
    with pytest.raises(AppError):materialize(draft(r.evidence_id,[r.evidence_id],'highlight','南京销售额为21250。'),e,t,tables)


@pytest.mark.parametrize('values',[(10,0,-3),(0,0,0),(10,10,5)])
def test_invalid_baselines_ties_and_negatives_do_not_create_misleading_ratios(values):
    e,_,_=artifacts(case(values))
    assert not [x for x in e if x.value.get('comparison_kind')]


def test_average_is_not_summed_for_concentration_and_preview_is_not_full_denominator():
    e,_,_=artifacts(case(function='avg'))
    assert not [x for x in e if x.value.get('comparison_kind')=='returned_concentration']
    inputs=case();inputs[2].tasks[0].result.rows=inputs[2].tasks[0].result.rows[:2]
    inputs[2].tasks[0].result.truncated=True
    e,_,_=artifacts(inputs)
    assert not [x for x in e if x.value.get('comparison_kind')]


def test_request_can_select_multiple_insights_from_one_task_and_priority_selection():
    e,t,_=artifacts()
    assert request_schema(e)['properties']['insights']['maxItems']==8
    selected=select_evidence(e,t)
    assert selected[0].evidence_type=='comparison'
    assert {x.evidence_id for x in selected}<= {x.evidence_id for x in e}


def test_duplicate_ranking_and_extreme_are_not_two_distinct_findings():
    e,t,tables=artifacts();rank=next(x for x in e if x.evidence_type=='ranking')
    maximum=next(x for x in e if x.evidence_type=='maximum')
    data=draft(rank.evidence_id,[rank.evidence_id],'highlight').model_dump()
    data['insights']+=draft(maximum.evidence_id,[maximum.evidence_id],'highlight').model_dump()['insights']
    with pytest.raises(AppError):materialize(InsightDraft.model_validate(data),e,t,tables)


def test_every_available_p0_task_needs_a_finding():
    inputs=report_case([task(),task(tid='A02')]);e,t,tables=artifacts(inputs)
    first=next(x for x in e if x.evidence_type=='ranking')
    with pytest.raises(AppError) as exc:materialize(draft(first.evidence_id,[first.evidence_id],'highlight'),e,t,tables)
    assert exc.value.error.code=='REPORT_CORE_FINDINGS_MISSING'


def test_new_presentation_and_html_use_saved_insights_without_view_evidence():
    inputs=case();e,_,_=artifacts(inputs);rel=next(x for x in e if x.value.get('comparison_kind')=='relative_lead')
    output=draft(rel.evidence_id,[next(x for x in e if x.evidence_type=='ranking').evidence_id,rel.evidence_id]).model_dump()
    report=asyncio.run(AnalysisReportService(ReportProvider(output),CapabilityRegistry()).generate(*inputs))
    before=report.model_dump_json();view=build_presentation(report,inputs[3]);html=render_report_v1(report,view)
    assert view.presentation_version=='business-report-v1.1' and view.evidence==[]
    assert [i.title for i in view.findings]==[i.finding for i in report.insights]
    assert view.recommendations==[i.recommendation for i in report.insights]
    assert all(i.finding in html for i in report.insights)
    assert 'V001' not in html and report.model_dump_json()==before


def test_public_report_and_draft_schema_unchanged():
    from app.domain.analysis_report import AnalysisReport
    assert 'insight_generation_version' not in AnalysisReport.model_fields
    assert set(InsightDraft.model_fields)=={'insights'}
    assert set(InsightDraft.model_json_schema()['$defs']['DraftInsight']['properties'])=={
        'primary_evidence_id','evidence_refs','finding_type','implication','recommendation','limitations'}


def test_invalid_candidate_is_disclosed_without_losing_valid_facts_or_fake_success():
    inputs=case();e,_,_=artifacts(inputs);ranks=[x for x in e if x.evidence_type=='ranking']
    output=draft(ranks[0].evidence_id,[ranks[0].evidence_id],'highlight').model_dump()
    output['insights']+=draft(ranks[1].evidence_id,[ranks[1].evidence_id],'highlight','利润高于其他城市。').model_dump()['insights']
    report=asyncio.run(AnalysisReportService(ReportProvider(output),CapabilityRegistry()).generate(*inputs))
    assert report.report_status=='partial' and len(report.insights)==1
    assert any('候选洞察未通过校验' in text for text in report.limitations)
    assert report.execution_metadata['A01']['rejected_insights'][0]['error_code']=='REPORT_UNVERIFIED_FACT'
    assert '利润高于' not in report.model_dump_json()


def test_scoped_count_language_does_not_allow_swapped_metric_numbers():
    e,t,tables=artifacts();r=next(x for x in e if x.value.get('comparison_kind')=='relative_lead')
    assert materialize(draft(r.evidence_id,[r.evidence_id],text='这两个城市的差异需要进一步核查。'),e,t,tables)
    with pytest.raises(AppError):
        materialize(draft(r.evidence_id,[r.evidence_id],text='这两个城市各有两个订单。'),e,t,tables)
