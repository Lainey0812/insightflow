from typing import Literal

from pydantic import BaseModel


class Provenance(BaseModel):
    source: Literal["mock", "uploaded", "llm", "input_guard"] = "mock"
    dataset: str = "insightflow-demo-v1"
    dataset_version: str | None = None
    plan_version: int | None = None
    notice: str = "Mock 示例，非上传文件分析结果"
