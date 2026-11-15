"""Phase 1-E Stage B acceptance: expected evaluation behaviour for RF-01..RF-05.

Plans are executed with the registered engine kernels on the Golden rows (helpers from
tests/test_evaluation_constraint_coverage.py), then judged by GoldenOracleEvaluator and
MustForbidEvaluator v2 and combined by the E2E hard gates. No LLM, no network, no writes.

Usage: cd insightflow/backend && ../.venv/bin/python \
    ../docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/stage-b/expected_behaviour.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'backend' / 'tests'))

from test_evaluation_constraint_coverage import (BY_CITY, BY_CITY_TYPE, CORRECT, FIELD, TWO_CITIES,  # noqa: E402
                                                 evidence, judge, run_plan, where)

from app.evaluation.constraint_coverage import MAPPING_VERSION, mapping_sha256  # noqa: E402
from app.evaluation.must_forbid import MustForbidEvaluator  # noqa: E402
from app.evaluation.protocol import config_hash  # noqa: E402

PROBES = [
    *[(case_id, 'correct plan', steps) for case_id, steps in CORRECT.items()],
    ('RF-01', 'wrong filter 岗位名称 eq 产品经理', [where(TWO_CITIES, ('岗位名称', 'eq', '产品经理')), BY_CITY]),
    ('RF-01', 'no exclusion, city+type groups sorted by type', [where(TWO_CITIES), BY_CITY_TYPE,
                                                               ('sort', {'field': FIELD['岗位类型'], 'direction': 'asc'})]),
    ('RF-01', 'polarity reversed', [where(TWO_CITIES, ('岗位类型', 'eq', '实习')), BY_CITY]),
    ('RF-02', 'still excludes interns', [where(TWO_CITIES, ('岗位类型', 'ne', '实习')), BY_CITY]),
    ('RF-03', 'wrong filter 岗位名称 eq 分析师', [where(TWO_CITIES, ('岗位名称', 'eq', '分析师')), BY_CITY]),
    ('RF-03', 'no type filter, city+type groups', [where(TWO_CITIES), BY_CITY_TYPE]),
    ('RF-04', 'wrong filter 岗位名称 eq 产品经理', [where(TWO_CITIES, ('岗位名称', 'eq', '产品经理')), BY_CITY]),
    ('RF-05', 'equivalent whitelist 城市 in 深圳/北京/杭州', [where(('城市', 'in', ['深圳', '北京', '杭州'])), BY_CITY]),
    ('RF-05', 'also excludes interns', [where(('城市', 'ne', '上海'), ('岗位类型', 'ne', '实习')), BY_CITY]),
]


def main():
    print(json.dumps({'mapping_version': MAPPING_VERSION, 'mapping_sha256': mapping_sha256(),
                      'must_forbid_config_sha256': config_hash(MustForbidEvaluator())}, ensure_ascii=False))
    for case_id, label, steps in PROBES:
        oracle, forbid, summary = judge(evidence(case_id, run_plan(steps)))
        print(json.dumps({'case': case_id, 'plan': label, 'oracle': [oracle.verdict, oracle.failure_code],
                          'must_forbid': [forbid.verdict, forbid.failure_code, forbid.reason],
                          'e2e': [summary.verdict, summary.gate]}, ensure_ascii=False))
    history = evidence('RF-02', {'plan': {}, 'profile': {}, 'execution_steps': None,
                                 'result_tables': [[{'城市': '上海', '岗位数量': 4}, {'城市': '深圳', '岗位数量': 3}]],
                                 'engine_execution_status': 'success'})
    oracle, forbid, summary = judge(history)
    print(json.dumps({'case': 'RF-02', 'plan': 'tables only (no plan/profile, like a historical run)',
                      'oracle': [oracle.verdict, oracle.failure_code], 'must_forbid': [forbid.verdict, forbid.failure_code, forbid.reason],
                      'e2e': [summary.verdict, summary.gate]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
