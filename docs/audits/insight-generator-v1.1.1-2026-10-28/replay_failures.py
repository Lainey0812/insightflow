"""Offline diagnostics of saved real V1.1 responses; never calls a model or modifies production.

Run from project root: .venv/bin/python docs/audits/insight-generator-v1.1.1-2026-10-28/replay_failures.py
Output is immutable; use a new directory for subsequent audits.
"""
import hashlib
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from app.domain.analysis_plan import ValidatedAnalysisPlan
from app.domain.analysis_report import Evidence, InsightDraft
from app.domain.execution import ExecutionResultV1
from app.domain.errors import AppError
from app.reporting import fact_validation as fv

DEST = Path(__file__).parent
SOURCE = ROOT / 'docs/evaluations/insight-generator-v1.1'
FAILED = {'O01', 'O02', 'R03', 'O03', 'H01', 'H02', 'H03'}


def save(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose_text(text, role, chosen, tasks, tables, limitations):
    captured = {}
    def trace(frame, event, arg):
        if frame.f_code is fv.validate_text.__code__ and event == 'exception':
            v = frame.f_locals
            if isinstance(arg[1], AppError):
                checked = v.get('checked', text)
                captured['normalized_checked_text'] = checked
                matches = []
                patterns = {key: getattr(fv, key) for key in
                            ['NUMERIC', 'UNSUPPORTED_ASSERTION', 'UNSUPPORTED_BUSINESS_CLAIM']}
                for key in ['english_number', 'causal', 'business', 'completed', 'threshold_claim']:
                    if v.get(key):
                        patterns[key] = v[key].re
                for key, pattern in patterns.items():
                    for match in pattern.finditer(checked):
                        matches.append({'rule': key, 'match': match.group(), 'span': list(match.span()),
                                        'pattern': pattern.pattern})
                captured['matches'] = matches
        return trace
    old = sys.gettrace()
    sys.settrace(trace)
    try:
        fv.validate_text(text, role, chosen, tasks, tables, limitations)
        captured['outcome'] = 'accepted'
    except AppError as exc:
        captured.update(outcome='rejected', error=exc.error.model_dump(mode='json'))
    finally:
        sys.settrace(old)
    return {'role': role, 'original_text': text, **captured}


def main():
    live = json.loads((SOURCE / 'final-live.json').read_text())
    frozen = {c['case_id']: c for c in json.loads((SOURCE / 'frozen-inputs-v2.json').read_text())}
    source_files = [*sorted((ROOT / 'backend/app/reporting').glob('*.py')),
                    ROOT / 'backend/app/services/analysis_report.py',
                    ROOT / 'frontend/src/reporting/ReportPage.tsx']
    manifest = {'mode': 'offline_saved_real_response_diagnostic_not_new_live_evaluation',
        'requirement': 'REQ-0040', 'model': live['model'], 'prompt_version': live['prompt_version'],
        'inputs_sha256': sha(SOURCE / 'frozen-inputs-v2.json'),
        'historical_files_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted(SOURCE.rglob('*')) if p.is_file()},
        'production_files_sha256': {str(p.relative_to(ROOT)): sha(p) for p in source_files},
        'production_matches_final_live': {p: sha(ROOT / p) == h for p, h in live['source_sha256'].items()},
        'validator_start_line': inspect.getsourcelines(fv.validate_text)[1], 'results': []}
    for rec in live['records']:
        if rec['case_id'] not in FAILED:
            continue
        cid = rec['case_id']
        dest = DEST / cid
        dest.mkdir(exist_ok=False)
        call = rec['calls'][0]
        payload = call['input']
        fixture = frozen[cid]
        plan = ValidatedAnalysisPlan.model_validate(fixture['input']['validated'])
        execution = ExecutionResultV1.model_validate(fixture['input']['execution'])
        tasks = {t.task_id: t for t in plan.plan.tasks}
        tables = {t.result.result_id: t.result for t in execution.tasks if t.status == 'success'}
        evidence = [Evidence.model_validate(e) for e in payload['evidence']]
        by_id = {e.evidence_id: e for e in evidence}
        draft = InsightDraft.model_validate_json(call['raw_output'])
        (dest / 'raw-output.txt').write_text(call['raw_output'], encoding='utf-8')
        save(dest / 'llm-input.json', payload)
        save(dest / 'frozen-input.json', fixture)
        diagnostic = {'case_id': cid, 'query': rec['query'], 'split': rec['split'],
            'historical_report_error': rec['error'], 'candidates': []}
        for pos, candidate in enumerate(draft.insights):
            chosen = [by_id[r] for r in candidate.evidence_refs]
            primary = by_id[candidate.primary_evidence_id]
            binding = lambda e: {'task_id': e.task_id, 'data_ref': e.data_ref,
                'result_field': e.result_field, 'source_scope': e.value.get('source_scope', e.scope)}
            c = {'candidate_number': pos + 1, 'raw_candidate': candidate.model_dump(mode='json'),
                'references': [{'evidence_id': e.evidence_id, 'binding': binding(e),
                    'matches_primary_binding': binding(e) == binding(primary),
                    'statement': e.statement, 'source_row_indices': e.source_row_indices,
                    'value': e.value} for e in chosen]}
            try:
                ins = fv.materialize(InsightDraft(insights=[candidate]), evidence, tasks, tables,
                                     require_core=False, trusted_limitations=payload['limitations'])
                c['actual_candidate_outcome'] = 'accepted'
                c['materialized'] = [i.model_dump(mode='json') for i in ins]
            except AppError as exc:
                c['actual_candidate_outcome'] = 'rejected'
                c['actual_first_error'] = exc.error.model_dump(mode='json')
            c['text_diagnostics'] = [diagnose_text(text, role, chosen, tasks, tables, payload['limitations'])
                for role, text in [('implication', candidate.implication),
                                   ('recommendation', candidate.recommendation),
                                   *[('limitation', v) for v in candidate.limitations]]]
            diagnostic['candidates'].append(c)
        try:
            accepted, rejected = fv.materialize_candidates(draft, evidence, tasks, tables, payload['limitations'])
            diagnostic['assembly_replay'] = {'status': 'accepted', 'accepted': len(accepted), 'rejected': rejected}
        except AppError as exc:
            diagnostic['assembly_replay'] = {'status': 'rejected', 'error': exc.error.model_dump(mode='json')}
        diagnostic['historical_error_reproduced'] = (diagnostic['assembly_replay'].get('error', {}).get('code') == rec['error']['code'])
        save(dest / 'diagnostics.json', diagnostic)
        manifest['results'].append({'case_id': cid, 'historical_error_reproduced': diagnostic['historical_error_reproduced'],
            'candidate_results': [{'number': c['candidate_number'], 'outcome': c['actual_candidate_outcome'],
                'first_error': c.get('actual_first_error', {}).get('code'),
                'text_matches': [{'role': d['role'], 'matches': [m['match'] for m in d.get('matches', [])]}
                    for d in c['text_diagnostics'] if d.get('matches')]} for c in diagnostic['candidates']]})
    save(DEST / 'replay-manifest.json', manifest)
    print(json.dumps(manifest['results'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
