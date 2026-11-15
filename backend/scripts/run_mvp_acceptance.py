"""Frozen product acceptance against real APIs and configured LLM, in isolated storage.

This script does not alter product rules or use production operation kernels as its oracle.
Inputs are synthetic. Raw requests/outputs are written only to the evaluation directory.
"""
import argparse
import ast
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / 'docs/evaluations/mvp-product-v1-2026-11-04'
FROZEN = ARTIFACT / 'frozen'


def write(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False, default=str)


def load_environment():
    for raw in (ROOT / 'backend/.env').read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            continue
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = ast.literal_eval(value)
        os.environ[key.strip()] = value


def verify_freeze():
    manifest = json.loads((FROZEN / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen input changed: ' + name)


def clean(value):
    """Normalize numpy/pandas values for exact labelled-table comparison."""
    import pandas as pd
    if value is None or pd.isna(value):
        return None
    if hasattr(value, 'item'):
        return value.item()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def equivalent(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(equivalent(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-8)
    return left == right


def metric(frame, spec):
    field, function = spec.get('field'), spec['function']
    if function == 'count':
        return len(frame) if field is None else int(frame[field].count())
    series = frame[field]
    if function == 'distinct_count':
        return int(series.nunique())
    if not series.count():
        return None
    return clean(getattr(series, {'avg': 'mean'}.get(function, function))())


def reference_chain(source, task):
    """Independent dataframe reference, without importing Engine or Registry handlers."""
    import pandas as pd
    frame = source.copy()
    membership = None
    for step in task['steps']:
        operation, params = step['operation'], step['params']
        if operation == 'filter':
            for condition in params['conditions']:
                series = frame[condition['field']]
                value, op = condition['value'], condition['operator']
                if pd.api.types.is_datetime64_any_dtype(series) and value is not None:
                    value = [pd.Timestamp(v) for v in value] if isinstance(value, list) else pd.Timestamp(value)
                if op == 'is_null':
                    selected = series.isna()
                elif op == 'not_null':
                    selected = series.notna()
                elif op in ('in', 'not_in'):
                    selected = series.isin(value)
                    if op == 'not_in':
                        selected = ~selected
                    selected &= series.notna()
                else:
                    selected = getattr(series, {'gte': 'ge', 'lte': 'le'}.get(op, op))(value) & series.notna()
                frame = frame.loc[selected.fillna(False)]
        elif operation == 'derive':
            attribute = {'extract_year': 'year', 'extract_month': 'month'}[params['function']]
            frame = frame.assign(**{params['alias']: getattr(pd.to_datetime(frame[params['field']]).dt, attribute)})
        elif operation in ('aggregate', 'group_aggregate'):
            membership = list(frame.index)
            dimensions = params.get('dimensions', [])
            if dimensions:
                rows = []
                for key, group in frame.groupby(dimensions, sort=False, dropna=False):
                    key = key if isinstance(key, tuple) else (key,)
                    rows.append({**dict(zip(dimensions, key)), **{m['alias']: metric(group, m) for m in params['metrics']}})
                frame = pd.DataFrame(rows, columns=dimensions + [m['alias'] for m in params['metrics']])
            else:
                frame = pd.DataFrame([{m['alias']: metric(frame, m) for m in params['metrics']}])
        elif operation in ('sort', 'top_n'):
            frame = frame.sort_values(params['field'], ascending=params['direction'] == 'asc', kind='stable', na_position='last')
            if operation == 'top_n':
                frame = frame.head(params['n'])
        else:
            raise ValueError('Unsupported reference operation ' + operation)
    return [{k: clean(v) for k, v in row.items()} for row in frame.to_dict('records')], membership


def business_oracle(source, case, names):
    import pandas as pd
    frame = source.copy()
    for field, operation, value in case.get('filters', []):
        series = frame[names[field]]
        if operation == 'year':
            selected = pd.to_datetime(series).dt.year == value
        elif operation == 'in':
            selected = series.isin(value)
        else:
            selected = getattr(series, operation)(value)
        frame = frame.loc[selected]
    members = list(frame.index)
    dimension = case.get('dimension')
    if dimension and dimension.startswith('month('):
        key = '__expected_month'
        frame[key] = pd.to_datetime(frame[names[dimension[6:-1]]]).dt.month
    else:
        key = names[dimension] if dimension else None
    spec = {'function': case['function'], 'field': names[case['metric_field']] if case.get('metric_field') else None}
    if key:
        rows = [{'category': clean(k), 'value': metric(g, spec)} for k, g in frame.groupby(key, sort=False, dropna=False)]
    else:
        rows = [{'value': metric(frame, spec)}]
    if case.get('order'):
        order_key = 'category' if case.get('requires_derive') else 'value'
        rows.sort(key=lambda r: r[order_key], reverse=case['order'] == 'desc')
    if case.get('top_n'):
        rows = rows[:case['top_n']]
    return rows, members


def check_plan(case, plan, checked, source, names):
    expected, members = business_oracle(source, case, names)
    errors, matches = [], []
    for task in plan['tasks']:
        if any(m.get('field') == names[field] for field in case.get('prohibited_fields', []) for step in task['steps'] for m in step['params'].get('metrics', [])):
            errors.append('PROHIBITED_METRIC:' + task['task_id'])
        for step in task['steps']:
            params = step['params']
            for m in params.get('metrics', []):
                if m['function'] != case['function'] or m.get('field') != (names[case['metric_field']] if case.get('metric_field') else None):
                    continue
                dimensions = params.get('dimensions', [])
                dimension = case.get('dimension')
                if case.get('requires_derive'):
                    dim = next((s['params']['alias'] for s in task['steps'] if s['operation'] == 'derive' and s['params']['function'] == 'extract_month' and s['params']['field'] == names[dimension[6:-1]]), None)
                else:
                    dim = names[dimension] if dimension else None
                if dimensions != ([dim] if dim else []):
                    continue
                rows, actual_members = reference_chain(source, task)
                projected = [({'category': r[dim], 'value': r[m['alias']]} if dim else {'value': r[m['alias']]}) for r in rows]
                target = expected
                if not case.get('order'):
                    projected = sorted(projected, key=lambda x: str(x.get('category')))
                    target = sorted(expected, key=lambda x: str(x.get('category')))
                reasons = []
                if not equivalent(projected, target):
                    reasons.append('GOAL_RESULT_MISMATCH')
                if set(actual_members or []) != set(members):
                    reasons.append('FILTER_SCOPE_MISMATCH')
                sorts = [s for s in task['steps'] if s['operation'] in ('sort', 'top_n')]
                order_field = dim if case.get('requires_derive') else m['alias']
                if case.get('order') and not any(s['params']['field'] == order_field and s['params']['direction'] == case['order'] for s in sorts):
                    reasons.append('ORDER_NOT_PRESERVED')
                if case.get('top_n') and not any(s['operation'] == 'top_n' and s['params']['n'] == case['top_n'] for s in sorts):
                    reasons.append('TOP_N_NOT_PRESERVED')
                matches.append({'task_id': task['task_id'], 'metric_alias': m['alias'], 'dimension': dim, 'errors': reasons, 'expected': target, 'reference': projected})
    if not matches:
        errors.append('REQUIRED_METRIC_OR_DIMENSION_NOT_PLANNED')
    elif all(m['errors'] for m in matches):
        errors.extend(matches[0]['errors'])
    if case.get('no_extra_tasks') and len(plan['tasks']) != 1:
        errors.append('UNREQUESTED_OR_DUPLICATE_TASKS_REVIEW_REQUIRED')
    if checked['coverage_status'] == 'blocked':
        errors.append('EXPECTED_GOAL_BLOCKED')
    return {'errors': list(dict.fromkeys(errors)), 'matches': matches, 'expected': expected}


def run(case_id, run_name):
    verify_freeze()
    case = next(c for c in json.loads((FROZEN / 'cases.json').read_text()) if c['case_id'] == case_id)
    out = ARTIFACT / 'runs' / run_name / case_id
    out.mkdir(parents=True, exist_ok=False)
    load_environment()
    runtime = ROOT / 'var/verification/mvp-product-v1-2026-11-04' / run_name / case_id
    os.environ['INSIGHTFLOW_DATA_DIR'] = str(runtime)
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.config import Settings
    from app.main import create_app
    from app.llm.compatible_provider import CompatibleLLMProvider
    from fastapi.testclient import TestClient
    from dataclasses import replace
    import pandas as pd
    settings = replace(Settings.from_env(), data_dir=runtime, admin_read_token='mvp-synthetic-read', admin_local_test_mode=False)
    if not settings.llm_api_key or settings.llm_model != 'qwen3.8-flash':
        raise RuntimeError('Configured qwen3.8-flash credentials required; no Mock fallback')

    class ObservedProvider(CompatibleLLMProvider):
        counter = 0

        async def _send(self, payload):
            self.counter += 1
            index = self.counter
            write(out / f'http-{index:02d}-request.json', payload)
            try:
                response = await super()._send(payload)
            except BaseException as exc:
                write(out / f'http-{index:02d}-error.json', {'code': getattr(getattr(exc, 'error', None), 'code', type(exc).__name__)})
                raise
            write(out / f'http-{index:02d}-response.json', response.model_dump(mode='json'))
            return response

    provider = ObservedProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.llm_timeout_seconds)
    app = create_app(settings, provider)
    write(out / 'configuration.json', {'model': settings.llm_model, 'timeout_seconds': settings.llm_timeout_seconds,
        'intent_max_attempts': settings.intent_max_attempts, 'planner_max_attempts': settings.planner_max_attempts,
        'intent_enable_thinking': settings.intent_enable_thinking, 'planner_enable_thinking': settings.planner_enable_thinking,
        'report_enable_thinking': settings.report_enable_thinking, 'data_dir': str(runtime),
        'endpoint_sha256': hashlib.sha256(provider.url.encode()).hexdigest(), 'input_type': 'synthetic', 'schema': 'existing-project-contracts'})
    started = time.perf_counter()
    result = {'case_id': case_id, 'split': case['split'], 'status': 'pending_review', 'checks': {}, 'errors': [], 'human_review': 'not_performed'}
    with TestClient(app) as client:
        try:
            response = client.post('/api/v1/sessions', data={'real_workflow': 'true', 'goal': case['query']}, files={'file': (case['domain']+'.csv', (FROZEN / (case['domain']+'.csv')).read_bytes(), 'text/csv')})
            initial = response.json()
            write(out / 'create-response.json', {k: v for k, v in initial.items() if k != 'review_access_token'})
            if response.status_code != 201:
                result.update(status='failed', errors=['CREATE_FAILED'])
                return finish(out, result, started)
            session_id = initial['id']
            client.headers['X-Session-Token'] = initial['review_access_token']
            state = client.get('/api/v1/sessions/' + session_id).json()
            result.update(session_id=session_id, workflow_id=state['workflow_id'], root_run_id=state['root_run_id'])
            write(out / 'prepared-session.json', state)
            if case['kind'] == 'clarify':
                result['checks']['initial_clarification'] = state['status'] == 'WAITING_FOR_CLARIFICATION'
                if not result['checks']['initial_clarification']:
                    result.update(status='failed', errors=['EXPECTED_CLARIFICATION_MISSING'])
                    return finish(out, result, started, app, client)
                response = client.post('/api/v1/sessions/' + session_id + '/clarifications', json={'answer': case['clarification'], 'expected_revision': state['revision']})
                write(out / 'clarification-response.json', response.json())
                state = client.get('/api/v1/sessions/' + session_id).json()
            if case['kind'] == 'blocked':
                plan = state.get('review_plan')
                blocked = state['status'] == 'WAITING_FOR_CLARIFICATION' or bool(plan and plan['validated_plan']['coverage_status'] == 'blocked')
                result.update(status='pending_review' if blocked else 'failed', expected_stop=blocked,
                    errors=[] if blocked else ['UNSUPPORTED_CORE_NOT_BLOCKED'])
                return finish(out, result, started, app, client)
            if state['status'] != 'AWAITING_APPROVAL':
                code = (state.get('error') or {}).get('code', state['status'])
                result.update(status='unavailable' if code.startswith(('LLM_', 'PLANNER_LLM_', 'PROMPT_')) else 'failed', errors=[code])
                return finish(out, result, started, app, client)
            record = state['review_plan']
            checked, plan = record['validated_plan'], record['validated_plan']['plan']
            profile = app.state.datasets.profile(record['dataset_id'], record['dataset_version'])
            write(out / 'profile.json', profile.model_dump(mode='json'))
            source = pd.read_csv(FROZEN / (case['domain']+'.csv'))
            names = {f.display_name: f.field_id for f in profile.fields}
            source = source.rename(columns=names)
            for field in profile.fields:
                if field.logical_type.value in ('date', 'datetime'):
                    source[field.field_id] = pd.to_datetime(source[field.field_id])
            if case['kind'] != 'exploratory':
                goal = check_plan(case, plan, checked, source, names)
                write(out / 'goal-oracle.json', goal)
                result['checks']['goal_plan'] = not goal['errors']
                if goal['errors']:
                    result.update(status='failed', errors=goal['errors'], execution_withheld=True)
                    return finish(out, result, started, app, client)
            else:
                result['checks']['exploratory_mode'] = state['intent']['analysis_mode'] == 'exploratory'
                if not result['checks']['exploratory_mode']:
                    result.update(status='failed', errors=['EXPLORATORY_MODE_MISMATCH'])
                    return finish(out, result, started, app, client)
            execute_body = {'session_id': session_id, 'plan_id': record['plan_id'], 'plan_version': record['plan_version'], 'execution_request_id': 'mvp-' + case_id}
            guard = client.post('/api/v1/executions', json=execute_body)
            result['checks']['unapproved_rejected'] = guard.status_code == 409
            write(out / 'unapproved-check.json', {'http_status': guard.status_code, 'body': guard.json()})
            if not result['checks']['unapproved_rejected']:
                result.update(status='failed', errors=['UNAPPROVED_EXECUTION_NOT_REJECTED'])
                return finish(out, result, started, app, client)
            review = client.get('/api/v1/sessions/' + session_id + '/review')
            write(out / 'review-presentation.json', review.json())
            if not review.json().get('can_approve'):
                result.update(status='failed', errors=['APPROVAL_BLOCKED'], execution_withheld=True)
                return finish(out, result, started, app, client)
            body = {k: record[k] for k in ('plan_id', 'plan_version', 'dataset_id', 'dataset_version', 'validation_version')}
            body.update(expected_revision=state['revision'], approval_request_id='mvp-approval-' + case_id,
                acknowledged_warnings=app.state.plan_review.warning_ids(app.state.repository.get(session_id).review_plan.validated_plan))
            response = client.post('/api/v1/sessions/' + session_id + '/approvals', json=body)
            write(out / 'approval-response.json', response.json())
            if response.status_code != 200:
                result.update(status='failed', errors=['APPROVAL_REJECTED'])
                return finish(out, result, started, app, client)
            response = client.post('/api/v1/executions', json=execute_body)
            write(out / 'execution-response.json', response.json())
            if response.status_code != 200:
                result.update(status='failed', errors=['EXECUTION_REJECTED'])
                return finish(out, result, started, app, client)
            execution_id = response.json()['execution_id']
            full = client.get('/api/v1/executions/' + execution_id + '?view=complete').json()
            write(out / 'execution-complete.json', full)
            result.update(execution_id=execution_id, execution_status=full['execution_status'])
            baseline_checks = []
            for task in full['tasks']:
                if task['status'] != 'success':
                    baseline_checks.append({'task_id': task['task_id'], 'status': task['status'], 'passed': False})
                    continue
                expected, _ = reference_chain(source, next(t for t in plan['tasks'] if t['task_id'] == task['task_id']))
                baseline_checks.append({'task_id': task['task_id'], 'passed': equivalent(expected, task['result']['rows']), 'expected': expected, 'actual': task['result']['rows']})
            write(out / 'execution-oracle.json', baseline_checks)
            result['checks']['calculation'] = all(c['passed'] for c in baseline_checks)
            replay = client.post('/api/v1/executions', json=execute_body)
            result['checks']['execution_idempotent'] = replay.status_code == 200 and replay.json()['execution_id'] == execution_id
            generation = client.get('/api/v1/executions/' + execution_id + '/report').json()
            write(out / 'report-generation.json', generation)
            result['report_generation_status'] = generation['status']
            if generation.get('report_id'):
                report = client.get('/api/v1/reports/' + generation['report_id']).json()
                presentation = client.get('/api/v1/reports/' + generation['report_id'] + '/presentation')
                write(out / 'analysis-report.json', report)
                write(out / 'presentation.json', presentation.json())
                result.update(report_id=report['report_id'], report_status=report['report_status'], goal_coverage=report['goal_coverage'])
                ids = {e['evidence_id'] for e in report['evidence']}
                result['checks']['evidence_refs'] = bool(report['insights']) and all(i['evidence_refs'] and set(i['evidence_refs']) <= ids for i in report['insights'])
                result['checks']['persisted_report_readable'] = presentation.status_code == 200
                if report['report_status'] == 'partial':
                    result['status'] = 'partial'
                elif report['report_status'] == 'unavailable':
                    result['status'] = 'unavailable'
            else:
                result.update(status='failed', errors=['REPORT_NOT_DELIVERED'])
            if not all(result['checks'].values()):
                result['status'] = 'failed'
                result['errors'].extend(k.upper() for k, v in result['checks'].items() if not v)
            return finish(out, result, started, app, client)
        except Exception as exc:
            # Keep runner defects separate from product failures; do not expose configuration.
            result.update(status='runner_error', runner_error_type=type(exc).__name__, runner_error_message=str(exc)[:500])
            return finish(out, result, started, app, client)


def finish(out, result, started, app=None, client=None):
    result['elapsed_seconds'] = round(time.perf_counter()-started, 3)
    if app and result.get('workflow_id'):
        try:
            trace = client.get('/admin/workflow-traces/' + result['workflow_id'], headers={'X-Admin-Token': 'mvp-synthetic-read'})
            write(out / 'workflow-trace.json', trace.json())
            result['trace_http_status'] = trace.status_code
            calls = app.state.llm_captures.repository.calls(run_id=result['root_run_id'])
            write(out / 'llm-calls.json', [c.model_dump(mode='json') for c in calls])
            result['llm_call_count'] = len(calls)
        except Exception as exc:
            result['collection_error'] = type(exc).__name__
    write(out / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--suite-root', type=Path, help='Optional separately frozen suite under docs/evaluations; original Gold is never edited.')
    arguments = parser.parse_args()
    if arguments.suite_root:
        selected = arguments.suite_root.resolve()
        if not selected.is_relative_to(ROOT / 'docs/evaluations'):
            parser.error('suite-root must be within docs/evaluations')
        ARTIFACT, FROZEN = selected, selected / 'frozen'
    run(arguments.case, arguments.run)
