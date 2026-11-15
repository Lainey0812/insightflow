"""Versioned Constraint Coverage Mapping for Golden Set constraints.

The Golden Set file is not changed. Every entry pins one constraint sentence by dataset, case,
list (must_forbid or must_execute), index and the SHA-256 of its exact text, and records how it
is verified:

- ``ORACLE_COVERED``: an Oracle PASS strictly implies the constraint on this dataset. The proof
  depends on the dataset rows and the engine capability set, so both are pinned in
  ``coverage_basis``. It never yields PASS unless the Oracle itself passes on the same evidence.
- ``INDEPENDENT_CHECK``: a deterministic check over execution evidence (``check``).
- ``NON_ASSERTION``: explanatory text; it is listed but is not a gate.

An entry stops counting when its text hash, the version of the evaluator it relies on, the
dataset rows or the engine capability version no longer match. Sentences without an entry are
never treated as satisfied. Coverage was established in
docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/REVIEW.md and the decisions in
REQ-0145.
"""
import hashlib
import json

MAPPING_VERSION = 'golden-constraint-coverage-v1'
DATASET_ID = 'requirement-fidelity-golden-v1'
ORACLE_EVALUATOR = 'insightflow.golden.oracle'
CHECK_EVALUATOR = 'insightflow.golden.must_forbid'
ORACLE_VERSION = 'golden-oracle-v2'
CHECK_VERSION = 'must-forbid-v2'
ROWS_SHA256 = '68375f4025815b6e6fd08c85e03da657e4e8ec0f6ec150a1c37ce6d34a0b7986'
CAPABILITY_VERSION = '1.0'
REVIEW = 'docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/REVIEW.md'
ROW_ID = '编号'

INTERN_ROWS = ['J04', 'J06', 'J07', 'J09']
FULL_TIME_ROWS = ['J01', 'J02', 'J03', 'J05', 'J08']
TWO_CITY_INTERN_ROWS = ['J04', 'J06', 'J07']

# Why an Oracle PASS implies the sentence. Shared premises are listed in REVIEW.md section 1.
ORACLE_PREMISES = ['dataset rows pinned by rows_sha256',
                   'engine capability set pinned by capability_version: no join, row duplication or relabelling',
                   'no numeric or date columns, so every metric is count or distinct_count bounded by group size',
                   'every non-empty result table must equal the oracle mapping exactly',
                   'oracle city labels are unique in every result table (guard unique-oracle-labels)']


def rows_sha256(rows) -> str:
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _entry(case_id, field, index, text_sha256, mode, basis, check=None):
    covered_by, version = {'ORACLE_COVERED': (ORACLE_EVALUATOR, ORACLE_VERSION)}.get(mode, (CHECK_EVALUATOR, CHECK_VERSION))
    return {'dataset_id': DATASET_ID, 'case_id': case_id, 'constraint_field': field, 'constraint_index': index,
            'constraint_text_hash': text_sha256, 'verification_mode': mode, 'covered_by': covered_by,
            'evaluator_version': version, 'check': check,
            'coverage_basis': {'rows_sha256': ROWS_SHA256, 'capability_version': CAPABILITY_VERSION, 'review': REVIEW, **basis},
            'mapping_version': MAPPING_VERSION}


def _oracle(case_id, index, text_sha256, proof):
    return _entry(case_id, 'must_forbid', index, text_sha256, 'ORACLE_COVERED', {'premises': ORACLE_PREMISES, 'proof': proof})


def _forbid_rows(case_id, field, index, text_sha256, rows, failure_code, basis):
    return _entry(case_id, field, index, text_sha256, 'INDEPENDENT_CHECK', basis,
                  {'kind': 'row_set', 'row_id': ROW_ID, 'forbid_rows': rows, 'failure_code': failure_code})


def _salary(index, text_sha256, note):
    return _entry('RF-04', 'must_forbid', index, text_sha256, 'INDEPENDENT_CHECK', {'decision': 'REQ-0143', 'note': note},
                  {'kind': 'forbid_field', 'rule_id': 'forbid-salary-field'})


MAPPING = [
    _oracle('RF-01', 0, 'f1cbb084a2df906b328f303cfb085e2d04ae390c8f93f88701b8fb455971b3c1',
            'Keeping only interns leaves at most 1 上海 row, so 上海=3 is impossible.'),
    _oracle('RF-01', 1, 'c8b92c1d6f4b63d1efb8d81cdbc321604f26b42dd1c14edf846ed992d662033d',
            'Label set must be exactly {上海, 深圳}; no operation can move 北京 or 杭州 rows into those groups.'),
    _oracle('RF-01', 2, '309bf8b181081a4f95020c5b1a070f84d59bc941cf11ec4f1b9a5f9a155c2f4f',
            '上海 has 2 distinct 岗位名称, so any count deduplicated by name is at most 2.'),
    _oracle('RF-01', 3, '2d77aa99e38224d3fabdd56c0efdbcccd4ce835f14846f7c24dbdbd000f77dc9',
            'Every non-empty table must be the per-city mapping; a single total cannot match.'),
    _forbid_rows('RF-01', 'must_execute', 0, '1658e237c1f39851f16614a6c4f22d9a10a5bc9263b0d3afb1a181b163b05677',
                 INTERN_ROWS, 'F-EXCLUDE-DROPPED',
                 {'decision': 'REQ-0145 D1', 'rows': 'all rows with 岗位类型=实习',
                  'counterexample': '岗位名称 eq 产品经理 gives 上海 3 / 深圳 1 with intern J04 counted'}),
    _oracle('RF-02', 0, 'c57f0488e9a074e64fa1b7953c1e62da3a0eef1fe6deda8954372136248006f6',
            '上海=4 and 深圳=3 equal all rows of each city, so J04, J06 and J07 are counted; no proper subgroup reaches them.'),
    _oracle('RF-02', 1, '950adc605c108332d68dd87572883433ff04e62e763f4a33cf64694d2dd5efd5',
            'Keeping only interns leaves at most 1 上海 row, so 上海=4 is impossible.'),
    _oracle('RF-02', 2, '5c85af1dcdbb80be7f7fc054bf8f468582a8147e8f51558080d32c3b280be62c',
            'Label set must be exactly {上海, 深圳}, which must_execute names as the cities that must appear.'),
    _entry('RF-03', 'must_forbid', 0, 'c57f0488e9a074e64fa1b7953c1e62da3a0eef1fe6deda8954372136248006f6', 'INDEPENDENT_CHECK',
           {'decision': 'REQ-0145 D3 (row reading)', 'rows': 'rows of 上海 and 深圳 with 岗位类型=实习',
            'counterexample': '岗位名称 eq 分析师 drops intern J04 and still gives 上海 1 / 深圳 2'},
           {'kind': 'row_set', 'row_id': ROW_ID, 'require_rows': TWO_CITY_INTERN_ROWS, 'failure_code': 'F-EXTRA-CONSTRAINT'}),
    _forbid_rows('RF-03', 'must_forbid', 1, 'dcf9b41632aa02180c2218a80aedba41c91c9f56d7852244fe0c31da2748afee',
                 FULL_TIME_ROWS, 'F-EXCLUDE-DROPPED',
                 {'decision': 'REQ-0145 D1', 'rows': 'all rows with 岗位类型=正式',
                  'counterexample': '岗位名称 eq 分析师 gives 上海 1 / 深圳 2 with 正式 J03 counted'}),
    _salary(0, '26d1ab466f508f086b7f0a0ebb7bf025c743e80c829fc14754ae76a6a680a52b',
            'Reading, filtering, grouping or aggregating salary appears as a salary field reference in a step.'),
    _salary(1, 'd94ca76c2426a63298c86d05fb1097ecf20999a35442ec5919ce75d465e1e47d',
            'An invented salary field is matched by name even when the profile has no such field.'),
    _salary(2, '14683cd5f3712d1ec9b515cd186cf521c8a0e9377afe21f263c13663d26bd6e9',
            'Salary output appears as a salary result column or metric alias.'),
    _salary(3, '34653a2cb998205c85a4248cde06720050a956cbc254849a3c174b0eed07260a',
            'Any salary field use fails, even when the city counts are correct.'),
    _entry('RF-04', 'must_forbid', 4, '2851de5dcb5636fc450469a70667a3c47eebe8edb24724501d11a1211d66283a', 'NON_ASSERTION',
           {'decision': 'REQ-0143', 'note': 'Plan text is never scanned; only structured field references and result columns are matched.'}),
    _forbid_rows('RF-04', 'must_execute', 0, 'b7a623877fd7c868bf0d2160da2893c86fd2380187222f79a9a526c444d2767d',
                 INTERN_ROWS, 'F-EXCLUDE-DROPPED',
                 {'decision': 'REQ-0145 D1', 'rows': 'all rows with 岗位类型=实习',
                  'counterexample': '岗位名称 eq 产品经理 gives 上海 3 / 深圳 1 with intern J04 counted'}),
    _oracle('RF-05', 0, '9cf87f631a39d920830f5ae878dd119fe65776a93abf91d8ae7084f4aab870ec',
            'Label set must be exactly {深圳, 北京, 杭州}.'),
    _oracle('RF-05', 1, '00298fe2799d66bad7a4f2dce0465989f60c32c55909471b8968e0e5be80f46f',
            'Label set must be exactly {深圳, 北京, 杭州}.'),
    _oracle('RF-05', 2, '14399f53a5dbdcf01647b6678ec77e32322a6614a32636097ca9d2f55ccbab30',
            'Label set must be exactly {深圳, 北京, 杭州}.'),
    _oracle('RF-05', 3, 'c75e7064f99173cb73564f0b1b7aed6e66ddeb98b24d02ac4960f94c0cd4c89c',
            '深圳=3 needs all 深圳 rows including J06 and J07; 杭州=1 can only be intern J09.'),
]

# Applies to every case of the dataset that has an oracle (REQ-0145 D2).
GUARDS = {DATASET_ID: {'unique-oracle-labels': {
    'failure_code': 'F-ORACLE-MISS', 'decision': 'REQ-0145 D2',
    'rule': 'In every non-empty result table, no column may repeat an oracle label across rows.',
    'reason': 'find_mapping keeps the last row of a repeated label, so a table grouped by city and job type can match the oracle.'}}}


def mapping_sha256(mapping=MAPPING, guards=GUARDS) -> str:
    body = {'version': MAPPING_VERSION, 'mapping': mapping, 'guards': guards}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def text_sha256(text) -> str:
    return hashlib.sha256(str(text).encode()).hexdigest()


def resolve(case, dataset_id, rows, current_versions, capability_version, mapping=MAPPING):
    """Split a case's constraints into usable entries and reasons they cannot be used.

    Returns (entries, unadapted_refs, stale_reasons). Every must_forbid sentence is resolved;
    must_execute sentences only when the mapping has an entry for them.
    """
    table = {(e['constraint_field'], e['constraint_index']): e for e in mapping
             if e['dataset_id'] == dataset_id and e['case_id'] == case.get('case_id')}
    entries, unadapted, stale = [], [], []
    rows_digest = rows_sha256(rows) if isinstance(rows, list) and rows else None
    for field in ('must_forbid', 'must_execute'):
        for index, text in enumerate(case.get(field) or []):
            ref = f'case.{field}[{index}]'
            entry = table.get((field, index))
            if entry is None:
                if field == 'must_forbid':
                    unadapted.append(ref)
                continue
            why = [name for name, ok in (
                ('text_hash', entry['constraint_text_hash'] == text_sha256(text)),
                ('mapping_version', entry['mapping_version'] == MAPPING_VERSION),
                ('evaluator_version', current_versions.get(entry['covered_by']) == entry['evaluator_version']),
                ('capability_version', entry['coverage_basis'].get('capability_version') == capability_version),
                ('dataset_rows', rows_digest is None or entry['coverage_basis'].get('rows_sha256') == rows_digest)) if not ok]
            if why:
                stale.append(f'{ref}:{"+".join(why)}')
            else:
                entries.append((ref, entry))
    return entries, unadapted, stale
