"""Bounded evidence ordering, without an additional model call."""
def select_evidence(evidence, tasks):
    order = {'change_rate': 0, 'comparison': 1, 'difference': 2, 'ranking': 3,
             'metric': 4, 'proportion': 5, 'maximum': 6, 'minimum': 7, 'coverage': 8}
    selected = []
    for task in sorted(tasks.values(), key=lambda t: (t.priority, t.task_id)):
        candidates = [e for e in evidence if e.task_id == task.task_id]
        business = [e for e in candidates if e.evidence_type != 'coverage']
        candidates = sorted(business or candidates, key=lambda e: (order[e.evidence_type], e.evidence_id))
        fields = list(dict.fromkeys(e.result_field for e in candidates))
        buckets = {field: [e for e in candidates if e.result_field == field] for field in fields}
        bounded = []
        while len(bounded) < 20 and any(buckets.values()):
            for field in fields:
                if buckets[field] and len(bounded) < 20:
                    bounded.append(buckets[field].pop(0))
        selected.append(bounded)
    result = []
    while len(result) < 80 and any(selected):
        for bucket in selected:
            if bucket and len(result) < 80:
                result.append(bucket.pop(0))
    return result
