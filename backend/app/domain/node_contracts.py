from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from .models import Provenance, WorkflowError, uid

T = TypeVar("T")


class NodeInput(BaseModel, Generic[T]):
    session_id: str
    run_id: str = Field(default_factory=uid)
    payload: T


class NodeOutput(BaseModel, Generic[T]):
    session_id: str
    run_id: str
    node_name: str
    status: Literal["success", "error"]
    data: T | None = None
    error: WorkflowError | None = None
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def check_outcome(self) -> "NodeOutput[T]":
        if self.status == "success" and (self.data is None or self.error is not None):
            raise ValueError("Successful nodes require data and no error")
        if self.status == "error" and (self.error is None or self.data is not None):
            raise ValueError("Failed nodes require an error and no data")
        return self
