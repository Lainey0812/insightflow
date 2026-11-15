"""Batch regression of the typical suite with the configured real LLM, in isolated storage under var/regression.

Usage (from the project root):
    .venv/bin/python backend/scripts/run_regression.py --label "baseline"
    .venv/bin/python backend/scripts/run_regression.py --label "planner prompt v1.3" --cases TC01 TC08

Each run gets a new directory var/regression/runs/<run_id>/ with its own Business DB, Trace DB and Prompt Registry.
Existing runs are never overwritten. Plans that can be approved are approved by the runner and marked as such.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'docs/testing/typical-suite-v1-2026-11-09'


def load_environment():
    env = ROOT / 'backend/.env'
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
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
        os.environ.setdefault(key.strip(), value)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--label', required=True, help='本次运行的说明，例如改了哪个 Prompt 或代码')
    parser.add_argument('--cases', nargs='*', help='只跑指定用例，默认 TC01–TC12')
    parser.add_argument('--suite', default=str(SUITE))
    args = parser.parse_args()
    if not 1 <= len(args.label.strip()) <= 120:
        parser.error('--label 需要 1–120 个字符')

    sys.path.insert(0, str(ROOT / 'backend'))
    load_environment()
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.llm.factory import create_provider
    from app.main import create_app
    from app.regression.runner import evaluate, source_fingerprint, summarize, write_new
    from app.regression.scoring import AUTO_CASES

    suite_dir = Path(args.suite).resolve()
    cases_raw = (suite_dir / 'cases.json').read_bytes()
    suite = json.loads(cases_raw)
    selected = tuple(args.cases) if args.cases else AUTO_CASES
    unknown = [c for c in selected if c not in AUTO_CASES]
    if unknown:
        parser.error('只能自动运行 TC01–TC12：' + ', '.join(unknown))

    now = datetime.now(timezone.utc)
    run_id = f"rg_{now:%Y%m%d-%H%M%S}_{secrets.token_hex(3)}"
    run_dir = Settings.from_env().data_dir / 'regression' / 'runs' / run_id
    (run_dir / 'cases').mkdir(parents=True, exist_ok=False)
    settings = replace(Settings.from_env(), data_dir=run_dir / 'data', admin_read_token='', admin_local_test_mode=False,
                       admin_snapshot_token='', admin_annotation_token='')
    if not settings.llm_api_key or not settings.llm_model or not settings.llm_base_url:
        raise SystemExit('需要在 backend/.env 配置真实模型（INSIGHTFLOW_LLM_BASE_URL / MODEL / API_KEY）；回归不使用 Mock。')
    provider = create_provider(settings)

    start = {'schema_version': 'regression-run-v1', 'run_id': run_id, 'label': args.label.strip(), 'started_at': now.isoformat(),
             'suite': {'version': suite['suite_version'], 'path': str(suite_dir.relative_to(ROOT)), 'cases_sha256': hashlib.sha256(cases_raw).hexdigest()},
             'selected_cases': list(selected),
             'environment': {'model': settings.llm_model, 'timeout_seconds': settings.llm_timeout_seconds,
                             'intent_max_attempts': settings.intent_max_attempts, 'planner_max_attempts': settings.planner_max_attempts,
                             'intent_enable_thinking': settings.intent_enable_thinking, 'planner_enable_thinking': settings.planner_enable_thinking,
                             'report_enable_thinking': settings.report_enable_thinking,
                             'endpoint_sha256': hashlib.sha256(settings.llm_base_url.encode()).hexdigest()},
             'source_fingerprint': source_fingerprint(ROOT), 'git': 'unknown',
             'approval_policy': '计划可审批时由回归运行器代为批准；TC08、TC11 期望在规划阶段阻断，不批准。'}
    write_new(run_dir / 'run-start.json', start)

    def saved(result):
        write_new(run_dir / 'cases' / f"{result['case_id']}.json", result)
        print(f"{result['case_id']} {result['status']:<12} {sum(c['status'] == 'pass' for c in result['checks'])}/{len(result['checks'])} 项通过", flush=True)

    app = create_app(settings, provider)
    with TestClient(app) as client:
        results = evaluate(client, app, suite['cases'], suite_dir, run_id, selected, saved)
    finished = datetime.now(timezone.utc)
    write_new(run_dir / 'run.json', {**start, 'finished_at': finished.isoformat(), 'summary': summarize(results), 'cases': results})
    summary = summarize(results)
    print(f"\n{run_id}: {summary['passed']}/{summary['auto_total']} 通过，{summary['llm_calls']} 次模型调用，结果在 {run_dir}")


if __name__ == '__main__':
    main()
