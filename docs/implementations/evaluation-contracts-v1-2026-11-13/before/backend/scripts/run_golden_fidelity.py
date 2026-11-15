"""Run the five frozen fidelity cases with the real model and keep each node trace.

The golden set is not extended here. Results go to a new directory and do not overwrite older runs.
"""
import ast
import csv
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'
OUT = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs'


def load_environment():
    env = ROOT / 'backend/.env'
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:]
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            continue
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = ast.literal_eval(value)
        os.environ.setdefault(key.strip(), value)


def write_new(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)


def main():
    sys.path.insert(0, str(ROOT / 'backend'))
    load_environment()
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.evaluation.golden_fidelity import load_golden, score_case
    from app.llm.factory import create_provider
    from app.main import create_app
    from app.regression.runner import run_case, source_fingerprint

    document = load_golden(GOLD)
    raw = GOLD.read_bytes()
    now = datetime.now(timezone.utc)
    run_id = f"gf_{now:%Y%m%d-%H%M%S}_{secrets.token_hex(3)}"
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True)
    suite_dir = run_dir / 'input'
    suite_dir.mkdir()
    with (suite_dir / 'jobs.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=document['columns'])
        writer.writeheader()
        writer.writerows(document['rows'])
    settings = replace(Settings.from_env(), data_dir=run_dir / 'data', admin_read_token='', admin_local_test_mode=False,
                       admin_snapshot_token='', admin_annotation_token='')
    if not settings.llm_api_key or not settings.llm_model or not settings.llm_base_url:
        raise SystemExit('需要 backend/.env 里的真实模型配置。Golden Set 不使用 Mock。')
    app = create_app(settings, create_provider(settings))
    results = []
    with TestClient(app) as client:
        for item in document['cases']:
            case = {'case_id': item['case_id'], 'dataset': 'jobs.csv', 'header_row': 1, 'user_query': item['user_input'], 'expected': {}}
            observed = run_case(client, app, case, suite_dir, run_id)
            trace = None
            if observed.get('workflow_id'):
                try:
                    trace = app.state.workflow_observability.get(observed['workflow_id'])
                except Exception as exc:
                    trace = {'trace_error': type(exc).__name__}
            verdict = score_case(item, observed)
            case_dir = run_dir / item['case_id']
            write_new(case_dir / 'trace.json', trace or {'trace_error': 'no_workflow'})
            nodes = ((trace or {}).get('trace') or {}).get('nodes') or []
            record = {'case_id': item['case_id'], 'verdict': verdict, 'execution_status': observed.get('execution_status'),
                      'workflow_id': observed.get('workflow_id'), 'approved_by_runner': observed.get('approved_by_runner'),
                      'error_code': observed.get('error_code'), 'runner_error': observed.get('runner_error'),
                      'nodes': [{'name': node.get('name'), 'status': node.get('status'), 'span_id': node.get('span_id')} for node in nodes]}
            write_new(case_dir / 'result.json', record)
            results.append(record)
            print(f"{item['case_id']} {verdict['status']} {verdict['failure'] or '-'} nodes={len(nodes)}", flush=True)
    summary = {'schema_version': 'golden-fidelity-run-v1', 'run_id': run_id, 'started_at': now.isoformat(),
               'finished_at': datetime.now(timezone.utc).isoformat(), 'golden_sha256': hashlib.sha256(raw).hexdigest(),
               'source_fingerprint': source_fingerprint(ROOT), 'model': settings.llm_model,
               'passed': sum(item['verdict']['status'] == 'passed' for item in results), 'case_count': len(results),
               'approval_note': '计划可审批时由运行器代为批准，只为让引擎执行当前版本。', 'cases': results}
    write_new(run_dir / 'summary.json', summary)
    print(f"{run_id}: {summary['passed']}/{summary['case_count']} 通过，trace 在 {run_dir}")


if __name__ == '__main__':
    main()
