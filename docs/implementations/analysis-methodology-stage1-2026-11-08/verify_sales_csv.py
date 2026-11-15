"""Real local CSV / approved fixture / real Engine; no external model request."""
import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests')]
import pandas as pd
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.services.analysis_report import AnalysisReportService
from app.reporting.presentation import build_presentation
from app.reporting.export import render_report_v1
from engine_fixtures import upload, approve, execute
from planning_fixtures import task, step
from intent_fixtures import StubProvider
from report_fixtures import ReportProvider

out = Path(__file__).parent/'real-sales-verification'
out.mkdir(exist_ok=False)
source = Path('/Users/lainey/Downloads/insightflow_sales_orders_test.csv').read_bytes()
data_dir = ROOT.parent/'var/verification'/('sample-statistics-'+uuid4().hex)
app = create_app(Settings(data_dir), StubProvider())
with TestClient(app) as client:
    profile = upload(client, source, 'insightflow_sales_orders_test.csv')
    fields = {f.display_name:f.field_id for f in profile.fields}
    steps = [step('filter', {'conditions':[
        {'field':fields['订单日期'],'operator':'gte','value':'2026-01-01'},
        {'field':fields['订单日期'],'operator':'lt','value':'2027-01-01'},
        {'field':fields['地区'],'operator':'eq','value':'华东'},
        {'field':fields['订单状态'],'operator':'eq','value':'已完成'}]}),
        step('group_aggregate', {'dimensions':[fields['城市']], 'metrics':[
            {'function':'count','field':None,'alias':'records'},
            {'function':'distinct_count','field':fields['订单编号'],'alias':'unique_orders'},
            {'function':'sum','field':fields['销售额'],'alias':'sales_total'}]}, 'S02'),
        step('top_n', {'field':'sales_total','direction':'desc','n':3}, 'S03')]
    state, request = approve(app, profile, [task(steps)])
    response = execute(client, request)
    assert response.status_code == 200, response.text
    execution = app.state.executions.complete(response.json()['execution_id'])
    assert execution.execution_status == 'success'
    frame = pd.read_csv(io.BytesIO(source))
    dates = pd.to_datetime(frame['订单日期'])
    filtered = frame.loc[(dates >= '2026-01-01') & (dates < '2027-01-01') & (frame['地区']=='华东') & (frame['订单状态']=='已完成')]
    mask = filtered[['城市','订单编号','销售额']].isna().any(axis=1)
    samples = execution.tasks[0].execution_metadata.sample_statistics
    assert (samples.input_row_count, samples.complete_row_count, samples.missing_row_count) == (len(filtered),int((~mask).sum()),int(mask.sum()))
    expected = filtered.groupby('城市')['销售额'].sum().sort_values(ascending=False).head(3).to_dict()
    actual = {row[fields['城市']]:row['sales_total'] for row in execution.tasks[0].result.rows}
    assert actual == expected == {'济南':21250,'南京':20250,'上海':5760}
    approval = state.engine_approval
    # Scripted fixture tests report assembly only, never represented as a real LLM.
    report = asyncio.run(AnalysisReportService(ReportProvider(), app.state.capability_registry).generate(
        approval.intent, approval.validated_plan, execution, profile))
    app.state.reports.save(report, {'session_id':state.id})
    saved = app.state.reports.get(report.report_id)
    view = build_presentation(saved, profile)
    html = render_report_v1(saved, view)
    assert f'完整记录 {samples.complete_row_count} 条' in html
    (out/'execution.json').write_text(execution.model_dump_json(indent=2))
    (out/'report.json').write_text(saved.model_dump_json(indent=2))
    (out/'report.html').write_text(html)
    summary = {'verification_kind':'actual_csv_real_engine_scripted_report_fixture', 'real_llm':False,
        'csv_sha256':hashlib.sha256(source).hexdigest(), 'execution_id':execution.execution_id,
        'approval_id':execution.approval_id, 'dataset_id':profile.dataset_id, 'dataset_version':profile.dataset_version,
        'report_id':saved.report_id, 'upload_rows':len(frame), 'included_rows':samples.input_row_count,
        'complete_rows':samples.complete_row_count,'missing_rows':samples.missing_row_count,
        'top_three':actual, 'pandas_matches':True, 'report_metadata_matches_execution':saved.execution_metadata[execution.tasks[0].task_id]['execution_metadata']['sample_statistics']==samples.model_dump(mode='json'),
        'scope':'2026年华东地区已完成；聚合前输入，非Top3返回分组行数',
        'approval_fixture_notice':'Temporary verification database; server-owned approval fixture, no production approval bypass.'}
    (out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))
