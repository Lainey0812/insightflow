"""Score the five-case fidelity golden set from saved results. No model calls and no plan repair."""
import json
from pathlib import Path

from app.regression.scoring import find_mapping

GOLD_PATH = Path(__file__).resolve().parents[3] / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'
SCORER_VERSION = 'requirement-fidelity-golden-v1'


def load_golden(path=GOLD_PATH):
    document = json.loads(Path(path).read_text())
    if document.get('case_count') != 5 or len(document.get('rows') or []) != 9 or len(document.get('cases') or []) != 5:
        raise ValueError('Golden set must stay at 5 cases and 9 rows')
    return document


def _texts_and_numbers(tables):
    texts, numbers = [], []
    for table in tables or []:
        for row in table or []:
            cells = row.values() if isinstance(row, dict) else row if isinstance(row, list) else []
            for value in cells:
                if isinstance(value, bool) or value is None:
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    texts.append(str(value).strip())
                    continue
                if number == float('inf') or number != number:
                    continue
                numbers.append(number)
    return texts, numbers


def salary_executed(tasks, fields, tables):
    """A prohibition sentence is not salary execution. A salary field or result column is."""
    names = {field.get('field_id'): field.get('display_name') or '' for field in fields or []}
    for table in tables or []:
        for row in table or []:
            keys = row.keys() if isinstance(row, dict) else []
            if any('薪资' in str(key) for key in keys):
                return True
    for task in tasks or []:
        for step in task.get('steps') or []:
            params = step.get('params') or {}
            identifiers = [params.get('field'), *(params.get('dimensions') or [])]
            identifiers += [item.get('field') for item in params.get('conditions') or [] if isinstance(item, dict)]
            identifiers += [item.get('field') for item in params.get('metrics') or [] if isinstance(item, dict)]
            if any(identifier and '薪资' in names.get(identifier, '') for identifier in identifiers):
                return True
    return False


def _matches(tables, expected):
    if find_mapping(tables, {str(key): value for key, value in expected.items()}, exact=True)[0]:
        return True
    if len(expected) != 1:
        return False
    target = float(next(iter(expected.values())))
    texts, numbers = _texts_and_numbers(tables)
    cities = {'上海', '深圳', '北京', '杭州'}
    return numbers == [target] and not cities.intersection(texts)


def _exact_oracle(tables, expected):
    nonempty = [table for table in tables or [] if table]
    wanted = {str(key): value for key, value in expected.items()}
    return bool(nonempty) and all(find_mapping([table], wanted, exact=True)[0] for table in nonempty)


def score_case(case, observed):
    tables = observed.get('result_tables') or []
    tasks = ((observed.get('plan') or {}).get('tasks') or [])
    fields = ((observed.get('profile') or {}).get('fields') or [])
    if case['case_id'] == 'RF-04' and salary_executed(tasks, fields, tables):
        return {'status': 'failed', 'failure': 'F-METRIC-SUBSTITUTED', 'reason': 'salary_executed'}
    if observed.get('execution_status') != 'success' or not any(tables):
        return {'status': 'failed', 'failure': 'F-GOAL-SUBSTITUTED', 'reason': 'no_execution_result'}
    if _exact_oracle(tables, case['oracle']):
        return {'status': 'passed', 'failure': None, 'reason': 'oracle_match'}
    for control in case.get('error_controls') or []:
        if _matches(tables, control['result']):
            return {'status': 'failed', 'failure': control['code'], 'reason': control['label']}
    return {'status': 'failed', 'failure': 'F-ORACLE-MISS', 'reason': 'no_control_matched'}
