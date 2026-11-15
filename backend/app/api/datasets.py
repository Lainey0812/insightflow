from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, UploadFile, Depends
from app.api.session_access import session_guard
from starlette.concurrency import run_in_threadpool

from app.domain.dataset_profile import DatasetProfile, ProfileOptions
from app.domain.errors import AppError
from app.services.data_profiler import DataProfilerService
from app.storage.dataset_repository import DatasetRepository
from app.storage.file_store import FileStore
from app.storage.session_repository import SessionRepository


def create_dataset_router(files: FileStore, datasets: DatasetRepository,
                          profiler: DataProfilerService, sessions: SessionRepository) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Data Profiler"], dependencies=[Depends(session_guard(sessions.database))])

    @router.post("/datasets", response_model=DatasetProfile, status_code=201)
    async def upload_dataset(file: Annotated[UploadFile, File()],
        header_row: Annotated[int, Form(ge=1, le=100_001)] = 1,
        sheet_name: Annotated[str | None, Form(min_length=1, max_length=31)] = None,
        encoding: Annotated[Literal["utf-8-sig", "gb18030"], Form()] = "utf-8-sig",
        delimiter: Annotated[Literal[",", ";", "\t", "|"], Form()] = ","):
        options = ProfileOptions(header_row=header_row, sheet_name=sheet_name, encoding=encoding, delimiter=delimiter)
        metadata = await files.save(file)
        try:
            return await run_in_threadpool(profiler.profile, metadata, options)
        except Exception:
            files.remove(metadata)
            raise

    @router.post("/datasets/{dataset_id}/profiles", response_model=DatasetProfile)
    def reprofile_dataset(dataset_id: str, options: ProfileOptions):
        return profiler.profile(datasets.file(dataset_id), options)

    @router.get("/datasets/{dataset_id}/versions/{version}/profile", response_model=DatasetProfile)
    def get_profile(dataset_id: str, version: str):
        return datasets.profile(dataset_id, version)

    @router.get("/sessions/{session_id}/profile", response_model=DatasetProfile)
    def get_session_profile(session_id: str):
        ref = sessions.get(session_id).dataset_ref
        if ref is None:
            raise AppError("REAL_PROFILE_NOT_AVAILABLE", "该会话没有真实数据画像；历史 Mock 画像不会作为真实结果返回。")
        return datasets.profile(ref.dataset_id, ref.dataset_version)

    return router
