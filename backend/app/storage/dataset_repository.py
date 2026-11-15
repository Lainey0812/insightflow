from contextlib import closing

from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.models import FileInfo
from .database import Database


class DatasetRepository:
    def __init__(self, database: Database):
        self.database = database
        with closing(database.connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, file_info TEXT NOT NULL)")
            conn.execute("""CREATE TABLE IF NOT EXISTS dataset_profiles (
                dataset_id TEXT NOT NULL, dataset_version TEXT NOT NULL, profile TEXT NOT NULL,
                PRIMARY KEY (dataset_id, dataset_version),
                FOREIGN KEY (dataset_id) REFERENCES datasets(id)
            )""")

    def save(self, file: FileInfo, profile: DatasetProfile) -> DatasetProfile:
        if file.id != profile.dataset_id or (file.content_sha256 and file.content_sha256 != profile.content_sha256):
            raise AppError("DATASET_REFERENCE_MISMATCH", "画像与源文件引用不一致。", 409)
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO datasets VALUES (?, ?)", (file.id, file.model_dump_json()))
            # A dataset version is immutable. Reads continue to validate the typed contract.
            conn.execute("INSERT OR IGNORE INTO dataset_profiles VALUES (?, ?, ?)",
                         (file.id, profile.dataset_version, profile.model_dump_json()))
            stored = conn.execute("SELECT profile FROM dataset_profiles WHERE dataset_id=? AND dataset_version=?",
                                  (file.id, profile.dataset_version)).fetchone()
            result = DatasetProfile.model_validate_json(stored["profile"])
            if result != profile:
                raise AppError("PROFILE_VERSION_CONFLICT", "该版本已存在不同的画像，不能覆盖历史结果。", 409)
            return result

    def file(self, dataset_id: str) -> FileInfo:
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT file_info FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            raise AppError("DATASET_NOT_FOUND", "数据集不存在。", 404)
        return FileInfo.model_validate_json(row["file_info"])

    def profile(self, dataset_id: str, version: str) -> DatasetProfile:
        with closing(self.database.connect()) as conn:
            row = conn.execute("SELECT profile FROM dataset_profiles WHERE dataset_id=? AND dataset_version=?",
                               (dataset_id, version)).fetchone()
        if not row:
            raise AppError("PROFILE_NOT_FOUND", "该数据集版本的画像不存在。", 404)
        return DatasetProfile.model_validate_json(row["profile"])
