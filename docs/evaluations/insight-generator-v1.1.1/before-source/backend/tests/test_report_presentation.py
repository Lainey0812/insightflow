"""Business view tests: saved real-report snapshot + controlled deterministic kernel cases."""
import asyncio
import copy
from decimal import Decimal
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.domain.analysis_report import AnalysisReport
from app.domain.dataset_profile import DatasetProfile
from app.main import create_app
from app.reporting.export import render_report_v1
from app.reporting.presentation import build_presentation
from app.services.analysis_report import AnalysisReportService
from app.planning.capabilities import CapabilityRegistry
from planning_fixtures import step,task
from report_fixtures import report_case,ReportProvider
from test_report_workflow import Provider,run

ROOT=Path(__file__).resolve().parents[2]
EVAL=ROOT/'docs/evaluations/report-workflow-v1'


def saved_case():
    report=AnalysisReport.model_validate_json((EVAL/'fresh-workflow-analysis-report.json').read_text())
    profile=DatasetProfile.model_validate(json.loads((EVAL/'fresh-workflow-session.json').read_text())['profile'])
    return report,profile


def rank_case(values,n=3,direction='desc'):
    raw=('城市,销售额\n'+'\n'.join(f'{label},{value}' for label,value in values)+'\n').encode()
    ops=[step('group_aggregate',{'dimensions':['field_0001'],'metrics':[{'function':'sum','field':'field_0002','alias':'sales'}]}),
        step('top_n',{'field':'sales','direction':direction,'n':n},'S02')]
    i,v,x,p=report_case([task(ops)],raw)
    x.tasks[0].result_id=x.tasks[0].result.result_id
    report=asyncio.run(AnalysisReportService(ReportProvider(),CapabilityRegistry()).generate(i,v,x,p))
    return report,p


def test_real_saved_sales_layout_values_scopes_trace_and_no_mutation():
    report,profile=saved_case();before=report.model_dump_json()
    view=build_presentation(report,profile)
    assert view.kind=='ranking'
    assert view.title=='2026 年华东地区城市销售额 Top 3 分析'
    assert view.subtitle=='已完成订单 · 按城市汇总 · 销售额降序排名'
    assert [m.display_value for m in view.key_metrics]==['21,250','4.9%','87.8%']
    assert view.key_metrics[-1].caption=='占前三名合计'
    assert '1,000' in view.findings[0].body and '4.9%' in view.findings[0].body
    assert '5,760' in view.findings[1].body and '27.1%' in view.findings[1].body
    assert '并不是' in view.findings[2].body and '87.8%' in view.findings[2].body
    assert '60 条' in view.data_notes[0] and '16 条' in view.data_notes[0]
    assert '2026 年华东地区已完成订单' in view.data_notes[1]
    assert all(word in view.recommendations[0] for word in ['订单数量','平均订单金额','产品类别结构','尚未执行','不足以确定'])
    refs={e.evidence_id:e for e in view.evidence}
    for item in [*view.key_metrics,*view.findings]:
        assert set(item.evidence_refs)<=refs.keys()
        for ref in item.evidence_refs:
            e=refs[ref];table=report.result_data[e.data_ref]
            assert e.result_field in {c.field for c in table.columns}
            assert all(0<=row<len(table.rows) for row in e.source_row_indices)
    assert refs['V003'].value['denominator']=='20250'
    assert refs['V004'].value['denominator']=='21250'
    assert refs['V005'].value['denominator']=='47260'
    assert refs['V005'].scope.endswith('分母仅为前三名合计')
    assert report.model_dump_json()==before


def test_generic_data_is_not_turned_into_sales_or_customer_story():
    report,profile=rank_case([('甲',100),('乙',60),('丙',20)])
    view=build_presentation(report,profile)
    assert view.kind=='general' and view.presentation_version=='business-report-v1.1'
    assert [i.title for i in view.findings]==[i.finding for i in report.insights]
    assert '订单数量' not in view.recommendations[0] and '产品类别' not in view.recommendations[0]


@pytest.mark.parametrize('kind',['truncated','tie','ascending','missing_dimension','no_profile'])
def test_no_false_precise_ranking_for_ineligible_results(kind):
    if kind=='tie':report,profile=rank_case([('甲',10),('乙',10),('丙',2)])
    elif kind=='ascending':report,profile=rank_case([('甲',10),('乙',5),('丙',2)],direction='asc')
    elif kind=='missing_dimension':report,profile=rank_case([('甲',10),('',5),('丙',2)])
    else:report,profile=saved_case()
    if kind=='truncated':
        raw=report.model_dump();table=next(iter(raw['result_data'].values()));table['truncated']=True;table['total_result_rows']=4;report=AnalysisReport.model_validate(raw)
    if kind=='no_profile':profile=None
    view=build_presentation(report,profile)
    assert view.kind=='general' and view.evidence==[]


def test_nonpositive_denominators_and_negative_results_do_not_create_percentages():
    report,profile=rank_case([('甲',10),('乙',0),('丙',-3)])
    view=build_presentation(report,profile)
    assert view.kind=='general' and view.presentation_version=='business-report-v1.1'
    assert not [e for e in view.evidence if e.value.get('unit')=='%']
    assert not any('%' in m.display_value for m in view.key_metrics)
    assert not [e for e in report.evidence if e.value.get('comparison_kind')]


def test_fewer_than_top_n_does_not_claim_complete_top_three():
    report,profile=rank_case([('甲',10),('乙',5)],n=3)
    view=build_presentation(report,profile)
    assert '实际返回 2 个城市' in view.executive_summary
    assert '位列销售额前三名' not in view.executive_summary
    assert [m.evidence_refs for m in view.key_metrics]==[[m.evidence_ref] for m in report.key_metrics]
    assert view.evidence==[]


def test_partial_and_blocked_status_is_never_described_as_full_completion():
    report,profile=saved_case();report.report_status='partial';report.goal_coverage='blocked'
    view=build_presentation(report,profile)
    assert view.executive_summary.startswith('本报告只展示已有结果')
    assert report.limitations[-1] in view.data_notes


def test_large_integer_card_formats_original_value_without_float_rounding():
    report,profile=rank_case([('甲',9007199254740993),('乙',1),('丙',0)])
    view=build_presentation(report,profile)
    assert view.key_metrics[0].display_value=='9,007,199,254,740,993'


def test_html_export_uses_same_business_view_and_escapes_untrusted_text():
    report,profile=saved_case();view=build_presentation(report,profile)
    html=render_report_v1(report,view)
    for text in ['业务分析报告',view.title,'执行摘要','核心发现与业务解读','建议进一步分析','数据说明','4.9%','87.8%','27.1%','分母仅为前三名合计']:
        assert text in html
    changed=view.model_copy(update={'title':'<script>alert(1)</script>'})
    html=render_report_v1(report,changed)
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_presentation_and_download_are_authenticated_reads_without_rerunning_llm(tmp_path):
    provider=Provider();app=create_app(Settings(tmp_path),provider)
    with TestClient(app) as client:
        _,result,state=run(client);job=state['report_generations'][0];rid=job['report_id']
        original=client.get('/api/v1/reports/'+rid).json();calls=len(provider.requests)
        view=client.get('/api/v1/reports/'+rid+'/presentation')
        assert view.status_code==200,view.text
        assert [m['display_value'] for m in view.json()['key_metrics']]==['21,250','4.9%','87.8%']
        html=client.get('/api/v1/reports/'+rid+'/download')
        assert html.status_code==200 and '核心发现与业务解读' in html.text
        assert len(provider.requests)==calls and client.get('/api/v1/reports/'+rid).json()==original
        token=client.headers.pop('X-Session-Token')
        assert client.get('/api/v1/reports/'+rid+'/presentation').status_code==403
        assert client.get('/api/v1/reports/'+rid+'/presentation',headers={'X-Session-Keys':json.dumps({state['id']:token})}).status_code==200


def test_small_nonzero_values_are_not_formatted_as_zero():
    from app.reporting.presentation import display
    assert display(Decimal('0.000001'))=='0.000001'
    assert display(Decimal('21250.00'))=='21,250'


def test_count_of_numeric_field_is_labeled_as_count_not_money():
    candidate=task([step('group_aggregate',{'dimensions':['field_0001'],'metrics':[{'function':'count','field':'field_0002','alias':'count'}]}),
        step('top_n',{'field':'count','direction':'desc','n':3},'S02')])
    i,v,x,p=report_case([candidate],raw='城市,销售额\n甲,10\n甲,20\n甲,30\n乙,10\n乙,20\n丙,10\n'.encode())
    x.tasks[0].result_id=x.tasks[0].result.result_id
    report=asyncio.run(AnalysisReportService(ReportProvider(),CapabilityRegistry()).generate(i,v,x,p))
    view=build_presentation(report,p)
    assert view.key_metrics[0].label=='第一名销售额非空记录数'
    assert '平均订单金额' not in view.recommendations[0]
