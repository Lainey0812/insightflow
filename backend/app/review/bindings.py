"""Bounded vocabulary bindings backed by dataset metadata, not a general NLU layer.

Business entity counts mean uploaded records, never distinct real-world entities.
Exact column names take precedence; ambiguous quantity columns remain unresolved.
"""
import re


RECORD_ENTITIES = {
    '订单': {'订单编号', '订单ID', '订单号'},
    '岗位': {'岗位名称', '岗位编号', '职位名称', '职位编号'},
    '工单': {'工单编号', '工单ID', '工单号'},
    '任务': {'任务编号', '任务ID', '任务号'},
}


def record_count(text, profile, entity_context=""):
    names = [n for field in profile.fields for n in {field.original_name, field.display_name} if n]
    if text in names:
        return False  # A source column named “订单数量” is not a row-count alias.
    for entity, identifiers in RECORD_ENTITIES.items():
        if text in {entity + '数量', entity + '数', entity + '记录数', entity + '记录数量'}:
            # A quantity column would create a sum-vs-count ambiguity.
            if any(name in {entity + '数量', entity + '数', entity + '总数'} for name in names):
                return False
            return any(name in identifiers for name in names) or entity in entity_context
    return False


def goal_dimensions(goal, profile):
    """Recognize only explicit field-labelled grouping phrases, not business semantics.

    Count targets are often retained in business_goal rather than duplicated in
    constraints. Bind exact names there too; do not let a correct row count hide
    a different grouping. Unsupported prose remains outside this finite proof.
    """
    found = []
    owners = {}
    for field in profile.fields:
        for name in {field.original_name, field.display_name} - {None}:
            owners.setdefault(name, set()).add(field.field_id)
    for field in profile.fields:
        for name in {field.original_name, field.display_name} - {None}:
            explicit = r'(?:按照|按)' + re.escape(name) + r'(?:分组|汇总|统计|比较|计算)'
            categorical = r'(?:各|不同)' + re.escape(name) + r'(?:的)?(?:订单|岗位|工单|任务|销售额|平均|响应|记录|数量|已解决)'
            if re.search(explicit, goal) or re.search(categorical, goal):
                if len(owners[name]) != 1:
                    return None  # An explicit duplicated name is still ambiguous.
                found.append(field.field_id)
                break
    return found


def observed_binding(text, profile):
    """Return a unique exact categorical field/value-set binding, or None.

    Whole observed values are consumed before conjunctions. No substrings,
    fuzzy matches, truncated samples, unknown values or first-field selection.
    """
    matches = []
    for field in profile.fields:
        if field.logical_type != 'text':
            continue
        values = {s.value for s in field.samples if not s.truncated and isinstance(s.value, str)}
        expressions = {value: [value] for value in values}
        # Small bounded set of explicit entity suffixes; field names are exact.
        for value in values:
            for suffix in {field.display_name, '地区', '城市', '订单', '工单', '岗位', '任务', '项目'}:
                expressions.setdefault(value + suffix, [value])
        if text in expressions:
            matches.append((field.field_id, expressions[text]))
            continue
        parts = re.split(r'和|与|、', text)
        if 1 < len(parts) <= 20 and all(part in values for part in parts) and len(parts) == len(set(parts)):
            matches.append((field.field_id, parts))
    unique = {(field, tuple(values)): (field, values) for field, values in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None
