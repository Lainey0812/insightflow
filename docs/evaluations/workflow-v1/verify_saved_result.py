"""Recheck saved browser execution against independent Pandas on the CSV.

Run with the project's Python environment. This reads artifacts only; it does
not call the model, app, Engine kernels, approval API or database.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd


def main():
    directory = Path(__file__).resolve().parent
    root = directory.parents[2]
    verification = json.loads((directory / 'pandas-verification.json').read_text())
    source = root / verification['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == verification['file_sha256']
    frame = pd.read_csv(source)
    execution = json.loads((directory / 'execution-result.json').read_text())
    assert execution['source'] == 'engine' and execution['execution_status'] == 'success'
    actual = {task['task_id']: task['result']['rows'] for task in execution['tasks']}
    summary = [{'total_sales': int(frame['销售额'].sum()), 'avg_sales': float(frame['销售额'].mean()),
                'max_sales': int(frame['销售额'].max()), 'min_sales': int(frame['销售额'].min())}]
    regions = (frame.groupby('地区')['销售额'].agg(['sum', 'size'])
               .sort_values('sum', ascending=False))
    expected_regions = [{'field_0001': name, 'region_total_sales': int(row['sum']),
                         'region_record_count': int(row['size'])} for name, row in regions.iterrows()]
    assert actual['T1'] == summary
    assert actual['T2'] == expected_regions
    assert verification['approved_plan_version'] == execution['plan_version'] == 2
    print(json.dumps({'file_rows': len(frame), 'total_sales': summary[0]['total_sales'],
                      'execution_id': execution['execution_id'], 'all_matched': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
