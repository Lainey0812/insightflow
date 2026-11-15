"""Independent Pandas verification of saved real browser executions.

Read-only: no database changes, no approval requests, no Engine kernels or LLM.
Run from any directory using the project's Python environment.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd


def main():
    directory = Path(__file__).resolve().parent
    root = directory.parents[2]
    settings = {
        'sales': ('订单日期', '订单状态', '已完成', '销售额', 'sum', False),
        'jobs': ('发布日期', '岗位状态', '在招', '招聘人数', 'sum', False),
        'tickets': ('创建日期', '工单状态', '已解决', '响应分钟', 'mean', True),
        'projects': ('开始日期', '任务状态', '已完成', '工时', 'sum', False),
    }
    comparisons = []
    for topic, (date_field, status_field, status, metric, function, ascending) in settings.items():
        record = json.loads((directory / (topic + '-browser.json')).read_text())
        path = root / 'examples/hitl-v2' / (topic + '.csv')
        frame = pd.read_csv(path)
        dates = pd.to_datetime(frame[date_field], errors='raise')
        selected = frame[(dates.dt.year == 2026) & (frame[status_field] == status)]
        if topic == 'sales':
            selected = selected[selected['地区'] == '华东']
        grouped = selected.groupby('城市')[metric].agg(function).sort_values(ascending=ascending).head(3)
        expected = [{'city': city, 'value': value.item() if hasattr(value, 'item') else value} for city, value in grouped.items()]
        assert len(record['executions']) == len(record['approvals']) == len(record['constraint_audits']) == 1
        execution = record['executions'][0]
        assert execution['source'] == 'engine' and execution['execution_status'] == 'success'
        assert record['approvals'][0]['snapshot']['constraints_confirmed']
        assert record['constraint_audits'][0]['audit']['all_verified']
        assert execution['approval_id'] == record['constraint_audits'][0]['approval_id']
        assert execution['plan_version'] == record['approvals'][0]['plan_version'] == 1
        table = execution['tasks'][0]['result']
        dimension = next(c['field'] for c in table['columns'] if c['role'] == 'dimension')
        numeric = next(c['field'] for c in table['columns'] if c['role'] == 'metric')
        actual = [{'city': row[dimension], 'value': row[numeric]} for row in table['rows']]
        assert actual == expected, (topic, actual, expected)
        comparisons.append({'topic': topic, 'source_file': str(path.relative_to(root)),
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'selected_rows': len(selected),
            'session_id': record['session']['id'], 'execution_id': execution['execution_id'],
            'expected': expected, 'actual': actual, 'matched': True})
    print(json.dumps({'all_matched': True, 'comparisons': comparisons}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
