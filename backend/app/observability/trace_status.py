"""Canonical trace statuses. Legacy values are accepted once, then replaced."""
from app.domain.errors import AppError

CANONICAL = ('success', 'error', 'running', 'skipped', 'suspended')
LEGACY = {
    'complete': 'success', 'succeeded': 'success',
    'failed': 'error', 'partial': 'error', 'unavailable': 'error',
    'queued': 'running',
    'interrupted': 'suspended', 'waiting_input': 'suspended',
    'waiting_approval': 'suspended', 'cancelled': 'suspended',
}


def normalize_status(value):
    if not isinstance(value, str):
        return value
    return LEGACY.get(value, value)


def stored_statuses(value):
    """One dashboard status matches itself and every legacy value it replaced."""
    canonical = normalize_status(value)
    if canonical not in CANONICAL:
        raise AppError('TRACE_STATUS_UNKNOWN', '状态筛选只接受 success、error、running、skipped、suspended。', 422)
    if value in LEGACY:
        return (value,)
    return tuple(dict.fromkeys((canonical, *(old for old, new in LEGACY.items() if new == canonical))))
