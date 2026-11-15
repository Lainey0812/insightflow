import hashlib
from dataclasses import dataclass

import pandas as pd

from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.profiling.parsers import parse_table
from app.profiling.versioning import dataset_version
from app.storage.dataset_repository import DatasetRepository
from app.storage.file_store import FileStore


@dataclass
class LoadedDataset:
    profile: DatasetProfile
    frame: pd.DataFrame


class DatasetLoader:
    def __init__(self, datasets: DatasetRepository, files: FileStore):
        self.datasets, self.files = datasets, files

    def load(self, dataset_id: str, version: str) -> LoadedDataset:
        profile = self.datasets.profile(dataset_id, version)
        file = self.datasets.file(dataset_id)
        content = self.files.read(file)
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash != profile.content_sha256:
            raise AppError("DATASET_INTEGRITY_ERROR", "源文件与该画像版本内容不一致。", 409)
        table = parse_table(content, file.extension, profile.options)
        if dataset_version(content_hash, table.file_format, table.options) != version:
            raise AppError("DATASET_VERSION_MISMATCH", "文件解析规则与指定数据集版本不一致。", 409)
        headers = [None if value is None or (isinstance(value, str) and not value.strip()) else str(value) for value in table.headers]
        if (len(table.rows) != profile.row_count or len(headers) != profile.column_count or
                headers != [field.original_name for field in profile.fields]):
            raise AppError("DATASET_STRUCTURE_MISMATCH", "指定画像的行列结构与实际解析结果不一致。", 409)
        return LoadedDataset(profile, pd.DataFrame(table.rows,
            columns=[field.field_id for field in profile.fields], dtype=object))
