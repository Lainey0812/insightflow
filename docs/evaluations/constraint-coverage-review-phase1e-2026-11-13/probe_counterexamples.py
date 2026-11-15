"""Phase 1-E Stage A read-only probe.

Runs concrete plans through the real Engine kernels (app.planning.operations)
on the Golden Set rows, then feeds the result tables to the real
GoldenOracleEvaluator. Nothing is written except stdout.

Usage: cd insightflow/backend && ../.venv/bin/python \
    ../docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/probe_counterexamples.py
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from app.domain.dataset_profile import LogicalType as L
from app.evaluation.evaluators import GoldenOracleEvaluator
from app.planning import operations as ops
from app.planning.params import FilterParams, GroupParams, SortParams

ROOT = Path(__file__).resolve().parents[3]
GOLD = ROOT / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'
TYPES = {name: L.TEXT for name in ('编号', '城市', '岗位名称', '岗位类型')}


def run(rows, steps):
    frame = pd.DataFrame(rows)
    for op, params in steps:
        frame = {'filter': lambda f: ops.filter_rows(f, FilterParams(**params), TYPES),
                 'group': lambda f: ops.group_aggregate(f, GroupParams(**params), TYPES),
                 'sort': lambda f: ops.sort_rows(f, SortParams(**params), TYPES)}[op](frame)
    return json.loads(frame.to_json(orient='records', force_ascii=False))


def cond(field, operator, value):
    return {'field': field, 'operator': operator, 'value': value}


TWO = cond('城市', 'in', ['上海', '深圳'])
COUNT = {'dimensions': ['城市'], 'metrics': [{'function': 'count', 'alias': '岗位数量'}]}
BY_TYPE = {'dimensions': ['城市', '岗位类型'], 'metrics': [{'function': 'count', 'alias': '岗位数量'}]}

PROBES = [
    ('RF-01', 'correct: 岗位类型 ne 实习', [('filter', {'conditions': [TWO, cond('岗位类型', 'ne', '实习')]}), ('group', COUNT)]),
    ('RF-01', 'wrong filter: 岗位名称 eq 产品经理 (keeps intern J04)',
     [('filter', {'conditions': [TWO, cond('岗位名称', 'eq', '产品经理')]}), ('group', COUNT)]),
    ('RF-01', 'no exclusion, group by 城市+岗位类型, sort 岗位类型 asc (duplicate city labels)',
     [('filter', {'conditions': [TWO]}), ('group', BY_TYPE), ('sort', {'field': '岗位类型', 'direction': 'asc'})]),
    ('RF-04', 'wrong filter: 岗位名称 eq 产品经理 (keeps intern J04)',
     [('filter', {'conditions': [TWO, cond('岗位名称', 'eq', '产品经理')]}), ('group', COUNT)]),
    ('RF-03', 'correct: 岗位类型 eq 实习', [('filter', {'conditions': [TWO, cond('岗位类型', 'eq', '实习')]}), ('group', COUNT)]),
    ('RF-03', 'wrong filter: 岗位名称 eq 分析师 (counts 正式 J03, drops intern J04)',
     [('filter', {'conditions': [TWO, cond('岗位名称', 'eq', '分析师')]}), ('group', COUNT)]),
    ('RF-03', 'no filter on type, group by 城市+岗位类型 (duplicate city labels, 正式 rows present)',
     [('filter', {'conditions': [TWO]}), ('group', BY_TYPE)]),
    ('RF-02', 'correct: no type filter', [('filter', {'conditions': [TWO]}), ('group', COUNT)]),
    ('RF-02', 'violation: 岗位类型 ne 实习', [('filter', {'conditions': [TWO, cond('岗位类型', 'ne', '实习')]}), ('group', COUNT)]),
    ('RF-02', 'violation: 岗位类型 eq 实习', [('filter', {'conditions': [TWO, cond('岗位类型', 'eq', '实习')]}), ('group', COUNT)]),
    ('RF-05', 'correct: 城市 ne 上海', [('filter', {'conditions': [cond('城市', 'ne', '上海')]}), ('group', COUNT)]),
    ('RF-05', 'equivalent whitelist: 城市 in 深圳/北京/杭州',
     [('filter', {'conditions': [cond('城市', 'in', ['深圳', '北京', '杭州'])]}), ('group', COUNT)]),
    ('RF-05', 'violation: also 岗位类型 ne 实习',
     [('filter', {'conditions': [cond('城市', 'ne', '上海'), cond('岗位类型', 'ne', '实习')]}), ('group', COUNT)]),
    ('RF-05', 'violation: by 城市+岗位类型 (duplicate city labels)',
     [('filter', {'conditions': [cond('城市', 'ne', '上海')]}), ('group', BY_TYPE)]),
]


def main():
    raw = GOLD.read_bytes()
    document = json.loads(raw)
    print('golden_sha256', hashlib.sha256(raw).hexdigest())
    cases = {case['case_id']: case for case in document['cases']}
    oracle = GoldenOracleEvaluator()
    for case_id, label, steps in PROBES:
        table = run(document['rows'], steps)
        evidence = SimpleNamespace(case=cases[case_id], refs={},
                                   artifacts={'engine_execution_status': 'success', 'result_tables': [table]})
        outcome = oracle.evaluate(evidence)
        print(json.dumps({'case': case_id, 'probe': label, 'oracle': outcome.verdict,
                          'code': outcome.failure_code, 'table': table}, ensure_ascii=False))


if __name__ == '__main__':
    main()
