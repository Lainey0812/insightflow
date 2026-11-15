from app.domain.dataset_profile import DatasetProfile
from app.domain.errors import AppError
from app.domain.intent import ContextColumn, DatasetContext


def build_dataset_context(profile: DatasetProfile | None) -> DatasetContext:
    if not isinstance(profile, DatasetProfile):
        raise AppError("DATASET_CONTEXT_REQUIRED", "请先通过 Data Profiler 生成真实数据画像。", 422)
    context = DatasetContext(dataset_name=profile.file_name, row_count=profile.row_count, columns=[
        ContextColumn(field_id=field.field_id, name=field.display_name,
                      physical_type=field.physical_type, logical_type=field.logical_type)
        for field in profile.fields
    ])
    if len(context.model_dump_json().encode("utf-8")) > 64 * 1024:
        raise AppError("DATASET_CONTEXT_TOO_LARGE", "字段上下文超出 64 KB 上限，无法提交给模型。", 422)
    return context
