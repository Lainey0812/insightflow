"""Which dataset rows reached aggregation, recovered by replaying the executed plan.

The engine records step names, statuses and row counts, but not which rows a filter kept.
For a small pinned dataset the answer is recomputed: every task the engine completed is
replayed with the same registered kernels on the dataset rows, and the row ids present at
its first aggregate/group_aggregate step are collected. Replayed row counts are compared
with the engine's step log, so a replay that diverges from the recorded execution is
reported instead of trusted.
"""
import pandas as pd

from app.domain.dataset_profile import LogicalType
from app.planning.capabilities import CapabilityRegistry

AGGREGATING = {'aggregate', 'group_aggregate'}


def _column_map(profile):
    fields = (profile or {}).get('fields') if isinstance(profile, dict) else None
    if not isinstance(fields, list) or not fields:
        return None, None
    columns, types = {}, {}
    for field in fields:
        if not isinstance(field, dict) or not field.get('field_id'):
            continue
        source = field.get('original_name') or field.get('display_name')
        if source:
            columns[source] = field['field_id']
        try:
            types[field['field_id']] = LogicalType(field.get('logical_type') or 'text')
        except ValueError:
            types[field['field_id']] = LogicalType.TEXT
    return columns, types


def aggregation_inputs(plan, profile, executed, rows, row_id, registry=None):
    """Return ({task_id: set(row ids)} for non-empty completed tasks, gaps).

    A gap names evidence that is missing or a replay that cannot be trusted; callers must not
    draw conclusions when gaps are present.
    """
    registry = registry or CapabilityRegistry()
    tasks = (plan or {}).get('tasks') if isinstance(plan, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return {}, ['plan']
    columns, types = _column_map(profile)
    if columns is None:
        return {}, ['profile']
    if row_id not in columns:
        return {}, [f'profile:no_field_for:{row_id}']
    if not isinstance(rows, list) or not rows:
        return {}, ['dataset_rows']
    if not isinstance(executed, list) or not executed:
        return {}, ['engine']
    log = {(entry.get('task_id'), entry.get('step_id')): entry for entry in executed if isinstance(entry, dict)}
    id_field = columns[row_id]
    base = pd.DataFrame(rows)[[c for c in columns if c in rows[0]]].rename(columns=columns).astype(object)
    inputs, gaps = {}, []
    for task in tasks:
        steps = task.get('steps') or []
        entries = [log.get((task.get('task_id'), step.get('step_id'))) for step in steps]
        if not steps or any(entry is None or entry.get('status') != 'success' for entry in entries):
            continue
        frame, reached = base.copy(), None
        for step, entry in zip(steps, entries):
            where = f"{task.get('task_id')}/{step.get('step_id')}"
            if step.get('operation') in AGGREGATING and reached is None:
                reached = set(frame[id_field])
            spec = registry.operations.get(step.get('operation'))
            if spec is None:
                gaps.append(f'replay_unsupported:{where}')
                break
            try:
                frame = spec.handler(frame, spec.params_model.model_validate(step.get('params') or {}), types)
            except Exception as exc:
                gaps.append(f'replay_error:{where}:{type(exc).__name__}')
                break
            logged = entry.get('output_row_count')
            if logged is not None and logged != len(frame):
                gaps.append(f'replay_mismatch:{where}')
                break
        else:
            if reached is None:
                reached = set(frame[id_field]) if id_field in frame else set()
            if len(frame):
                inputs[task.get('task_id')] = reached
    if not inputs and not gaps:
        gaps.append('engine:no_completed_task_with_rows')
    return inputs, gaps
