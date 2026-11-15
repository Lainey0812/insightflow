from typing import Any

from .models import WorkflowError


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, *, details: dict[str, Any] | None = None):
        self.error = WorkflowError(code=code, message=message, details=details or {})
        self.status = status
