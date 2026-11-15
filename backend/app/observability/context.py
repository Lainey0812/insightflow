"""Task-local observation only, with no scheduling or business state decisions."""
from contextvars import ContextVar
from contextlib import contextmanager

_trace = ContextVar('insightflow_observation_context', default=None)


def current_trace():
    return _trace.get()


@contextmanager
def bind_trace(trace):
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)
