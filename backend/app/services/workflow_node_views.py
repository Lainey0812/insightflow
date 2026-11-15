"""Read-only node projections. They do not change plans, approvals, execution or reports."""

_BASIS_KEYS = ('version', 'digest', 'plan_id', 'plan_version', 'dataset_id', 'dataset_version',
               'row_grain', 'entity_field_id', 'declaration_source')
_DROP = {'rows', 'cells', 'source_row_indices', 'result_data'}


def _preview_cell(value):
    if isinstance(value, str) and len(value) > 200:
        return value[:200]
    return value


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
            'result_columns': [{'field': column.get('field'), 'label': column.get('label') or column.get('field')}
                               for column in (table.get('columns') or []) if isinstance(column, dict)][:8],
            'result_preview': [{column.get('field'): _preview_cell(row.get(column.get('field')))
                                for column in (table.get('columns') or [])[:8] if isinstance(column, dict) and column.get('field')}
                               for row in (table.get('rows') or [])[:20] if isinstance(row, dict)],
            'preview_limited': len(table.get('rows') or []) > 20,
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


def _version_record(records, plan_id, plan_version):
    if plan_id is None or plan_version is None:
        return None
    found = [item for item in records if item.get('plan_id') == plan_id and item.get('plan_version') == plan_version]
    return found[0] if len(found) == 1 else None


def _plan_of(record):
    if not isinstance(record, dict):
        return None
    validated = record.get('validated_plan') if 'validated_plan' in record else record
    plan = validated.get('plan') if isinstance(validated, dict) else None
    return plan if isinstance(plan, dict) else None


def _rule(task):
    filters, dimensions, metrics, fields = [], [], [], []
    for step in task.get('steps') or []:
        if not isinstance(step, dict):
            continue
        params = step.get('params') if isinstance(step.get('params'), dict) else {}
        operation = step.get('operation')
        if operation == 'filter':
            for condition in params.get('conditions') or []:
                if isinstance(condition, dict):
                    filters.append({'field': condition.get('field'), 'operator': condition.get('operator'), 'value': condition.get('value')})
                    fields.append(condition.get('field'))
        elif operation in {'aggregate', 'group_aggregate'}:
            for dimension in params.get('dimensions') or []:
                dimensions.append(dimension)
                fields.append(dimension)
            for metric in params.get('metrics') or []:
                if isinstance(metric, dict):
                    metrics.append({'function': metric.get('function'), 'field': metric.get('field'), 'alias': metric.get('alias')})
                    fields.append(metric.get('field'))
        elif operation in {'sort', 'top_n', 'derive'} and params.get('field'):
            fields.append(params.get('field'))
    return {'fields': list(dict.fromkeys(field for field in fields if field)), 'filters': filters,
            'dimensions': dimensions, 'metrics': metrics}


def _task_brief(task):
    return {'task_id': task.get('task_id'), 'title': task.get('title'), 'business_question': task.get('business_question'),
            'priority': task.get('priority'), 'steps': [{'step_id': step.get('step_id'), 'operation': step.get('operation'),
            'params': step.get('params')} for step in task.get('steps') or [] if isinstance(step, dict)],
            'rule': _rule(task)}


def _plan_brief(plan):
    if not isinstance(plan, dict):
        return None
    return {'plan_id': plan.get('plan_id'), 'plan_version': plan.get('plan_version'),
            'dataset_id': plan.get('dataset_id'), 'dataset_version': plan.get('dataset_version'),
            'tasks': [_task_brief(task) for task in plan.get('tasks') or [] if isinstance(task, dict)]}


def _version_line(plan_id, plan_version, executions, engine_approval):
    approval = engine_approval if isinstance(engine_approval, dict) else {}
    snapshot = ((approval.get('validated_plan') or {}).get('plan') or {}) if isinstance(approval.get('validated_plan'), dict) else {}
    approved = snapshot.get('plan_version') if snapshot.get('plan_id') == plan_id else None
    executed = [item.get('plan_version') for item in executions
                if item.get('plan_id') == plan_id and item.get('plan_version') is not None]
    distinct = list(dict.fromkeys(executed))
    return {'validated_plan_id': plan_id, 'validated_plan_version': plan_version,
            'approved_plan_version': approved,
            'executed_plan_version': distinct[0] if len(distinct) == 1 else None,
            'executed_ambiguous': len(distinct) > 1}


def _covering_hitl(node, hitl_nodes):
    start = node.get('started_at')
    if not start:
        return None
    covers = []
    for hitl in hitl_nodes:
        opened, closed = hitl.get('started_at'), hitl.get('finished_at')
        if opened and start >= opened and (not closed or start <= closed):
            covers.append(hitl)
    return covers[0] if len(covers) == 1 else None


def _history(records):
    return [{'plan_id': item.get('plan_id'), 'plan_version': item.get('plan_version'), 'change_type': item.get('change_type'),
             'created_at': item.get('created_at'), 'change_summary': item.get('change_summary'),
             'dataset_id': item.get('dataset_id'), 'dataset_version': item.get('dataset_version')} for item in records]


def attach_node_views(nodes, *, planner_result, version_records, execution_views, report_views, approvals,
                      engine_approval, review_status, approved_plan_version):
    created = [item for item in version_records if item.get('change_type') == 'created']
    executions = [item for item in execution_views if item.get('execution_id')]
    approval = engine_approval if isinstance(engine_approval, dict) else {}
    snapshot_plan = ((approval.get('validated_plan') or {}).get('plan') or {}) if isinstance(approval.get('validated_plan'), dict) else {}
    hitl_nodes = [node for node in nodes if node.get('name') == 'hitl']
    for node in nodes:
        if node.get('name') != 'plan_validator':
            continue
        attrs = node.get('attributes') or {}
        role = attrs.get('validation_role')
        record = _version_record(version_records, attrs.get('plan_id'), attrs.get('plan_version'))
        validated = None
        if record is not None:
            validated = record.get('validated_plan') or {}
        elif role == 'planner_output' and planner_result:
            validated = planner_result
        elif role == 'initial_plan_save' and len(created) == 1:
            validated = created[0].get('validated_plan') or {}
        elif isinstance(role, str) and role.startswith('hitl_'):
            covered = _covering_hitl(node, hitl_nodes)
            covered_attrs = (covered or {}).get('attributes') or {}
            covered_record = _version_record(version_records, covered_attrs.get('plan_id'), covered_attrs.get('plan_version'))
            validated = (covered_record or {}).get('validated_plan') or None
        if isinstance(validated, dict) and validated.get('plan'):
            view = validation_view(validated, role if isinstance(role, str) else 'unspecified')
            plan = view.get('plan') or {}
            view['version_line'] = _version_line(plan.get('plan_id'), plan.get('plan_version'), executions, engine_approval)
            view['plan_brief'] = _plan_brief(plan)
            node['validator_view'] = view
    engines = [node for node in nodes if node.get('name') == 'analysis_engine']
    for node in engines:
        attrs = node.get('attributes') or {}
        ref = attrs.get('execution_id') or attrs.get('result_ref')
        match = next((item for item in executions if item['execution_id'] == ref), None)
        if match is None and len(executions) == 1 and len(engines) == 1:
            match = executions[0]
        if match is not None:
            plan = None
            record = _version_record(version_records, match.get('plan_id'), match.get('plan_version'))
            if record is not None:
                plan = _plan_of(record)
            elif snapshot_plan.get('plan_id') == match.get('plan_id') and snapshot_plan.get('plan_version') == match.get('plan_version'):
                plan = snapshot_plan
            by_task = {task.get('task_id'): task for task in (plan or {}).get('tasks') or [] if isinstance(task, dict)}
            for task in match.get('tasks') or []:
                source = by_task.get(task.get('task_id'))
                task['rule'] = _rule(source) if source else None
            match['plan_brief'] = _plan_brief(plan) if plan else None
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
    approval_id = approval.get('approval_id')
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
        submitted = _version_record(version_records, attrs.get('plan_id'), attrs.get('plan_version'))
        submitted_plan = _plan_brief(_plan_of(submitted)) if submitted else None
        approved_plan = _plan_brief(snapshot_plan) if matched and snapshot_plan else None
        node['approval_view'] = {'review_status': review_status, 'approved_plan_version': approved_plan_version,
            'command': attrs.get('command'), 'outcome': attrs.get('outcome'), 'span_plan_id': attrs.get('plan_id'),
            'span_plan_version': attrs.get('plan_version'), 'history': history, 'history_complete': False,
            'submitted_plan': submitted_plan, 'approved_plan': approved_plan,
            'version_line': _version_line(attrs.get('plan_id'), attrs.get('plan_version'), executions if matched else [], engine_approval if matched else None),
            'matched_approval': matched,
            'decision': None if not matched else {'approval_id': approval_id, 'status': approval.get('status'),
                'approved_at': approval.get('approved_at'), 'plan_id': snapshot_plan.get('plan_id'),
                'plan_version': snapshot_plan.get('plan_version'),
                'constraints_confirmed': approval.get('constraints_confirmed'),
                'snapshot_hash': link.get('snapshot_hash'), 'plan_version_id': link.get('plan_version_id')},
            'executed': executed}
