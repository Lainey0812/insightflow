from app.domain.dataset_profile import DatasetProfile, ProfileOptions
from app.domain.models import FileInfo
from app.profiling.profiler import build_profile
from app.storage.dataset_repository import DatasetRepository
from app.storage.file_store import FileStore


class DataProfilerService:
    """Application boundary shared by HTTP and the workflow node."""

    def __init__(self, files: FileStore, datasets: DatasetRepository):
        self.files = files
        self.datasets = datasets

    def profile(self, file: FileInfo, options: ProfileOptions | None = None) -> DatasetProfile:
        content = self.files.read(file)
        profile = build_profile(content, file.extension, file.id, file.name, options)
        return self.datasets.save(file, profile)
