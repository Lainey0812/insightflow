"""Display statuses for the trace dashboard. Stored records keep their original values."""
from app.domain.errors import AppError

DISPLAY_STATUSES = ('success', 'error', 'running', 'skipped', 'suspended')
STORED_GROUPS = {
    'success': ('complete',),
    'error': ('failed', 'partial', 'unavailable'),
    'running': ('running', 'queued'),
    'skipped': ('skipped',),
    'suspended': ('interrupted', 'waiting_input', 'waiting_approval'),
}
STORED_STATUSES = tuple(status for group in STORED_GROUPS.values() for status in group)


def stored_statuses(value):
    """Expand one dashboard status to the stored values it replaces. A legacy value stays exact."""
    if value in STORED_GROUPS:
        return STORED_GROUPS[value]
    if value in STORED_STATUSES:
        return (value,)
    raise AppError('TRACE_STATUS_UNKNOWN', '状态筛选只接受 success、error、running、skipped、suspended。', 422)
