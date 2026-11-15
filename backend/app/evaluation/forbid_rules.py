"""Executable forbid-field rules referenced by the Constraint Coverage Mapping.

Which Golden sentence uses which rule is recorded in constraint_coverage.MAPPING, pinned to the
sentence's text hash. This module only defines what a rule matches.
"""
import hashlib
import json

RULES_VERSION = 'golden-forbid-rules-v1'

# Identifiers are compared after normalize_identifier(). Only structured identifiers are
# matched (field references, metric aliases, result column names), never free text.
SALARY_FIELD = {
    'names': ['薪资', '薪资区间'],
    'aliases': ['salary', 'salary_range', '薪水', '工资'],
    # Aggregate output names such as 平均薪资, avg_salary or salary_median.
    'patterns': [r'^(平均|最高|最低|中位数|中位|总|avg|average|mean|max|min|median|sum|total)?'
                 r'(薪资|薪水|工资|salary)'
                 r'(区间|范围|均值|平均值|中位数|总额|总计|range|avg|average|mean|median|total|sum|max|min)?$'],
}

RULES = {
    'forbid-salary-field': {
        'kind': 'forbid_field',
        'match': SALARY_FIELD,
        'scopes': ['plan', 'engine', 'result_columns'],
        # Same code the legacy RF-04 check used for salary execution.
        'failure_code': 'F-METRIC-SUBSTITUTED',
    },
}


def rules_sha256(rules=RULES) -> str:
    body = {'version': RULES_VERSION, 'rules': rules}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
