"""Audit production request assembly using synthetic fixtures + local HTTP transport.
NOT an LLM evaluation, not a production run, no external requests, no SQLite writes.
Run from repository root: .venv/bin/python docs/audits/prompt-loading-paths-2026-10-29/capture_requests.py
Each rerun requires a NEW output directory; never overwrite archived captures.
"""
import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
import httpx
from app.domain.errors import AppError
from app.domain.execution import ApprovedExecutionSnapshot
from app.domain.intent import ParsedIntent
from app.intent import prompt as intent_prompt
from app.planning import prompt as planner_prompt
from app.reporting import prompt as report_prompt
from app.services import intent_parser, analysis_planner, analysis_report
from app.llm.compatible_provider import CompatibleLLMProvider
from app.observability.provenance import digest
from app.planning.capabilities import CapabilityRegistry
from intent_fixtures import intent_payload
from planning_fixtures import recruiting_profile, task
from report_fixtures import report_case

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('captures')
OUT.mkdir(exist_ok=False)
CASES = []
CHECKS = []


def check(name, value):
    CHECKS.append({'check': name, 'passed': bool(value)})
    assert value, name


def text_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def report_response(body):
    evidence = json.loads(body['messages'][1]['content'])['evidence']
    selected = []
    for item in evidence:
        if item['evidence_type'] == 'ranking' and item['task_id'] not in {e['task_id'] for e in selected}:
            selected.append(item)
    return {'insights': [{'primary_evidence_id': e['evidence_id'], 'evidence_refs': [e['evidence_id']],
        'finding_type': 'highlight', 'implication': '当前结果仅作为继续核查的线索。',
        'recommendation': '核查相关分组的记录构成；补充分析尚未执行。',
        'limitations': ['结论仅适用于当前返回范围，不能外推整体市场。']} for e in selected]}


async def exercise(case_id, node, operation, responses):
    calls = []
    def handler(request):
        body = json.loads(request.content)
        entry = {'attempt': len(calls) + 1, 'request': body,
            'system_utf8_sha256': text_hash(body['messages'][0]['content']),
            'user_utf8_sha256': text_hash(body['messages'][1]['content']),
            'response_schema_canonical_sha256': digest(body['response_format']['json_schema']['schema']),
            'body_canonical_sha256': digest(body)}
        calls.append(entry)
        candidate = responses[min(len(calls) - 1, len(responses) - 1)]
        if candidate == '__HTTP_503__':
            entry['scripted_response'] = {'http_status': 503}
            return httpx.Response(503, json={'error': 'local scripted failure'})
        if callable(candidate):
            candidate = candidate(body)
        content = candidate if isinstance(candidate, str) else json.dumps(candidate, ensure_ascii=False)
        entry['scripted_response'] = {'content': content, 'not_real_llm': True}
        return httpx.Response(200, json={'model': 'scripted-transport-not-real-model', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': content}}]})
    provider = CompatibleLLMProvider('https://local-audit.invalid/v1', 'qwen3.8-flash',
                                     transport=httpx.MockTransport(handler))
    try:
        result = await operation(provider)
        outcome = {'kind': 'returned', 'object_type': type(result).__name__}
        if hasattr(result, 'report_status'):
            outcome['report_status'] = result.report_status
        if hasattr(result, 'parse_origin'):
            outcome['parse_origin'] = result.parse_origin
    except AppError as exc:
        outcome = {'kind': 'error', 'code': exc.error.code}
    record = {'case_id': case_id, 'node': node, 'evidence_class': 'synthetic_local_transport_capture',
              'not_real_llm': True, 'database_access_forbidden': True, 'calls': calls, 'outcome': outcome}
    (OUT / f'{case_id}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    CASES.append(record)
    return record


async def main():
    profile = recruiting_profile()
    good = intent_payload(business_goal='比较城市岗位数量', analysis_object='招聘数据')
    bad_grounding = copy.deepcopy(good)
    bad_grounding['constraints']['filters'] = [{'raw_text': '只看广州', 'validation_status': 'unverified'}]
    query = '比较城市岗位数量'
    intent_service = lambda p: intent_parser.IntentParserService(p, enable_thinking=False)
    planner_service = lambda p: analysis_planner.AnalysisPlannerService(p, CapabilityRegistry())
    report_service = lambda p: analysis_report.AnalysisReportService(p, CapabilityRegistry())
    i1 = await exercise('I01-first', 'intent', lambda p: intent_service(p).parse(query, profile, ['保留全部城市']), [good])
    i2 = await exercise('I02-json-retry', 'intent', lambda p: intent_service(p).parse(query, profile), ['not json', good])
    i3 = await exercise('I03-grounding-retry', 'intent', lambda p: intent_service(p).parse(query, profile), [bad_grounding, good])
    i4 = await exercise('I04-empty-guard', 'intent', lambda p: intent_service(p).parse('  ', profile), [good])
    parsed = ParsedIntent.model_validate(good)
    p1 = await exercise('P01-first', 'planner', lambda p: planner_service(p).plan(parsed, profile), [{'tasks': [task()]}])
    p2 = await exercise('P02-json-retry', 'planner', lambda p: planner_service(p).plan(parsed, profile), ['not json', {'tasks': [task()]}])
    clarify = ParsedIntent.model_validate(intent_payload(mode='undetermined', action='clarify'))
    p3 = await exercise('P03-clarify-guard', 'planner', lambda p: planner_service(p).plan(clarify, profile), [{'tasks': [task()]}])
    intent, validated, execution, report_profile = report_case()
    r1 = await exercise('R01-imported', 'report', lambda p: report_service(p).generate(intent, validated, execution, report_profile), [report_response])
    # In-memory constructed approval, only to inspect this assembly branch. Not an Engine/approval acceptance test.
    engine_fixture = execution.model_copy(update={'source': 'engine', 'approval_id': 'audit_approval', 'session_id': 'audit_session'})
    approval = ApprovedExecutionSnapshot(approval_id='audit_approval', approved_at='synthetic-audit-time',
        session_id='audit_session', validated_plan=validated, intent=intent, constraints_confirmed=True)
    r2 = await exercise('R02-approved-context', 'report', lambda p: report_service(p).generate(intent, validated,
        engine_fixture, report_profile, approved_snapshot=approval, original_query='请比较上传招聘数据中的城市岗位数量'), [report_response])
    no_evidence = report_case(null_metrics=True)
    r3 = await exercise('R03-no-evidence', 'report', lambda p: report_service(p).generate(*no_evidence), [report_response])
    r4 = await exercise('R04-http-failure', 'report', lambda p: report_service(p).generate(intent, validated, execution, report_profile), ['__HTTP_503__'])
    multi = report_case(tasks=[task(tid='A01'), task(tid='A02')])
    r5 = await exercise('R05-multi-task-schema', 'report', lambda p: report_service(p).generate(*multi), [report_response])

    def payload(case, index=0):
        return json.loads(case['calls'][index]['request']['messages'][1]['content'])
    def schema(case):
        return case['calls'][0]['request']['response_format']['json_schema']['schema']
    check('13 production assembly scenarios captured', len(CASES) == 13)
    check('intent normal first call succeeds', i1['outcome']['kind'] == 'returned' and len(i1['calls']) == 1)
    check('intent JSON retry adds actual failure code', len(i2['calls']) == 2 and payload(i2, 1)['validation_feedback']['previous_error_code'] == 'LLM_INVALID_JSON')
    check('intent grounding retry selects different static instruction', len(i3['calls']) == 2 and payload(i3, 1)['validation_feedback']['previous_error_code'] == 'LLM_UNGROUNDED_OUTPUT'
          and payload(i3, 1)['validation_feedback']['instruction'] != payload(i2, 1)['validation_feedback']['instruction'])
    check('intent retry does not append assistant conversation', all(len(c['request']['messages']) == 2 for c in i3['calls']))
    check('intent profile samples are empty', payload(i1)['dataset_context']['sample_rows'] == [])
    check('empty input has zero calls', len(i4['calls']) == 0 and i4['outcome']['parse_origin'] == 'input_guard')
    check('planner first call returns validated plan', p1['outcome']['object_type'] == 'ValidatedAnalysisPlan')
    check('planner retry preserves context and adds feedback', len(p2['calls']) == 2 and
        {k:v for k,v in payload(p2, 1).items() if k != 'validation_feedback'} == payload(p2))
    check('clarify blocks planner before provider', not p3['calls'] and p3['outcome']['code'] == 'INTENT_CLARIFICATION_REQUIRED')
    check('planner schema includes six operation branches', len(schema(p1)['$defs']['AnalysisStep']['anyOf']) == 6)
    check('report imported call returns report', r1['outcome']['object_type'] == 'AnalysisReport')
    check('report approved context uses original query and approval flag', payload(r2)['constraints_confirmed'] is True
        and payload(r2)['original_query'] == '请比较上传招聘数据中的城市岗位数量')
    check('report independent fallback uses business goal', payload(r1)['original_query'] == intent.analysis_goal.business_goal
          and payload(r1)['constraints_confirmed'] is False)
    check('report user message contains readable generated scope', bool(payload(r2)['scope_context'][0]['approved_steps']))
    check('report output enum equals selected evidence IDs', schema(r1)['$defs']['DraftInsight']['properties']['primary_evidence_id']['enum']
          == [e['evidence_id'] for e in payload(r1)['evidence']])
    check('report schema changes with selected evidence', schema(r1) != schema(r5))
    check('no evidence produces unavailable with zero calls', not r3['calls'] and r3['outcome']['report_status'] == 'unavailable')
    check('report HTTP failure has no inner retry', len(r4['calls']) == 1 and r4['outcome']['code'] == 'LLM_HTTP_ERROR')
    check('all outbound bodies are precisely two messages with strict schema', all(
        [m['role'] for m in c['request']['messages']] == ['system', 'user']
        and c['request']['response_format']['json_schema']['strict'] is True for case in CASES for c in case['calls']))
    check('provider does not set temperature or top_p', all('temperature' not in c['request'] and 'top_p' not in c['request'] for case in CASES for c in case['calls']))
    modules = {'intent': (intent_prompt, intent_parser), 'planner': (planner_prompt, analysis_planner), 'report': (report_prompt, analysis_report)}
    observation = {}
    for node, (prompt, service) in modules.items():
        check(f'{node} loaded service system equals prompt module at audit time', service.SYSTEM_PROMPT == prompt.SYSTEM_PROMPT)
        check(f'{node} wire system equals loaded service system', all(c['request']['messages'][0]['content'] == service.SYSTEM_PROMPT for case in CASES if case['node'] == node for c in case['calls']))
        observation[node] = {'source': str(Path(prompt.__file__).relative_to(ROOT)), 'prompt_version': prompt.PROMPT_VERSION,
            'system_utf8_sha256': text_hash(service.SYSTEM_PROMPT), 'system_canonical_json_sha256': digest(service.SYSTEM_PROMPT),
            'system_characters': len(service.SYSTEM_PROMPT)}
    check('main app not imported (no default app/stores initialization)', 'app.main' not in sys.modules)
    baseline = json.loads(Path(__file__).with_name('audited-source.sha256.json').read_text())
    check('all 108 backend source files unchanged', all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == sha for p,sha in baseline.items()))
    summary = {'evidence_class': 'synthetic_local_transport_capture', 'external_calls': 0, 'sqlite_connections': 0,
        'scenario_count': len(CASES), 'outbound_request_count': sum(len(c['calls']) for c in CASES),
        'production_sources_modified': False, 'model_name_is_only_request_config_not_real_model_execution': True,
        'observations': observation, 'checks': CHECKS,
        'cases': [{k:v for k,v in c.items() if k != 'calls'} | {'call_count': len(c['calls'])} for c in CASES]}
    (OUT/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'scenarios':len(CASES), 'requests': summary['outbound_request_count'],
        'checks_passed':len(CHECKS), 'external_calls':0, 'sqlite_connections':0}))


if __name__ == '__main__':
    with patch('sqlite3.connect', side_effect=AssertionError('Database connections forbidden in prompt-loading audit')):
        asyncio.run(main())
