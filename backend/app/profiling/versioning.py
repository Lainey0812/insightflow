"""Shared, unchanged table-v2 dataset identity used by profiling and loading."""
import hashlib
import json

from app.domain.dataset_profile import ProfileOptions


def dataset_version(content_sha256: str, file_format: str, options: ProfileOptions) -> str:
    payload = {"content_sha256": content_sha256, "format": file_format,
               "parsing_contract": "table-v2", "options": options.model_dump()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()
