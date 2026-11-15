"""Versioned adaptation of natural-language must_forbid items into executable rules.

The Golden Set file is not changed. Each adapted item is pinned to its dataset, case, list
index and the SHA-256 of its exact text, so an edited sentence stops counting as adapted.

An item is adapted as either:
- ``rule``: it maps to an entry in RULES and is checked against execution evidence;
- ``clarification``: it explains how the rules are matched and forbids nothing by itself.

Items without an adaptation are not guessed at; the evaluator reports them as not adapted.
"""
import hashlib
import json

ADAPTER_VERSION = 'golden-forbid-adapter-v1'

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

ADAPTATIONS = {
    'requirement-fidelity-golden-v1': {
        'RF-04': [
            {'index': 0, 'text_sha256': '26d1ab466f508f086b7f0a0ebb7bf025c743e80c829fc14754ae76a6a680a52b',
             'disposition': 'rule', 'rule_id': 'forbid-salary-field',
             'note': 'Reading, filtering, grouping or aggregating salary appears as a salary field reference in a step.'},
            {'index': 1, 'text_sha256': 'd94ca76c2426a63298c86d05fb1097ecf20999a35442ec5919ce75d465e1e47d',
             'disposition': 'rule', 'rule_id': 'forbid-salary-field',
             'note': 'An invented salary field is matched by name even when the profile has no such field.'},
            {'index': 2, 'text_sha256': '14683cd5f3712d1ec9b515cd186cf521c8a0e9377afe21f263c13663d26bd6e9',
             'disposition': 'rule', 'rule_id': 'forbid-salary-field',
             'note': 'Salary output appears as a salary result column or metric alias.'},
            {'index': 3, 'text_sha256': '34653a2cb998205c85a4248cde06720050a956cbc254849a3c174b0eed07260a',
             'disposition': 'rule', 'rule_id': 'forbid-salary-field',
             'note': 'Any salary field use fails, even when the city counts are correct.'},
            {'index': 4, 'text_sha256': '2851de5dcb5636fc450469a70667a3c47eebe8edb24724501d11a1211d66283a',
             'disposition': 'clarification',
             'note': 'Plan text is never scanned; only structured field references and result columns are matched.'},
        ],
    },
}


def adapter_sha256(rules=RULES, adaptations=ADAPTATIONS) -> str:
    body = {'version': ADAPTER_VERSION, 'rules': rules, 'adaptations': adaptations}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
