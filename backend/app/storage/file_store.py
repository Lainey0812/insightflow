from pathlib import Path
import hashlib
import re

from fastapi import UploadFile

from app.domain.errors import AppError
from app.domain.models import FileInfo, uid


class FileStore:
    def __init__(self, directory: Path, max_bytes: int):
        self.directory = directory / "uploads"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    async def save(self, upload: UploadFile) -> FileInfo:
        name = (upload.filename or "").replace("\\", "/").split("/")[-1]
        extension = Path(name).suffix.lower()
        if extension not in {".csv", ".xlsx"}:
            raise AppError("UNSUPPORTED_FILE", "请选择 CSV 或 XLSX 文件；暂不支持 XLS。", 422)
        file_id = uid()
        path = self.directory / f"{file_id}{extension}"
        size = 0
        digest = hashlib.sha256()
        try:
            with path.open("xb") as target:
                while chunk := await upload.read(64 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise AppError("FILE_TOO_LARGE", "文件不能超过 10 MB。", 413)
                    target.write(chunk)
                    digest.update(chunk)
            if size == 0:
                raise AppError("EMPTY_FILE", "上传文件不能为空。", 422)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return FileInfo(id=file_id, name=name, size=size, extension=extension, content_sha256=digest.hexdigest())

    def read(self, file: FileInfo) -> bytes:
        if not re.fullmatch(r"[a-f0-9]{32}", file.id) or file.extension not in {".csv", ".xlsx"}:
            raise AppError("INVALID_FILE_REFERENCE", "文件引用无效。", 422)
        path = self.directory / f"{file.id}{file.extension}"
        try:
            with path.open("rb") as source:
                content = source.read(self.max_bytes + 1)
        except FileNotFoundError:
            raise AppError("SOURCE_FILE_NOT_FOUND", "数据集源文件不存在。", 404) from None
        if len(content) > self.max_bytes:
            raise AppError("FILE_TOO_LARGE", "文件不能超过 10 MB。", 413)
        if len(content) != file.size or (file.content_sha256 and hashlib.sha256(content).hexdigest() != file.content_sha256):
            raise AppError("DATASET_INTEGRITY_ERROR", "源文件内容已改变，请重新上传以创建新的数据集版本。", 409)
        return content

    def remove(self, file: FileInfo) -> None:
        (self.directory / f"{file.id}{file.extension}").unlink(missing_ok=True)
