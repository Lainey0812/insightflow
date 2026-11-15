import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from app.domain.models import Provenance, WorkflowError
from app.domain.errors import AppError
from app.domain.node_contracts import NodeInput, NodeOutput

I = TypeVar("I")
O = TypeVar("O")


class Node(ABC, Generic[I, O]):
    name: str
    error_provenance = Provenance()

    @abstractmethod
    async def process(self, payload: I) -> O: ...

    async def run(self, request: NodeInput[I]) -> NodeOutput[O]:
        try:
            data = await self.process(request.payload)
            provenance = getattr(data, "provenance", Provenance())
            return NodeOutput(session_id=request.session_id, run_id=request.run_id,
                              node_name=self.name, status="success", data=data,
                              provenance=provenance)
        except AppError as exc:
            return NodeOutput(session_id=request.session_id, run_id=request.run_id,
                              node_name=self.name, status="error", provenance=self.error_provenance,
                              error=exc.error.model_copy(update={"node_name": self.name}))
        except Exception:
            logging.getLogger(__name__).exception("Node failed: %s", self.name)
            return NodeOutput(session_id=request.session_id, run_id=request.run_id,
                              node_name=self.name, status="error", provenance=self.error_provenance, error=WorkflowError(
                                  code="NODE_FAILED", message="分析节点执行失败。",
                                  node_name=self.name))
