"""Independent Gold-to-plan predicate audit for product evaluations.

Equal rows/results do not prove that redundant filter literals are faithful.
This verifier reads already frozen explicit constraints; it never extracts or
changes Intent, runs an Engine handler, or authorizes a production approval.
"""
import json


def atom(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def predicate_key(field, operator, value):
    # Engine eq/in(singleton), ne/not_in(singleton) share non-null semantics.
    if operator in {'in', 'not_in'} and isinstance(value, list):
        unique = sorted({atom(v) for v in value})
        if len(unique) == 1:
            return field, 'eq' if operator == 'in' else 'ne', unique[0]
        return field, operator, tuple(unique)
    return field, operator, atom(value)


def audit_scope(case, task, field_names):
    """Verify actual pre-aggregation filter literals against the frozen business Gold.

    Year permits the current supported complete-year range or extract_year+eq.
    This intentionally reports unknown encodings rather than claiming general
    symbolic equivalence. Scalar/list filters never use observed membership as
    proof of the literal values.
    """
    steps = task['steps']
    aggregates = [i for i, s in enumerate(steps) if s['operation'] in {'aggregate', 'group_aggregate'}]
    if len(aggregates) != 1:
        return {'passed': False, 'issues': ['AGGREGATION_SHAPE_UNSUPPORTED']}
    stop = aggregates[0]
    actual = [(i, c) for i, s in enumerate(steps[:stop]) if s['operation'] == 'filter' for c in s['params']['conditions']]
    allowed, issues = set(), []
    for label, operator, value in case.get('filters', []):
        field = field_names[label]
        if operator != 'year':
            key = predicate_key(field, operator, value)
            found = [i for i, (_, condition) in enumerate(actual)
                     if predicate_key(condition['field'], condition['operator'], condition['value']) == key]
        else:
            lower = predicate_key(field, 'gte', f'{value:04d}-01-01')
            upper = predicate_key(field, 'lt', f'{value+1:04d}-01-01')
            ranges = [[i for i, (_, c) in enumerate(actual) if predicate_key(c['field'], c['operator'], c['value']) == k]
                      for k in (lower, upper)]
            found = [i for group in ranges for i in group] if all(ranges) else []
            if not found:
                for derive_index, step in enumerate(steps[:stop]):
                    params = step['params']
                    if step['operation'] == 'derive' and params.get('function') == 'extract_year' and params.get('field') == field:
                        found.extend(i for i, (position, c) in enumerate(actual) if position > derive_index and
                            predicate_key(c['field'], c['operator'], c['value']) == predicate_key(params['alias'], 'eq', value))
        if not found:
            issues.append({'code': 'REQUIRED_PREDICATE_NOT_PROVED', 'gold': [label, operator, value]})
        allowed.update(found)
    for index, (_, condition) in enumerate(actual):
        if index not in allowed:
            issues.append({'code': 'UNREQUESTED_OR_WRONG_FILTER', 'actual': condition})
    return {'passed': not issues, 'issues': issues, 'basis': 'exact frozen predicate values, independent of returned row equality'}
