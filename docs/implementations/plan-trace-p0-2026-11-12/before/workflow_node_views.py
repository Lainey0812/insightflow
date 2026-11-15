"""Read-only node projections. They do not change plans, approvals, execution or reports."""

_BASIS_KEYS = ('version', 'digest', 'plan_id', 'plan_version', 'dataset_id', 'dataset_version',
               'row_grain', 'entity_field_id', 'declaration_source')
_DROP = {'rows', 'cells', 'source_row_indices', 'result_data'}


def _scrub(value, depth=0):
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {key: _scrub(item, depth + 1) for key, item in value.items() if key not in _DROP}
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value[:40]]
    return value


def validation_view(validated, source):
    plan = validated.get('plan') or {}
    return {'source': source, 'plan_id': plan.get('plan_id'), 'plan_version': plan.get('plan_version'),
            'dataset_id': plan.get('dataset_id'), 'dataset_version': plan.get('dataset_version'),
            'coverage_status': validated.get('coverage_status'), 'fully_executable': validated.get('fully_executable'),
            'executable_task_ids': validated.get('executable_task_ids') or [],
            'blocked_task_ids': validated.get('blocked_task_ids') or [],
            'unmet_core_requirements': validated.get('unmet_core_requirements') or [],
            'validation_results': validated.get('validation_results') or [],
            'validation_version': validated.get('validation_version'), 'registry_version': validated.get('registry_version'),
            'approval_required': validated.get('approval_required', True), 'plan': plan, 'corrected_plan': None}


def execution_view(result):
    tasks = []
    for task in result.get('tasks') or []:
        if not isinstance(task, dict):
            continue
        meta = task.get('execution_metadata') if isinstance(task.get('execution_metadata'), dict) else {}
        table = task.get('result') if isinstance(task.get('result'), dict) else {}
        error = task.get('error') if isinstance(task.get('error'), dict) else None
        basis = meta.get('analysis_basis') if isinstance(meta.get('analysis_basis'), dict) else None
        samples = meta.get('sample_statistics') if isinstance(meta.get('sample_statistics'), dict) else None
        tasks.append({'task_id': task.get('task_id'), 'status': task.get('status'),
            'effective_row_count': task.get('effective_row_count'), 'valid_sample_count': task.get('valid_sample_count'),
            'row_count': task.get('row_count'), 'calculation': task.get('calculation'), 'scope': task.get('scope'),
            'sample_definition': task.get('sample_definition'), 'failure_reason': task.get('failure_reason'),
            'result_id': task.get('result_id'), 'result_ref': task.get('result_ref'),
            'output_row_count': table.get('total_result_rows'), 'truncated': table.get('truncated'),
            'preview_row_count': meta.get('preview_row_count'), 'input_row_count': meta.get('input_row_count'),
            'duration_ms': meta.get('duration_ms'), 'warnings': meta.get('warnings') or [],
            'error': {'code': error.get('code'), 'message': error.get('message'), 'step_id': error.get('step_id')} if error else None,
            'steps': [{'step_id': step.get('step_id'), 'operation': step.get('operation'), 'status': step.get('status'),
                       'input_row_count': step.get('input_row_count'), 'output_row_count': step.get('output_row_count'),
                       'duration_ms': step.get('duration_ms')}
                      for step in meta.get('steps') or [] if isinstance(step, dict)],
            'sample_statistics': None if samples is None else {
                'input_row_count': samples.get('input_row_count'), 'complete_row_count': samples.get('complete_row_count'),
                'missing_row_count': samples.get('missing_row_count'),
                'key_fields': [{'field': field.get('field'), 'label': field.get('label'), 'missing_count': field.get('missing_count')}
                               for field in samples.get('key_fields') or [] if isinstance(field, dict)],
                'metrics': {key: {'function': item.get('function'), 'field': item.get('field'), 'basis': item.get('basis'),
                                  'participating_count': item.get('participating_count')}
                            for key, item in (samples.get('metrics') or {}).items() if isinstance(item, dict)}},
            'analysis_basis': None if basis is None else {**{key: basis.get(key) for key in _BASIS_KEYS},
                'metrics': [_scrub(metric) for metric in basis.get('metrics') or [] if isinstance(metric, dict)]}})
    return {'execution_id': result.get('execution_id'), 'plan_id': result.get('plan_id'),
            'plan_version': result.get('plan_version'), 'approved_plan_version': result.get('approved_plan_version'),
            'approval_id': result.get('approval_id'), 'dataset_id': result.get('dataset_id'),
            'dataset_version': result.get('dataset_version'), 'execution_status': result.get('execution_status'),
            'source': result.get('source'), 'started_at': result.get('started_at'), 'finished_at': result.get('finished_at'),
            'duration_ms': result.get('duration_ms'),
            'errors': [{'code': error.get('code'), 'message': error.get('message'), 'task_id': error.get('task_id'),
                        'step_id': error.get('step_id')} for error in result.get('errors') or [] if isinstance(error, dict)],
            'warnings': result.get('warnings') or [], 'tasks': tasks, 'rows_omitted': True}


def report_view(report):
    summary = report.get('summary') if isinstance(report.get('summary'), dict) else {}
    provenance = report.get('provenance') if isinstance(report.get('provenance'), dict) else {}
    evidence = []
    for item in report.get('evidence') or []:
        if isinstance(item, dict):
            evidence.append({key: item.get(key) for key in ('evidence_id', 'task_id', 'evidence_type', 'calculation',
                                                             'statement', 'scope', 'related_result_refs', 'data_ref')})
    return {'report_id': report.get('report_id'), 'execution_id': report.get('execution_id'),
            'report_status': report.get('report_status'), 'goal_coverage': report.get('goal_coverage'),
            'generated_at': report.get('generated_at'), 'plan_version': report.get('plan_version'),
            'dataset_id': report.get('dataset_id'), 'dataset_version': report.get('dataset_version'),
            'dataset_row_count': report.get('dataset_row_count'), 'analysis_goal': report.get('analysis_goal'),
            'fact_validation': report.get('fact_validation'),
            'summary': {'headline': summary.get('headline'), 'overview': summary.get('overview'),
                        'evidence_refs': summary.get('evidence_refs') or []},
            'key_metrics': [_scrub(metric) for metric in report.get('key_metrics') or [] if isinstance(metric, dict)],
            'insights': [{key: item.get(key) for key in ('insight_id', 'task_id', 'fact', 'finding', 'implication',
                         'recommendation', 'evidence_refs', 'limitations')}
                         for item in report.get('insights') or [] if isinstance(item, dict)],
            'charts': [{key: item.get(key) for key in ('chart_id', 'task_id', 'title', 'chart_type', 'dimension',
                       'metrics', 'data_ref', 'evidence_refs', 'note')}
                       for item in report.get('charts') or [] if isinstance(item, dict)],
            'recommendations': report.get('recommendations') or [], 'limitations': report.get('limitations') or [],
            'uncompleted_tasks': report.get('uncompleted_tasks') or [], 'evidence': evidence,
            'provenance_notice': provenance.get('notice'), 'result_rows_omitted': True}


def _history(records):
    return [{'plan_id': item.get('plan_id'), 'plan_version': item.get('plan_version'), 'change_type': item.get('change_type'),
             'created_at': item.get('created_at'), 'change_summary': item.get('change_summary'),
             'dataset_id': item.get('dataset_id'), 'dataset_version': item.get('dataset_version')} for item in records]


def attach_node_views(nodes, *, planner_result, version_records, execution_views, report_views, approvals,
                      engine_approval, review_status, approved_plan_version):
    created = [item for item in version_records if item.get('change_type') == 'created']
    for node in nodes:
        role = (node.get('attributes') or {}).get('validation_role')
        if node.get('name') == 'plan_validator' and role == 'planner_output' and planner_result:
            node['validator_view'] = validation_view(planner_result, 'planner_output')
        elif node.get('name') == 'plan_validator' and role == 'initial_plan_save' and len(created) == 1:
            node['validator_view'] = validation_view(created[0].get('validated_plan') or {}, 'initial_plan_save')
    executions = [item for item in execution_views if item.get('execution_id')]
    engines = [node for node in nodes if node.get('name') == 'analysis_engine']
    for node in engines:
        attrs = node.get('attributes') or {}
        ref = attrs.get('execution_id') or attrs.get('result_ref')
        match = next((item for item in executions if item['execution_id'] == ref), None)
        if match is None and len(executions) == 1 and len(engines) == 1:
            match = executions[0]
        if match is not None:
            node['execution_view'] = match
    reports = [item for item in report_views if item.get('report_id')]
    for node in nodes:
        if node.get('name') not in {'insight_generator', 'evidence_builder', 'chart_builder', 'report_assembler', 'report_persistence'}:
            continue
        attrs = node.get('attributes') or {}
        match = next((item for item in reports if item['report_id'] == attrs.get('report_id')), None)
        if match is None and len(reports) == 1:
            match = reports[0]
        if match is not None:
            node['report_view'] = match
    for node in nodes:
        if node.get('name') != 'fact_validator' or len(reports) != 1:
            continue
        node['fact_note'] = reports[0].get('fact_validation')
    history = _history(version_records)
    approval = engine_approval or {}
    approval_id = (approval.get('approval_id') if isinstance(approval, dict) else None)
    snapshot_plan = ((approval.get('validated_plan') or {}).get('plan') or {}) if isinstance(approval, dict) else {}
    for node in nodes:
        if node.get('name') != 'hitl':
            continue
        attrs = node.get('attributes') or {}
        matched = bool(approval_id and attrs.get('approval_id') == approval_id)
        link = next((item for item in approvals if item.get('approval_id') == attrs.get('approval_id')), {})
        executed = [{'execution_id': item.get('execution_id'), 'plan_id': item.get('plan_id'),
                     'plan_version': item.get('plan_version'), 'approved_plan_version': item.get('approved_plan_version'),
                     'execution_status': item.get('execution_status')}
                    for item in executions if matched and item.get('approval_id') == approval_id]
        node['approval_view'] = {'review_status': review_status, 'approved_plan_version': approved_plan_version,
            'command': attrs.get('command'), 'outcome': attrs.get('outcome'), 'span_plan_id': attrs.get('plan_id'),
            'span_plan_version': attrs.get('plan_version'), 'history': history, 'history_complete': False,
            'matched_approval': matched,
            'decision': None if not matched else {'approval_id': approval_id, 'status': approval.get('status'),
                'approved_at': approval.get('approved_at'), 'plan_id': snapshot_plan.get('plan_id'),
                'plan_version': snapshot_plan.get('plan_version'),
                'constraints_confirmed': approval.get('constraints_confirmed'),
                'snapshot_hash': link.get('snapshot_hash'), 'plan_version_id': link.get('plan_version_id')},
            'executed': executed}
