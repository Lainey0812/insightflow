"""Transport fixtures exercise real storage/approval/kernels, not real model quality."""
import copy
import io
import json
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.errors import AppError
from app.domain.models import WorkflowError
from app.llm.base import LLMResponse
from app.main import create_app
from hitl_fixtures import approval, execution, revision
from intent_fixtures import intent_payload
from report_fixtures import ReportProvider
from workflow_v1_fixtures import ControlledWorkflowProvider, create_real

SALES = ('日期,地区,城市,状态,销售额\n'
    '2026-01-02,华东,济南,已完成,21250\n2026-02-01,华东,南京,已完成,20250\n'
    '2026-03-02,华东,上海,已完成,5760\n2026-03-03,华南,广州,已完成,90000\n'
    '2025-01-02,华东,济南,已完成,90000\n2026-02-02,华东,南京,未完成,90000\n').encode()
QUERY = '分析2026年华东地区已完成订单的销售额，按城市汇总并降序排名，取前三名'


def sales_intent():
    raw = intent_payload(business_goal='按城市汇总销售额并降序排名取前三名')
    raw['constraints'] = {'time_range': {'raw_text':'2026年','validation_status':'unverified'},
        'filters':[{'raw_text':v,'validation_status':'unverified'} for v in ['华东地区','已完成订单']],
        'metric_requirements':[{'raw_text':'销售额','validation_status':'unverified'}],
        'analysis_limits':[{'raw_text':'降序排名','validation_status':'unverified'}, {'raw_text':'前三名','validation_status':'unverified'}]}
    return raw


def sales_plan(context):
    return {'tasks':[{'task_id':'A01','title':'各城市已完成订单销售额前三名',
        'business_question':'本次筛选范围内哪些城市的销售额较高？','priority':'P0',
        'priority_reason':'删除后无法回答城市销售额排名问题',
        'requirement_ids':[r['requirement_id'] for r in context['core_requirements']],
        'depends_on':[], 'missing_inputs':[], 'steps':[
        {'step_id':'S01','operation':'filter','params':{'conditions':[
            {'field':'field_0001','operator':'gte','value':'2026-01-01'},
            {'field':'field_0001','operator':'lt','value':'2027-01-01'},
            {'field':'field_0002','operator':'eq','value':'华东'},
            {'field':'field_0004','operator':'eq','value':'已完成'}]}},
        {'step_id':'S02','operation':'group_aggregate','params':{'dimensions':['field_0003'], 'metrics':[
            {'function':'sum','field':'field_0005','alias':'sales_total'}]}},
        {'step_id':'S03','operation':'sort','params':{'field':'sales_total','direction':'desc'}},
        {'step_id':'S04','operation':'top_n','params':{'field':'sales_total','direction':'desc','n':3}}
    ]}]}


class Provider(ControlledWorkflowProvider):
    def __init__(self, *, report_error=None, report_mock=False, **kwargs):
        super().__init__(intents=[sales_intent()], planner=sales_plan, **kwargs)
        self.report_provider = ReportProvider(error=report_error)
        self.report_mock = report_mock

    async def generate(self, request):
        if request.purpose != 'report_insights_v1':
            return await super().generate(request)
        self.requests.append(request)
        response = await self.report_provider.generate(request)
        return response.model_copy(update={'is_mock':self.report_mock, 'provider':'controlled-transport-only'})


def run(client, xlsx=False):
    content, name = SALES, 'sales.csv'
    if xlsx:
        buf=io.BytesIO(); pd.read_csv(io.BytesIO(SALES)).to_excel(buf,index=False); content,name=buf.getvalue(),'sales.xlsx'
    state = create_real(client, content, name, QUERY)
    response = client.post(f'/api/v1/sessions/{state["id"]}/approvals', json=approval(state))
    assert response.status_code == 200, response.text
    approved = response.json()
    response = client.post('/api/v1/executions',json=execution(approved))
    assert response.status_code == 200, response.text
    return approved, response.json(), client.get('/api/v1/sessions/'+state['id']).json()


@pytest.mark.parametrize('xlsx',[False,True])
def test_real_file_report_pandas_approved_scope_persistence_idempotency_and_auth(tmp_path,xlsx):
    provider=Provider();app=create_app(Settings(tmp_path),provider)
    with TestClient(app) as client:
        approved,result,final=run(client,xlsx)
        assert result['execution_status']=='success' and final['status']=='COMPLETED'
        job=final['report_generations'][0]
        assert job['status']=='completed', job
        report=client.get('/api/v1/reports/'+job['report_id']).json()
        frame=pd.read_csv(io.BytesIO(SALES)); filtered=frame[(pd.to_datetime(frame['日期']).dt.year==2026)&(frame['地区']=='华东')&(frame['状态']=='已完成')]
        expected=filtered.groupby('城市')['销售额'].sum().sort_values(ascending=False).head(3)
        table=next(iter(report['result_data'].values()))
        assert {row['field_0003']:row['sales_total'] for row in table['rows']}==expected.to_dict()
        total=next(m for m in report['key_metrics'] if m['label'].startswith('本次返回'))
        assert total['value']==47260 and report['goal_coverage']=='complete'
        assert not any('需求约束尚需' in x for x in report['limitations'])
        assert report['execution_source']=='engine' and report['llm']['is_mock'] is False
        assert any('Top N' in x for x in report['limitations'])
        assert not [e for e in report['evidence'] if e['evidence_type']=='proportion']
        for i in report['insights']:
            assert set(i['evidence_refs']) <= {e['evidence_id'] for e in report['evidence']}
        assert report['charts'][0]['dimension']=='field_0003' and report['charts'][0]['metrics']==['sales_total']
        assert report['charts'][0]['chart_type']=='bar' and 'pie' not in report['charts'][0]['supported_chart_types']
        assert report['execution_metadata']['A01']['original_query']==QUERY
        assert any('2026' in s for s in report['execution_metadata']['A01']['approved_scope'])
        assert client.post('/api/v1/executions',json=execution(approved)).json()==result
        assert client.post(f'/api/v1/executions/{result["execution_id"]}/report',json={}).json()==job
        assert len(provider.report_provider.requests)==1
        assert client.get('/api/v1/reports/'+job['report_id']+'/execution').json()==app.state.executions.complete(result['execution_id']).model_dump(mode='json')
        assert 'attachment' in client.get(report['download_url']).headers['content-disposition']
        token=client.headers.pop('X-Session-Token')
        for path in [f'/api/v1/executions/{result["execution_id"]}/report', '/api/v1/reports/'+job['report_id'], report['download_url'], '/api/v1/reports/'+job['report_id']+'/execution']:
            assert client.get(path).status_code==403
        assert client.post(f'/api/v1/executions/{result["execution_id"]}/report', json={}).status_code==403
        assert client.get('/api/v1/reports/'+job['report_id'], headers={'X-Session-Keys':json.dumps({final['id']:token})}).json()==report
        assert client.get('/api/v1/reports/'+job['report_id'], headers={'X-Session-Keys':'[]'}).status_code==403
    with TestClient(create_app(Settings(tmp_path),Provider())) as restarted:
        restarted.headers['X-Session-Token']=token
        assert restarted.get('/api/v1/reports/'+job['report_id']).json()==report
        assert restarted.get('/api/v1/executions/'+result['execution_id']).json()==result
        assert restarted.get('/api/v1/sessions/'+final['id']).json()['report_generations'][0]==job


@pytest.mark.parametrize('failure',[AppError('LLM_TIMEOUT','报告调用超时',504),AppError('LLM_CALL_FAILED','模型不可用',502),'mock','json','fact','profit'])
def test_report_failure_never_changes_engine_result_and_explicit_retry(tmp_path,failure):
    p=Provider(report_error=failure if isinstance(failure,Exception) else None, report_mock=failure=='mock')
    if failure=='json':p.report_provider.output='not JSON'
    if failure in {'fact','profit'}:
        p.report_provider.output={'insights':[{'primary_evidence_id':'E0002','evidence_refs':['E0002'],'finding_type':'highlight',
            'implication':'销售额达到999999元。' if failure=='fact' else '该城市的经营效率更高。','recommendation':'继续核查业务背景。','limitations':[]}]}
    app=create_app(Settings(tmp_path),p)
    with TestClient(app) as client:
        approved,result,final=run(client)
        assert result['execution_status']=='success' and final['status']=='COMPLETED'
        job=final['report_generations'][0];assert job['status']=='failed' and job['report_id'] is None
        assert client.get('/api/v1/executions/'+result['execution_id']).json()==result
        assert client.post('/api/v1/executions',json=execution(approved)).json()==result
        assert len(p.report_provider.requests)==1
        p.report_provider.error=None;p.report_provider.output=None;p.report_mock=False
        response=client.post(f'/api/v1/executions/{result["execution_id"]}/report', json={'expected_attempt':1})
        assert response.status_code==202
        updated=client.get('/api/v1/executions/'+result['execution_id']+'/report').json()
        assert updated['status']=='completed' and updated['attempt']==2
        assert len(p.report_provider.requests)==2
        assert client.post(f'/api/v1/executions/{result["execution_id"]}/report', json={'execution':result}).status_code==422
        assert client.get('/api/v1/executions/'+result['execution_id']).json()==result


def test_generation_crash_recovery_and_attempt_compare_and_swap(tmp_path):
    app=create_app(Settings(tmp_path),Provider(report_error=AppError('TEST','失败',502)))
    with TestClient(app) as client:
        _,result,final=run(client);eid=result['execution_id']
        queued,fresh=app.state.report_workflow.enqueue(eid,1)
        assert fresh and queued.attempt==2
        same,again=app.state.report_workflow.enqueue(eid)
        assert not again and same==queued
        with pytest.raises(AppError):app.state.report_workflow.enqueue(eid,1)
        assert app.state.reports.start(eid,2).status=='generating'
        assert app.state.reports.start(eid,2) is None
        token=client.headers['X-Session-Token']
    restart=create_app(Settings(tmp_path),Provider())
    with TestClient(restart) as client:
        client.headers['X-Session-Token']=token
        job=client.get('/api/v1/executions/'+eid+'/report').json()
        assert job['status']=='failed' and job['error']['code']=='REPORT_PROCESS_INTERRUPTED'
        state=client.get('/api/v1/sessions/'+final['id']).json()
        assert state['status']=='COMPLETED' and state['report_generations']==[job]
        assert client.get('/api/v1/executions/'+eid).json()==result
        response=client.post('/api/v1/executions/'+eid+'/report',json={'expected_attempt':2})
        assert response.status_code==202
        assert client.get('/api/v1/executions/'+eid+'/report').json()['status']=='completed'


def test_immutable_execution_snapshot_used_if_latest_session_plan_changes(tmp_path):
    p=Provider(report_error=AppError('TEST','失败',502));app=create_app(Settings(tmp_path),p)
    with TestClient(app) as client:
        _,result,final=run(client)
        original=app.state.executions.approved_snapshot(result['execution_id'])
        # Simulate a newer session pointer, not a change to the immutable execution approval.
        app.state.repository.mutate(final['id'], lambda s: setattr(s,'engine_approval',None))
        p.report_provider.error=None
        assert client.post(f'/api/v1/executions/{result["execution_id"]}/report',json={'expected_attempt':1}).status_code==202
        job=client.get('/api/v1/executions/'+result['execution_id']+'/report').json()
        assert job['status']=='completed'
        report=client.get('/api/v1/reports/'+job['report_id']).json()
        assert report['plan_version']==original.validated_plan.plan.plan_version


def test_partial_engine_failure_retains_evidence_and_coverage(tmp_path,monkeypatch):
    from workflow_v1_fixtures import draft, intent
    p=Provider();p.intents=[intent()];p.planner=draft
    app=create_app(Settings(tmp_path),p)
    # Reuse Engine's established operation-error boundary, not fabricated successful rows.
    spec=app.state.capability_registry.operations['aggregate']
    def fail(*args,**kwargs):raise ValueError('failure isolated to auxiliary aggregate')
    monkeypatch.setitem(app.state.capability_registry.operations, 'aggregate', replace(spec, handler=fail))
    with TestClient(app) as client:
        from workflow_v1_fixtures import CSV
        state=create_real(client,CSV,goal='探索销售数据')
        r=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state));assert r.status_code==200,r.text
        result=client.post('/api/v1/executions',json=execution(r.json())).json()
        assert result['execution_status']=='partial_success'
        job=client.get('/api/v1/sessions/'+state['id']).json()['report_generations'][0]
        report=client.get('/api/v1/reports/'+job['report_id']).json()
        assert report['report_status']=='partial'
        assert report['uncompleted_tasks'][0]['task_id']=='A02'
        assert all(e['task_id']=='A01' for e in report['evidence'])
        assert all(c['task_id']=='A01' for c in report['charts'])


def test_request_schema_supports_full_nonblank_values_and_only_known_evidence():
    import re
    from app.reporting.prompt import request_schema
    from app.reporting.evidence import EvidenceBuilder
    from app.reporting.contracts import prepare
    from app.planning.capabilities import CapabilityRegistry
    from report_fixtures import report_case
    intent,plan,result,profile=report_case()
    _,desc=prepare(intent,plan,result,profile,CapabilityRegistry())
    evidence=EvidenceBuilder().build(result,profile,desc)
    schema=request_schema(evidence); props=schema['$defs']['DraftInsight']['properties']
    assert re.fullmatch(props['primary_evidence_id']['pattern'], 'E0002')
    assert not re.fullmatch(props['implication']['pattern'], '   ')
    assert re.fullmatch(props['implication']['pattern'], '可作为进一步核查线索。')
    assert props['primary_evidence_id']['enum']==[e.evidence_id for e in evidence]
    assert schema['properties']['insights']['maxItems']==8  # Public draft limit; no per-task-one restriction.


def test_report_service_rejects_mismatching_approval_and_partial_core_cannot_claim_complete(tmp_path,monkeypatch):
    import asyncio
    from app.domain.execution import ApprovedExecutionSnapshot
    from app.domain.intent import ParsedIntent
    from app.services.analysis_report import AnalysisReportService
    from app.planning.capabilities import CapabilityRegistry
    from report_fixtures import report_case
    intent,plan,result,profile=report_case()
    wrong=ApprovedExecutionSnapshot(approval_id='wrong', approved_at='today',validated_plan=plan,intent=intent)
    with pytest.raises(AppError) as exc:
        asyncio.run(AnalysisReportService(ReportProvider(),CapabilityRegistry()).generate(intent,plan,result,profile,approved_snapshot=wrong))
    assert exc.value.error.code=='REPORT_APPROVAL_MISMATCH'


def test_no_evidence_saves_unavailable_without_llm_and_keeps_failed_execution(tmp_path,monkeypatch):
    p=Provider();app=create_app(Settings(tmp_path),p)
    spec=app.state.capability_registry.operations['group_aggregate']
    def fail(*args,**kwargs):raise ValueError('test kernel failure')
    monkeypatch.setitem(app.state.capability_registry.operations,'group_aggregate',replace(spec,handler=fail))
    with TestClient(app) as client:
        _,result,final=run(client)
        assert result['execution_status']=='failed' and final['status']=='FAILED'
        job=final['report_generations'][0];assert job['status']=='unavailable'
        report=client.get('/api/v1/reports/'+job['report_id']).json()
        assert report['goal_coverage']=='blocked' and not report['charts'] and not report['insights']
        assert not p.report_provider.requests
        assert client.get('/api/v1/executions/'+result['execution_id']).json()==result


def test_core_failure_with_auxiliary_success_has_blocked_goal_and_no_core_facts(tmp_path,monkeypatch):
    from workflow_v1_fixtures import draft,intent
    p=Provider();p.intents=[intent()];p.planner=draft;app=create_app(Settings(tmp_path),p)
    spec=app.state.capability_registry.operations['group_aggregate']
    def fail(*args,**kwargs):raise ValueError('core group calculation failed')
    monkeypatch.setitem(app.state.capability_registry.operations,'group_aggregate',replace(spec,handler=fail))
    with TestClient(app) as client:
        from workflow_v1_fixtures import CSV
        state=create_real(client,CSV,goal='探索销售数据')
        approved=client.post(f'/api/v1/sessions/{state["id"]}/approvals',json=approval(state)).json()
        result=client.post('/api/v1/executions',json=execution(approved)).json()
        assert result['execution_status']=='partial_success'
        job=client.get('/api/v1/sessions/'+state['id']).json()['report_generations'][0]
        report=client.get('/api/v1/reports/'+job['report_id']).json()
        assert report['report_status']=='partial' and report['goal_coverage']=='blocked'
        assert '尚不能回答' in report['summary']['headline']
        assert all(e['task_id']=='A02' for e in report['evidence'])
        assert all(c['task_id']=='A02' for c in report['charts'])
        assert report['uncompleted_tasks'][0]['task_id']=='A01'


def test_averages_and_truncated_previews_are_not_summed_as_additive_metrics():
    from planning_fixtures import step,task
    from report_fixtures import report_case
    from app.reporting.contracts import prepare
    from app.reporting.evidence import EvidenceBuilder
    from app.planning.capabilities import CapabilityRegistry
    operations=[step('group_aggregate',{'dimensions':['field_0001'], 'metrics':[{'function':'avg','field':'field_0002','alias':'salary_avg'}]})]
    # Use an explicit numeric source file, independent of recruiting interval strings.
    raw='城市,金额\n甲,10\n甲,20\n乙,30\n'.encode()
    intent,plan,result,profile=report_case([task(operations)],raw=raw)
    _,desc=prepare(intent,plan,result,profile,CapabilityRegistry())
    assert not [e for e in EvidenceBuilder().build(result,profile,desc) if e.evidence_type=='metric']
    operations[0]['params']['metrics'][0]['function']='sum'
    intent,plan,result,profile=report_case([task(operations)],raw=raw)
    result.tasks[0].result.rows=result.tasks[0].result.rows[:1]
    result.tasks[0].result.truncated=True
    _,desc=prepare(intent,plan,result,profile,CapabilityRegistry())
    assert not [e for e in EvidenceBuilder().build(result,profile,desc) if e.evidence_type in {'metric','proportion'}]


@pytest.mark.parametrize('text,accepted',[
    ('该分组在已返回的排名结果中表现突出，可作为继续核查的线索。',True),
    ('销售额排名不直接证明盈利能力或投入效果，需补充成本资料。',True),
    ('排名不能证明经营效率，需补充投入数据。',True),
    ('销售额排名证明盈利能力更高。',False),
    ('该分组盈利能力更高。',False),
    ('该分组在整体市场排名第一。',False),
    ('不会导致利润下降。',False),
    ('两个分组贡献了90%的利润。',False),
])
def test_fact_guard_distinguishes_known_rank_reference_and_inference_limits(text,accepted):
    from app.reporting.fact_validation import materialize
    from app.domain.analysis_report import InsightDraft
    from app.reporting.contracts import prepare
    from app.reporting.evidence import EvidenceBuilder
    from app.planning.capabilities import CapabilityRegistry
    from report_fixtures import report_case
    intent,plan,result,profile=report_case();_,desc=prepare(intent,plan,result,profile,CapabilityRegistry())
    evidence=EvidenceBuilder().build(result,profile,desc)
    draft=InsightDraft.model_validate({'insights':[{'primary_evidence_id':'E0002','evidence_refs':['E0002'],'finding_type':'highlight',
        'implication':text,'recommendation':'继续核查业务背景。','limitations':[]}]})
    if accepted:
        actual=materialize(draft,evidence,{t.task_id:t for t in plan.plan.tasks})
        assert text in actual[0].implication  # Validation does not rewrite model text.
    else:
        with pytest.raises(AppError):materialize(draft,evidence,{t.task_id:t for t in plan.plan.tasks})
