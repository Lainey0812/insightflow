"""Run the five frozen fidelity cases with the real model and keep each node trace.

The golden set is not extended here. Results go to a new directory and do not overwrite older runs.
run-config.json is written before the first case and run-manifest.json after the last one.
"""
import ast
import csv
import hashlib
import os
import platform
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


def main():
    sys.path.insert(0, str(ROOT / 'backend'))
    load_environment()
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.evaluation.golden_fidelity import load_golden
    from app.evaluation.golden_run import run_golden
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
    model = {'name': settings.llm_model, 'endpoint_sha256': hashlib.sha256(settings.llm_base_url.encode()).hexdigest(),
             'timeout_seconds': settings.llm_timeout_seconds, 'intent_max_attempts': settings.intent_max_attempts,
             'planner_max_attempts': settings.planner_max_attempts, 'intent_enable_thinking': settings.intent_enable_thinking,
             'planner_enable_thinking': settings.planner_enable_thinking, 'report_enable_thinking': settings.report_enable_thinking}
    environment = {'source_fingerprint': source_fingerprint(ROOT), 'python': platform.python_version(), 'git': 'unknown'}
    app = create_app(settings, create_provider(settings))
    with TestClient(app) as client:
        def run_one(item):
            case = {'case_id': item['case_id'], 'dataset': 'jobs.csv', 'header_row': 1, 'user_query': item['user_input'], 'expected': {}}
            observed = run_case(client, app, case, suite_dir, run_id)
            trace = None
            if observed.get('workflow_id'):
                try:
                    trace = app.state.workflow_observability.get(observed['workflow_id'])
                except Exception as exc:
                    trace = {'trace_error': type(exc).__name__}
            return observed, trace

        def report(execution, results, e2e):
            oracle = next((r for r in results if r.required), None)
            print(f"{execution.case_id} execution={execution.execution_status or 'UNKNOWN'} "
                  f"oracle={oracle.verdict if oracle else '-'} e2e={e2e.verdict} ({e2e.reason})", flush=True)

        summary = run_golden(run_dir, document, raw, GOLD.relative_to(ROOT).as_posix(), run_one=run_one,
                             model=model, environment=environment, on_case=report)
    counts = summary['metrics']['counts']['e2e']
    print(f"{run_id}: E2E PASS {counts.get('PASS', 0)}/{len(summary['cases'])}，trace 在 {run_dir}")


if __name__ == '__main__':
    main()
