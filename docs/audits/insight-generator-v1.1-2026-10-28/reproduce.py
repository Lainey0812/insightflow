"""Read-only audit of a saved real-model report. No network or production writes.

Run at repository root:
  .venv/bin/python docs/audits/insight-generator-v1.1-2026-10-28/reproduce.py
Synthetic guard probes below are diagnostic tests, not real LLM quality scores.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
from app.domain.analysis_report import AnalysisReport, InsightDraft
from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.execution import ApprovedExecutionSnapshot, ExecutionResultV1
from app.planning.capabilities import CapabilityRegistry
from app.reporting.contracts import prepare
from app.reporting.evidence import EvidenceBuilder
from app.reporting.fact_validation import materialize
from app.reporting.presentation import build_presentation
from app.reporting.prompt import PROMPT_VERSION, SYSTEM_PROMPT, request_schema


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


report_id = 'report_9bc9b4b0184f4d3084ede0fb806230d3'
db_path = ROOT / 'var/workflow-v1-e2e/insightflow.sqlite3'
with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
    db.execute('PRAGMA query_only = ON')
    raw_report, audit = db.execute('SELECT report,audit FROM analysis_reports WHERE id=?', (report_id,)).fetchone()
    report = AnalysisReport.model_validate_json(raw_report)
    approval_json, execution_json = db.execute('SELECT approval,result FROM executions WHERE id=?', (report.execution_id,)).fetchone()
    approved = ApprovedExecutionSnapshot.model_validate_json(approval_json)
    execution = ExecutionResultV1.model_validate_json(execution_json)
    profile_json, = db.execute('SELECT profile FROM dataset_profiles WHERE dataset_id=? AND dataset_version=?',
                              (report.dataset_id, report.dataset_version)).fetchone()
    profile = DatasetProfile.model_validate_json(profile_json)
    # Same full-result hydration as ExecutionRepository.complete, using read-only SQL.
    for task in execution.tasks:
        if task.result:
            columns, rows, count = db.execute('SELECT columns_json,rows_json,row_count FROM execution_results WHERE execution_id=? AND id=?',
                                              (execution.execution_id, task.result_id)).fetchone()
            task.result = type(task.result)(result_id=task.result_id, columns=json.loads(columns), rows=json.loads(rows),
                                           truncated=False, row_offset=0, total_result_rows=count)
    execution.result_view = 'complete'
    execution = ExecutionResultV1.model_validate(execution.model_dump())

checked, descriptions = prepare(approved.intent, approved.validated_plan, execution, profile, CapabilityRegistry())
tasks = {t.task_id: t for t in checked.plan.tasks}
evidence = EvidenceBuilder().build(execution, profile, descriptions)
evidence.sort(key=lambda e: (tasks[e.task_id].priority, e.evidence_id))
assert [e.model_dump() for e in evidence] == [e.model_dump() for e in report.evidence]
selected = []
for task in sorted(tasks.values(), key=lambda t: t.priority):
    candidates = [e for e in evidence if e.task_id == task.task_id]
    business = [e for e in candidates if e.evidence_type != 'coverage']
    selected.extend((business or candidates)[:20])
selected = selected[:80]
all_calls = json.loads((ROOT / 'docs/evaluations/report-workflow-v1/live-model-calls.json').read_text())
history = json.loads((ROOT / 'docs/evaluations/report-workflow-v1/historical-output-reevaluation.json').read_text())
historical = {r['call_index']: r for r in history['records']}
calls = []
matched = []
for index, call in enumerate(all_calls, 1):
    if call.get('purpose') != 'report_insights_v1':
        continue
    record = {'call_index_one_based': index, 'real_call_record': call,
              'historical_runtime': historical.get(index)}
    calls.append(record)
    payload = call['input'] if isinstance(call['input'], dict) else json.loads(call['input'])
    if payload.get('evidence') != [e.model_dump(mode='json') for e in selected]:
        continue
    try:
        insights = materialize(InsightDraft.model_validate_json(call['actual_output']), selected, tasks)
    except AppError:
        continue
    if [i.model_dump() for i in insights] == [i.model_dump() for i in report.insights]:
        matched.append((index, call, payload, insights))
assert len(matched) == 1, 'Exact report-to-real-call attribution must be unique'
index, call, payload, insights = matched[0]
assert call['is_mock'] is False and call['actual_model'] == 'qwen3.8-flash'
assert call['system_prompt'] == SYSTEM_PROMPT
assert call['response_schema'] == request_schema(selected)
assert call['prompt_sha256'] == hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
presentation = build_presentation(report, profile)
save('01-all-evidence.json', [e.model_dump(mode='json') for e in evidence])
save('02-actual-llm-input.json', payload)
(OUT / '03-actual-llm-output.json').write_text(call['actual_output'] + '\n')
save('04-materialized-insights.json', [i.model_dump(mode='json') for i in insights])
save('05-saved-analysis-report.json', report.model_dump(mode='json'))
save('06-rule-presentation.json', presentation.model_dump(mode='json'))
save('actual-response-schema.json', call['response_schema'])
(OUT / 'current-prompt.txt').write_text(SYSTEM_PROMPT)
save('historical-real-report-calls.json', calls)

# Controlled post-processing probes. Never submitted to an LLM or saved as reports.
base = json.loads(call['actual_output'])
multi = json.loads(call['actual_output'])
multi['insights'][0]['evidence_refs'] = ['E0002', 'E0003', 'E0007', 'E0008']
multi_result = materialize(InsightDraft.model_validate(multi), selected, tasks)[0]
assert (multi_result.fact, multi_result.finding) == (insights[0].fact, insights[0].finding)
probes = []
for name, text in [
    ('verified_number_still_rejected', '济南与南京相差1000，值得进一步核查。'),
    ('unsupported_profit_not_detected', '济南利润高于南京，可以增加投入。'),
    ('unsupported_cause_not_detected', '济南销售额源自当地促销补贴。'),
    ('unsupported_english_percentage_not_detected', 'The profit share is ninety percent.'),
    ('valid_caution_rejected', '销售额不能证明盈利能力。'),
]:
    candidate = json.loads(json.dumps(multi, ensure_ascii=False))
    candidate['insights'][0]['implication'] = text
    try:
        materialize(InsightDraft.model_validate(candidate), selected, tasks)
        probes.append({'case': name, 'text': text, 'accepted': True})
    except AppError as error:
        probes.append({'case': name, 'text': text, 'accepted': False, 'error': error.error.code})
assert [p['accepted'] for p in probes] == [False, True, True, True, False]
save('controlled-probes.json', {'notice': 'Synthetic diagnostic drafts; no real model calls or quality scores.',
    'multi_reference_does_not_change_fact_or_finding': True,
    'multi_reference_insight': multi_result.model_dump(mode='json'), 'guard_probes': probes})

sources = ['backend/app/services/analysis_report.py', 'backend/app/reporting/prompt.py',
    'backend/app/reporting/evidence.py', 'backend/app/reporting/fact_validation.py',
    'backend/app/reporting/presentation.py', 'backend/app/domain/analysis_report.py',
    'backend/app/workflow/reporting.py', 'backend/app/llm/compatible_provider.py',
    'frontend/src/reporting/ReportPage.tsx']
manifest = {}
for source in sources:
    content = (ROOT / source).read_bytes()
    manifest[source] = hashlib.sha256(content).hexdigest()
    target = OUT / 'frozen-source' / source
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
save('audit-trace.json', {
    'audit_date': '2026-10-28', 'mode': 'read_only_saved_real_call_replay_no_new_llm_calls',
    'report_id': report_id, 'execution_id': report.execution_id, 'database_report_audit': json.loads(audit),
    'prompt_version': PROMPT_VERSION, 'actual_model': call['actual_model'],
    'enable_thinking': call['enable_thinking'], 'is_mock': call['is_mock'],
    'matched_call_index_one_based': index, 'recorded_duration_seconds': call['duration_seconds'],
    'llm_temperature': 'not explicitly set by provider; server default not recorded',
    'original_evidence_count': len(evidence), 'llm_evidence_count': len(selected),
    'llm_evidence_ids': [e.evidence_id for e in selected], 'excluded_evidence_ids': [e.evidence_id for e in evidence if e not in selected],
    'request_max_insights': call['response_schema']['properties']['insights']['maxItems'],
    'local_schema_max_insights': InsightDraft.model_json_schema()['properties']['insights']['maxItems'],
    'raw_candidate_count': len(base['insights']), 'saved_insight_count': len(insights),
    'presentation_finding_count': len(presentation.findings),
    'presentation_evidence_ids': [e.evidence_id for e in presentation.evidence],
    'rebuild_matches_saved_evidence': True, 'replay_matches_saved_insights': True,
    'source_sha256': manifest,
})
print(json.dumps({'all_evidence': len(evidence), 'sent_evidence': len(selected), 'raw_insights': len(base['insights']),
    'saved_insights': len(insights), 'presentation_findings': len(presentation.findings),
    'exact_real_call_index': index, 'diagnostic_guard_outcomes': [p['accepted'] for p in probes]}, ensure_ascii=False))
