import asyncio

from pydantic import BaseModel, Field

from app.domain.dataset_profile import DatasetProfile, ProfileOptions
from app.domain.models import FileInfo, Provenance
from app.services.data_profiler import DataProfilerService
from .base import Node


class ProfileInput(BaseModel):
    file: FileInfo
    options: ProfileOptions = Field(default_factory=ProfileOptions)


class DataProfilerNode(Node[ProfileInput, DatasetProfile]):
    name = "data_profiler"

    error_provenance = Provenance(source="uploaded", dataset="unavailable",
                                  notice="真实文件画像失败；未使用 Mock 画像替代。")

    def __init__(self, profiler: DataProfilerService):
        self.profiler = profiler

    async def process(self, payload: ProfileInput) -> DatasetProfile:
        # CPU / file work never blocks the event loop or the independent Intent Parser.
        return await asyncio.to_thread(self.profiler.profile, payload.file, payload.options)
