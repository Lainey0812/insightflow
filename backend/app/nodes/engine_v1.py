from starlette.concurrency import run_in_threadpool

from app.domain.execution import ExecutionRequest, ExecutionResultV1
from app.domain.provenance import Provenance
from .base import Node


class AnalysisEngineNode(Node[ExecutionRequest,ExecutionResultV1]):
    name = "analysis_engine_v1"
    error_provenance = Provenance(source="uploaded",dataset="unavailable",notice="真实执行未完成。")

    def __init__(self,service): self.service = service

    async def process(self,payload: ExecutionRequest):
        return await run_in_threadpool(self.service.execute,payload)
