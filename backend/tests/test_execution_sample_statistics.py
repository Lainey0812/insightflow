"""Joint completeness is an execution fact, not a sum of profiler column counts."""
import io

import pandas as pd
import pytest
from pydantic import ValidationError

from app.domain.execution import SampleStatistics, TaskExecutionMetadata
from app.reporting.export import saved_samples, render_report_v1
from app.domain.analysis_report import AnalysisReport
from engine_fixtures import upload, approve, execute
from planning_fixtures import task, step

CSV = b'city,order_id,sales,region\nA,o1,10,E\nA,o1,,E\n,o2,20,E\n,,30,E\nA,o3,40,W\nA,,50,E\nB,o4,60,E\n'


def run(client, app, steps, content=CSV):
    profile = upload(client, content)
    state, request = approve(app, profile, [task(steps)])
    response = execute(client, request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['tasks'][0]['status'] == 'success', result
    return result, request, state, profile


def aggregate_metrics():
    return [
        {'function':'count', 'field':None, 'alias':'records'},
        {'function':'count', 'field':'field_0002', 'alias':'non_null_ids'},
        {'function':'distinct_count', 'field':'field_0002', 'alias':'unique_ids'},
        {'function':'sum', 'field':'field_0003', 'alias':'total'},
    ]


def test_filtered_joint_rows_are_deduplicated_not_column_missing_sums(client, app, provider):
    steps = [step('filter', {'conditions':[{'field':'field_0004','operator':'eq','value':'E'}]}),
        step('group_aggregate', {'dimensions':['field_0001'],'metrics':aggregate_metrics()}, 'S02'),
        step('top_n', {'field':'total','direction':'desc','n':1}, 'S03')]
    data, request, state, profile = run(client, app, steps)
    output = data['tasks'][0]
    sample = output['execution_metadata']['sample_statistics']
    frame = pd.read_csv(io.BytesIO(CSV))
    selected = frame.loc[frame.region == 'E']
    mask = selected[['city','order_id','sales']].isna().any(axis=1)
    assert sample['input_row_count'] == len(selected) == 6
    assert sample['missing_row_count'] == int(mask.sum()) == 4
    assert sample['complete_row_count'] == int((~mask).sum()) == 2
    assert sum(f['missing_count'] for f in sample['key_fields']) == 5
    assert output['row_count'] == 1  # Top N groups are not source row counts.
    assert output['effective_row_count'] == 6
    metrics = sample['metrics']
    assert metrics['records']['basis'] == 'rows'
    assert metrics['records']['participating_count'] == 6
    assert metrics['non_null_ids']['basis'] == 'non_null_values'
    assert metrics['unique_ids']['basis'] == 'distinct_non_null_values'
    assert metrics['unique_ids']['participating_count'] == 4
    assert metrics['total']['participating_count'] == 5
    # The new metadata is part of the normal persisted result and idempotent replay.
    assert app.state.executions.get(data['execution_id']).model_dump(mode='json') == data
    assert execute(client, request).json() == data
    assert provider.requests == []


def test_record_non_null_and_distinct_counts_keep_different_meanings(client, app):
    steps = [step('filter', {'conditions':[{'field':'field_0004','operator':'eq','value':'E'}]}),
             step('aggregate', {'metrics':aggregate_metrics()}, 'S02')]
    data, *_ = run(client, app, steps)
    row = data['tasks'][0]['result']['rows'][0]
    assert row == {'records':6,'non_null_ids':4,'unique_ids':3,'total':170}


def test_no_field_count_has_no_fabricated_completeness(client, app):
    data, *_ = run(client, app, [step('aggregate', {'metrics':[{'function':'count','field':None,'alias':'records'}]})])
    sample = data['tasks'][0]['execution_metadata']['sample_statistics']
    assert sample['input_row_count'] == 7
    assert sample['key_fields'] == []
    assert sample['complete_row_count'] is None and sample['missing_row_count'] is None


def test_empty_filtered_input_has_zero_joint_rows_and_unchanged_empty_sum(client, app):
    data, *_ = run(client, app, [step('filter', {'conditions':[{'field':'field_0004','operator':'eq','value':'NONE'}]}),
        step('aggregate', {'metrics':[{'function':'sum','field':'field_0003','alias':'total'}]}, 'S02')])
    output = data['tasks'][0]
    sample = output['execution_metadata']['sample_statistics']
    assert (sample['input_row_count'],sample['complete_row_count'],sample['missing_row_count']) == (0,0,0)
    assert output['result']['rows'] == [{'total':None}]


def test_derived_group_key_uses_actual_derived_field_and_missing_values(client, app):
    data, *_ = run(client, app, [step('derive', {'field':'field_0001','function':'extract_year','alias':'year'}),
        step('group_aggregate', {'dimensions':['year'],'metrics':[{'function':'sum','field':'field_0002','alias':'total'}]}, 'S02')],
        b'date,sales\n2025-01-01,10\n,20\n2026-01-01,30\n')
    sample = data['tasks'][0]['execution_metadata']['sample_statistics']
    assert sample['missing_row_count'] == 1
    assert [f['field'] for f in sample['key_fields']] == ['year','field_0002']


def test_multiple_aggregations_do_not_mislabel_group_rows_as_source_records(client, app):
    data, *_ = run(client, app, [step('group_aggregate', {'dimensions':['field_0001'],
        'metrics':[{'function':'sum','field':'field_0003','alias':'total'}]}),
        step('aggregate', {'metrics':[{'function':'sum','field':'total','alias':'grand_total'}]}, 'S02')])
    assert data['tasks'][0]['execution_metadata']['sample_statistics'] is None


def test_legacy_metadata_remains_unknown_and_inconsistent_new_facts_are_rejected():
    legacy = TaskExecutionMetadata(input_row_count=7,started_at='old',finished_at='old',duration_ms=1,preview_row_count=1)
    assert legacy.sample_statistics is None
    sample = {'aggregate_step_id':'S01','input_row_count':3,
        'key_fields':[{'field':'x','label':'字段','missing_count':1}],
        'complete_row_count':2,'missing_row_count':1,
        'metrics':{'value':{'function':'count','field':'x','label':'字段','basis':'non_null_values','participating_count':2}}}
    SampleStatistics.model_validate(sample)
    for update in [{'complete_row_count':3},{'missing_row_count':0},
                   {'metrics':{'value':{'function':'count','field':'x','label':'字段','basis':'rows','participating_count':3}}}]:
        with pytest.raises(ValidationError):
            SampleStatistics.model_validate({**sample,**update})


def test_execution_sample_facts_flow_into_saved_report_and_html(client, app):
    import asyncio
    from app.services.analysis_report import AnalysisReportService
    from report_fixtures import ReportProvider
    from app.reporting.presentation import build_presentation
    from app.storage.report_repository import ReportRepository
    steps = [step('filter', {'conditions':[{'field':'field_0004','operator':'eq','value':'E'}]}),
             step('group_aggregate', {'dimensions':['field_0001'],'metrics':aggregate_metrics()}, 'S02')]
    data, request, state, profile = run(client, app, steps)
    execution = app.state.executions.complete(data['execution_id'])
    approval = state.engine_approval
    report = asyncio.run(AnalysisReportService(ReportProvider(), app.state.capability_registry).generate(
        approval.intent, approval.validated_plan, execution, profile))
    repository = ReportRepository(app.state.repository.database)
    repository.save(report, {'session_id': state.id})
    saved = repository.get(report.report_id)
    tid = execution.tasks[0].task_id
    sample = saved_samples(saved, tid)
    assert sample.input_row_count == 6 and sample.complete_row_count == 2 and sample.missing_row_count == 4
    html = render_report_v1(saved, build_presentation(saved, profile))
    assert '完整记录 2 条' in html and '关键字段缺失记录数' in html
    assert '至少一个关键字段缺失 4 条' in html
    assert '来源字段先排除缺失，再按不同值计数' in html
    # No sample facts are accepted for external/imported or mismatched records.
    imported = saved.model_copy(update={'execution_source':'imported'})
    assert saved_samples(imported, tid) is None


def test_long_column_labels_do_not_turn_previously_valid_calculations_into_failures(client, app):
    content = (('x' * 2100) + ',sales\na,10\nb,20\n').encode()
    data, *_ = run(client, app, [step('aggregate', {'metrics':[{'function':'count','field':'field_0001','alias':'value'}]})], content)
    assert data['tasks'][0]['result']['rows'] == [{'value':2}]
    sample = data['tasks'][0]['execution_metadata']['sample_statistics']
    assert len(sample['key_fields'][0]['label']) == 1800
