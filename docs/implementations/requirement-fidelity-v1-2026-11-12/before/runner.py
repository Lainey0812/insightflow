"""Drive suite cases through the public API of one isolated app instance and collect what was actually observed."""
import hashlib
import json
import time
from pathlib import Path

from app.regression.scoring import AUTO_CASES, EXPECT_STOP, MANUAL_ONLY, score

SETTLED = {'WAITING_FOR_CLARIFICATION', 'AWAITING_APPROVAL', 'COMPLETED', 'FAILED'}
APPROVAL_NOTE = '回归运行器代为批准：计划可审批时自动批准当前版本，不代表人工审阅。'
ROW_LIMIT = 50


def wait(client, session_id, settled=SETTLED, timeout=240.0):
    deadline = time.monotonic() + timeout
    while True:
        state = client.get('/api/v1/sessions/' + session_id).json()
        if state['status'] in settled or time.monotonic() > deadline:
            return state
        time.sleep(0.2)


def wait_report(client, execution_id, timeout=240.0):
    deadline = time.monotonic() + timeout
    while True:
        generation = client.get('/api/v1/executions/' + execution_id + '/report').json()
        if generation.get('status') in {'completed', 'failed', 'unavailable'} or time.monotonic() > deadline:
            return generation
        time.sleep(0.5)


def plan_summary(record):
    checked = record['validated_plan']
    counts = {'F0': 0, 'F1': 0, 'F2': 0}
    for result in checked['validation_results']:
        counts[result['feasibility']] += 1
    return {'plan_id': record['plan_id'], 'plan_version': record['plan_version'], 'coverage_status': checked['coverage_status'],
            'task_count': len(checked['plan']['tasks']), 'executable_count': len(checked['executable_task_ids']),
            'blocked_count': len(checked['blocked_task_ids']), 'f0_count': counts['F0'], 'f1_count': counts['F1'],
            'unmet_core_count': len(checked['unmet_core_requirements']), 'tasks': checked['plan']['tasks']}


def observe_workflow(app, workflow_id):
    try:
        view = app.state.workflow_observability.get(workflow_id)
    except Exception as exc:
        return {'observation_error': type(exc).__name__}
    trace = view.get('trace') or {}
    calls = trace.get('llm_calls') or []
    templates = {}
    for call in calls:
        templates.setdefault(call['node_id'], set()).add(call['template_snapshot_id'])
    return {'business_status': view['business_lifecycle']['status'], 'failure': view.get('failure'), 'quality': view.get('quality'),
            'llm': {'calls': len(calls), 'retries': sum(1 for c in calls if c.get('retry_index')),
                    'failed': sum(1 for c in calls if c.get('status') != 'succeeded'),
                    'duration_ms': round(sum(c.get('duration_ms') or 0 for c in calls))},
            'insight_calls': sum(1 for c in calls if c['node_id'] == 'insight_generator'),
            'prompt_templates': {node: sorted(ids) for node, ids in templates.items()},
            'nodes': [{k: n.get(k) for k in ('name', 'status', 'error_code', 'duration_ms')} for n in trace.get('nodes') or []]}


def run_case(client, app, case, suite_dir: Path, request_prefix: str):
    observed = {'approved_by_runner': False}
    started = time.perf_counter()
    try:
        data = (suite_dir / case['dataset']).read_bytes()
        response = client.post('/api/v1/sessions', data={'goal': case['user_query'], 'real_workflow': 'true', 'header_row': str(case['header_row'])},
                               files={'file': (Path(case['dataset']).name, data, 'text/csv')})
        if response.status_code != 201:
            observed.update(error_code=(response.json().get('error') or {}).get('code', f'HTTP_{response.status_code}'))
            return observed
        created = response.json()
        session_id = created['id']
        client.headers['X-Session-Token'] = created['review_access_token']
        state = wait(client, session_id)
        observed.update(session_id=session_id, workflow_id=state.get('workflow_id'), initial_status=state['status'])
        if state.get('intent'):
            observed.update(initial_analysis_mode=state['intent'].get('analysis_mode'), initial_next_action=state['intent'].get('next_action'))
        reply = case['expected'].get('clarification_reply')
        if state['status'] == 'WAITING_FOR_CLARIFICATION' and reply:
            client.post('/api/v1/sessions/' + session_id + '/clarifications', json={'answer': reply, 'expected_revision': state['revision']})
            state = wait(client, session_id)
        observed.update(final_status=state['status'], error_code=(state.get('error') or {}).get('code'))
        if state.get('intent'):
            observed['intent'] = {k: state['intent'].get(k) for k in ('analysis_mode', 'next_action')}
        record = state.get('review_plan')
        if record:
            observed['plan'] = plan_summary(record)
            profile = app.state.datasets.profile(record['dataset_id'], record['dataset_version'])
            observed['profile'] = {'row_count': profile.row_count, 'fields': [{'field_id': f.field_id, 'display_name': f.display_name} for f in profile.fields]}
        if state['status'] != 'AWAITING_APPROVAL' or case['case_id'] in EXPECT_STOP:
            return observed
        review = client.get('/api/v1/sessions/' + session_id + '/review').json()
        observed['can_approve'] = bool(review.get('can_approve'))
        if not observed['can_approve']:
            return observed
        body = {k: record[k] for k in ('plan_id', 'plan_version', 'dataset_id', 'dataset_version', 'validation_version')}
        body.update(expected_revision=state['revision'], approval_request_id=f'{request_prefix}-approval-{case["case_id"]}',
                    acknowledged_warnings=app.state.plan_review.warning_ids(app.state.repository.get(session_id).review_plan.validated_plan))
        approval = client.post('/api/v1/sessions/' + session_id + '/approvals', json=body)
        if approval.status_code != 200:
            observed['error_code'] = (approval.json().get('error') or {}).get('code', 'APPROVAL_REJECTED')
            return observed
        observed['approved_by_runner'] = True
        execution = client.post('/api/v1/executions', json={'session_id': session_id, 'plan_id': record['plan_id'],
            'plan_version': record['plan_version'], 'execution_request_id': f'{request_prefix}-{case["case_id"]}'})
        if execution.status_code != 200:
            observed['error_code'] = (execution.json().get('error') or {}).get('code', 'EXECUTION_REJECTED')
            return observed
        execution_id = execution.json()['execution_id']
        full = client.get('/api/v1/executions/' + execution_id + '?view=complete').json()
        observed.update(execution_id=execution_id, execution_status=full.get('execution_status'),
                        result_tables=[(t.get('result') or {}).get('rows', [])[:ROW_LIMIT] for t in full.get('tasks', []) if t.get('status') == 'success'],
                        task_errors=[{'task_id': t['task_id'], 'status': t['status']} for t in full.get('tasks', []) if t.get('status') != 'success'])
        generation = wait_report(client, execution_id)
        observed['report_generation_status'] = generation.get('status')
        if generation.get('report_id'):
            report = client.get('/api/v1/reports/' + generation['report_id']).json()
            observed.update(report_id=report['report_id'], report_status=report.get('report_status'),
                            goal_coverage=report.get('goal_coverage'), insight_count=len(report.get('insights') or []))
        observed['final_status'] = wait(client, session_id)['status']
        return observed
    except Exception as exc:
        observed.update(runner_error=type(exc).__name__, runner_error_message=str(exc)[:300])
        return observed
    finally:
        observed['duration_ms'] = round((time.perf_counter() - started) * 1000)
        client.headers.pop('X-Session-Token', None)
        if observed.get('workflow_id'):
            observed.update(observe_workflow(app, observed['workflow_id']))


def evaluate(client, app, cases, suite_dir: Path, request_prefix: str, selected=AUTO_CASES, on_case=None):
    results = []
    for case in cases:
        cid = case['case_id']
        if cid not in selected:
            reason = MANUAL_ONLY.get(cid, '未选入本次运行。')
            results.append({'case_id': cid, 'title': case['title'], 'status': 'not_run', 'reason': reason, 'checks': [],
                             'manual_review': case.get('safety_boundaries', [])})
            continue
        observed = run_case(client, app, case, suite_dir, request_prefix)
        status, checks = score(case, observed)
        result = {'case_id': cid, 'title': case['title'], 'status': status, 'checks': checks,
                  'manual_review': case.get('safety_boundaries', []), 'approval_note': APPROVAL_NOTE if observed.get('approved_by_runner') else None,
                  **{k: v for k, v in observed.items() if k != 'profile'}}
        results.append(result)
        if on_case:
            on_case(result)
    return results


def summarize(results):
    counts = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    auto = [r for r in results if r['status'] != 'not_run']
    templates = {}
    for r in auto:
        for node, ids in (r.get('prompt_templates') or {}).items():
            templates.setdefault(node, set()).update(ids)
    return {'counts': counts, 'auto_total': len(auto), 'passed': counts.get('passed', 0),
            'llm_calls': sum((r.get('llm') or {}).get('calls', 0) for r in auto),
            'duration_ms': sum(r.get('duration_ms') or 0 for r in auto),
            'prompt_templates': {node: sorted(ids) for node, ids in sorted(templates.items())}}


def source_fingerprint(root: Path):
    digest = hashlib.sha256()
    for path in sorted((root / 'backend/app').rglob('*')):
        if path.is_file() and path.suffix in {'.py', '.sql', '.md', '.txt', '.json'} and '__pycache__' not in path.parts:
            digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def write_new(path: Path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False, default=str)
