"""Re-run a Bad Case from its original file and goal. The saved record omits both."""
import time

from app.regression.runner import APPROVAL_NOTE, observe_workflow, plan_summary, wait, wait_report
from app.replay.judge import NOTICE, frozen_view, judge

MEDIA = {'.csv': 'text/csv', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
FAILURE_KEYS = ('code', 'category', 'label', 'node_name')


def _failure(value):
    if not value:
        return None
    return {k: value.get(k) for k in FAILURE_KEYS}


def project(observed):
    """Fields safe to store. No query, file bytes, result rows, or error text."""
    keep = ('session_id', 'workflow_id', 'initial_status', 'final_status', 'error_code', 'approved_by_runner',
            'execution_id', 'execution_status', 'report_generation_status', 'report_status', 'goal_coverage',
            'business_status', 'duration_ms', 'llm', 'prompt_templates', 'quality', 'runner_error')
    projected = {k: observed.get(k) for k in keep if k in observed}
    if observed.get('failure'):
        projected['failure'] = _failure(observed['failure'])
    if observed.get('plan'):
        plan = observed['plan']
        projected['plan'] = {k: plan.get(k) for k in ('coverage_status', 'task_count', 'executable_count', 'blocked_count',
                                                       'f0_count', 'f1_count', 'unmet_core_count')}
    if observed.get('approved_by_runner'):
        projected['approval_note'] = APPROVAL_NOTE.replace('回归运行器', '回放运行器')
    return projected


def run_source(client, app, source, request_prefix: str, case_id: str):
    observed = {'approved_by_runner': False}
    started = time.perf_counter()
    try:
        response = client.post('/api/v1/sessions', data={'goal': source['goal'], 'real_workflow': 'true', 'header_row': str(source['header_row'])},
                               files={'file': (source['filename'], source['content'], MEDIA[source['extension']])})
        if response.status_code != 201:
            observed['error_code'] = (response.json().get('error') or {}).get('code', f'HTTP_{response.status_code}')
            return observed
        created = response.json()
        client.headers['X-Session-Token'] = created['review_access_token']
        state = wait(client, created['id'])
        observed.update(session_id=created['id'], workflow_id=state.get('workflow_id'), initial_status=state['status'])
        answers = list(source.get('answers') or [])
        while state['status'] == 'WAITING_FOR_CLARIFICATION':
            if not answers:
                observed['source_error'] = '回放到澄清步骤，原会话没有更多已保存的补充回答。'
                observed['final_status'] = state['status']
                return observed
            reply = client.post('/api/v1/sessions/' + created['id'] + '/clarifications',
                                json={'answer': answers.pop(0), 'expected_revision': state['revision']})
            if reply.status_code != 200:
                observed['error_code'] = (reply.json().get('error') or {}).get('code', 'CLARIFICATION_REJECTED')
                return observed
            state = wait(client, created['id'])
        observed.update(final_status=state['status'], error_code=(state.get('error') or {}).get('code'))
        record = state.get('review_plan')
        if record:
            observed['plan'] = plan_summary(record)
        if state['status'] != 'AWAITING_APPROVAL':
            return observed
        review = client.get('/api/v1/sessions/' + created['id'] + '/review').json()
        if not review.get('can_approve'):
            return observed
        body = {k: record[k] for k in ('plan_id', 'plan_version', 'dataset_id', 'dataset_version', 'validation_version')}
        body.update(expected_revision=state['revision'], approval_request_id=f'{request_prefix}-approval-{case_id}',
                    acknowledged_warnings=app.state.plan_review.warning_ids(app.state.repository.get(created['id']).review_plan.validated_plan))
        approval = client.post('/api/v1/sessions/' + created['id'] + '/approvals', json=body)
        if approval.status_code != 200:
            observed['error_code'] = (approval.json().get('error') or {}).get('code', 'APPROVAL_REJECTED')
            return observed
        observed['approved_by_runner'] = True
        execution = client.post('/api/v1/executions', json={'session_id': created['id'], 'plan_id': record['plan_id'],
            'plan_version': record['plan_version'], 'execution_request_id': f'{request_prefix}-{case_id}'})
        if execution.status_code != 200:
            observed['error_code'] = (execution.json().get('error') or {}).get('code', 'EXECUTION_REJECTED')
            return observed
        execution_id = execution.json()['execution_id']
        full = client.get('/api/v1/executions/' + execution_id + '?view=complete').json()
        observed.update(execution_id=execution_id, execution_status=full.get('execution_status'))
        generation = wait_report(client, execution_id)
        observed['report_generation_status'] = generation.get('status')
        if generation.get('report_id'):
            report = client.get('/api/v1/reports/' + generation['report_id']).json()
            observed.update(report_status=report.get('report_status'), goal_coverage=report.get('goal_coverage'))
        observed['final_status'] = wait(client, created['id'])['status']
        return observed
    except Exception as exc:
        observed.update(runner_error=type(exc).__name__)
        return observed
    finally:
        observed['duration_ms'] = round((time.perf_counter() - started) * 1000)
        client.headers.pop('X-Session-Token', None)
        if observed.get('workflow_id'):
            extra = observe_workflow(app, observed['workflow_id'])
            extra['failure'] = _failure(extra.get('failure'))
            observed.update(extra)


def replay(client, app, prepared, request_prefix: str, on_case=None):
    results = []
    for item in prepared:
        source = item.get('source')
        if item.get('outcome'):
            result = {k: v for k, v in item.items() if k != 'source'}
        else:
            observed = run_source(client, app, source, request_prefix, item['case_id'])
            outcome, reason = judge(frozen_view(item['case']), observed)
            result = {k: v for k, v in item.items() if k not in {'source', 'case'}}
            result.update(outcome=outcome, reason=reason, source_ref={'session_id': source['session_id'], 'dataset_id': source['dataset_id'],
                          'dataset_version': source['dataset_version'], 'file_sha256': source['file_sha256']}, **project(observed))
        results.append(result)
        if on_case:
            on_case(result)
    return results


def summarize(results):
    counts = {}
    for result in results:
        counts[result['outcome']] = counts.get(result['outcome'], 0) + 1
    ran = [r for r in results if r['outcome'] != 'not_run']
    templates = {}
    for result in ran:
        for node, ids in (result.get('prompt_templates') or {}).items():
            templates.setdefault(node, set()).update(ids)
    return {'counts': counts, 'auto_total': len(ran), 'cleared': counts.get('cleared', 0),
            'recurred': counts.get('recurred', 0), 'source_missing': counts.get('source_missing', 0),
            'llm_calls': sum((r.get('llm') or {}).get('calls', 0) for r in ran),
            'duration_ms': sum(r.get('duration_ms') or 0 for r in ran),
            'prompt_templates': {node: sorted(ids) for node, ids in sorted(templates.items())},
            'notice': NOTICE}
