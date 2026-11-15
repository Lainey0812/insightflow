"""Replay open or confirmed Bad Cases with the configured real LLM, in isolated storage under var/replay.

Usage (from the project root):
    .venv/bin/python backend/scripts/run_bad_case_replay.py --label "修了事实校验之后"
    .venv/bin/python backend/scripts/run_bad_case_replay.py --label "只看这一条" --cases bc_0123456789abcdef0123456789abcdef

Each run gets a new directory var/replay/runs/<run_id>/ with its own Business DB, Trace DB and Prompt Registry.
The original session and file are read from the daily data directory and are not modified. Existing runs are never overwritten.
Plans that can be approved are approved by the runner and marked as such. The page does not start a run.
"""
import argparse
import ast
import hashlib
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
    parser.add_argument('--label', required=True, help='这次回放的说明，例如改了哪个 Prompt 或代码')
    parser.add_argument('--cases', nargs='*', help='指定 Bad Case 编号；默认只跑待确认和已确认')
    args = parser.parse_args()
    if not 1 <= len(args.label.strip()) <= 120:
        parser.error('--label 需要 1–120 个字符')

    sys.path.insert(0, str(ROOT / 'backend'))
    load_environment()
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.llm.compatible_provider import CompatibleLLMProvider
    from app.main import create_app
    from app.regression.runner import source_fingerprint, write_new
    from app.replay.judge import NOTICE
    from app.replay.runner import replay, summarize
    from app.replay.source import CASE_ID, load_cases, prepare

    selected = tuple(args.cases or ())
    unknown = [item for item in selected if not CASE_ID.fullmatch(item)]
    if unknown:
        parser.error('Bad Case 编号格式应为 bc_ 加 32 位小写十六进制：' + ', '.join(unknown))
    daily = Settings.from_env()
    if not daily.llm_api_key or not daily.llm_model or not daily.llm_base_url:
        raise SystemExit('需要在 backend/.env 配置真实模型（INSIGHTFLOW_LLM_BASE_URL / MODEL / API_KEY）；回放不使用 Mock。')
    found = load_cases(daily.data_dir)
    if selected:
        by_id = {case['case_id']: (case, latest) for case, latest in found}
        missing = [item for item in selected if item not in by_id]
        if missing:
            raise SystemExit('日常库没有这些 Bad Case：' + ', '.join(missing))
        chosen = [by_id[item] for item in selected]
    else:
        chosen = [(case, latest) for case, latest in found if latest.get('status') in {'open', 'confirmed'}]
    if not chosen:
        raise SystemExit('没有待确认或已确认的 Bad Case。可用 --cases 指定一条，包括已修复的。')

    now = datetime.now(timezone.utc)
    run_id = f"rp_{now:%Y%m%d-%H%M%S}_{secrets.token_hex(3)}"
    run_dir = daily.data_dir / 'replay' / 'runs' / run_id
    (run_dir / 'cases').mkdir(parents=True, exist_ok=False)
    settings = replace(daily, data_dir=run_dir / 'data', admin_read_token='', admin_local_test_mode=False,
                       admin_snapshot_token='', admin_annotation_token='')
    provider = CompatibleLLMProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.llm_timeout_seconds)
    prepared = [prepare(daily.data_dir, case, latest, forced=bool(selected)) for case, latest in chosen]
    start = {'schema_version': 'replay-run-v1', 'run_id': run_id, 'label': args.label.strip(), 'started_at': now.isoformat(),
             'selected_cases': [item['case_id'] for item in prepared],
             'environment': {'model': settings.llm_model, 'timeout_seconds': settings.llm_timeout_seconds,
                             'intent_max_attempts': settings.intent_max_attempts, 'planner_max_attempts': settings.planner_max_attempts,
                             'intent_enable_thinking': settings.intent_enable_thinking, 'planner_enable_thinking': settings.planner_enable_thinking,
                             'report_enable_thinking': settings.report_enable_thinking,
                             'endpoint_sha256': hashlib.sha256(settings.llm_base_url.encode()).hexdigest()},
             'source_fingerprint': source_fingerprint(ROOT), 'git': 'unknown',
             'approval_policy': '计划可审批时由回放运行器代为批准。原会话和上传文件只读，不写回日常库。',
             'notice': NOTICE}
    write_new(run_dir / 'run-start.json', start)

    def saved(result):
        write_new(run_dir / 'cases' / f"{result['case_id']}.json", result)
        print(f"{result['case_id']} {result['outcome']:<14} {result.get('reason') or ''}", flush=True)

    runnable = [item for item in prepared if item.get('source')]
    app = create_app(settings, provider)
    with TestClient(app) as client:
        results = replay(client if runnable else None, app if runnable else None, prepared, run_id, saved)
    write_new(run_dir / 'run.json', {**start, 'finished_at': datetime.now(timezone.utc).isoformat(), 'summary': summarize(results), 'cases': results})
    summary = summarize(results)
    print(f"\n{run_id}: {summary['auto_total']} 条参与自动判断，{summary['cleared']} 条原问题未再出现，"
          f"{summary['source_missing']} 条缺少原会话或文件。结果在 {run_dir}")


if __name__ == '__main__':
    main()
