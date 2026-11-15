"""Read-only registry of the Golden and TC datasets configured for evaluation discovery.

A dataset is whatever the configured source file says. The file hash is content_sha256 of those
bytes. It is not a dataset version. A version is returned only when the file itself records one.
Nothing here writes, and no dataset is created.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from .run_index import DiscoveryWarning

DatasetType = Literal['golden', 'tc']
FREEZE_STATUS = 'UNDECLARED'


@dataclass(frozen=True)
class DatasetSource:
    dataset_type: DatasetType
    path: Path
    source_ref: str
    paired_root_id: str


@dataclass(frozen=True)
class DiscoveredDataset:
    dataset_id: str
    dataset_version: str | None
    dataset_hash: str
    dataset_type: DatasetType
    case_count: int
    source: str
    freeze_status: Literal['UNDECLARED']
    paired_root_id: str


def repository_ref(path: Path, repo: Path, fallback: str) -> str:
    """A repository-relative ref when path stays inside repo. Never an absolute path."""
    try:
        resolved, root = path.resolve(), repo.resolve()
        if resolved == root or root in resolved.parents:
            return resolved.relative_to(root).as_posix()
    except OSError:
        pass
    return fallback if _relative_ref(fallback) else 'configured:dataset'


def _relative_ref(ref: str) -> bool:
    if not isinstance(ref, str) or not ref or ref.startswith(('/', '\\')) or '\\' in ref or '\x00' in ref:
        return False
    path = PurePosixPath(ref)
    return not path.is_absolute() and '..' not in path.parts


class DatasetRegistry:
    def __init__(self, sources: list[DatasetSource]):
        self.sources = list(sources)

    def load(self) -> tuple[list[DiscoveredDataset], list[DiscoveryWarning]]:
        warnings: list[DiscoveryWarning] = []
        found: list[DiscoveredDataset] = []
        for source in self.sources:
            dataset, source_warnings = _read_source(source)
            warnings.extend(source_warnings)
            if dataset is not None:
                found.append(dataset)
        by_key: dict[tuple[str, str], list[DiscoveredDataset]] = {}
        for dataset in found:
            by_key.setdefault((dataset.dataset_type, dataset.dataset_id), []).append(dataset)
        kept = []
        for key in sorted(by_key):
            copies = by_key[key]
            if len(copies) > 1:
                warnings.append(DiscoveryWarning(
                    'duplicate_dataset_id', None, f'{key[0]}:{key[1]}',
                    'More than one configured source has this dataset id; every copy is excluded.'))
                continue
            kept.append(copies[0])
        return kept, warnings


def _read_source(source: DatasetSource) -> tuple[DiscoveredDataset | None, list[DiscoveryWarning]]:
    def warn(code, detail):
        return [DiscoveryWarning(code, source.paired_root_id, source.dataset_type, detail)]

    if not _relative_ref(source.source_ref):
        return None, warn('dataset_source_ref_rejected', 'Dataset source ref must be a relative repository path.')
    path = source.path
    try:
        if not path.is_file():
            return None, warn('dataset_source_unreadable', 'Configured dataset file is missing or not a file.')
        data = path.read_bytes()
    except OSError:
        return None, warn('dataset_source_unreadable', 'Configured dataset file could not be read.')
    try:
        document = json.loads(data)
    except json.JSONDecodeError:
        return None, warn('dataset_json_corrupt', 'Dataset file is not valid JSON.')
    if not isinstance(document, dict):
        return None, warn('dataset_record_malformed', 'Dataset file is not a JSON object.')
    cases = document.get('cases')
    if not isinstance(cases, list):
        return None, warn('dataset_cases_missing', 'Dataset file has no cases list.')
    warnings = []
    if source.dataset_type == 'golden':
        dataset_id = document.get('set_id')
        recorded_version = document.get('version')
        dataset_version = recorded_version if isinstance(recorded_version, str) and recorded_version else None
        if dataset_version is None:
            warnings.append(DiscoveryWarning('dataset_version_not_recorded', source.paired_root_id, source.dataset_type,
                                             'Golden file has no version field. The file hash is not used as a version.'))
    else:
        dataset_id = document.get('suite_version')
        dataset_version = dataset_id if isinstance(dataset_id, str) and dataset_id else None
        if dataset_version is not None:
            warnings.append(DiscoveryWarning(
                'dataset_id_taken_from_suite_version', source.paired_root_id, source.dataset_type,
                'cases.json records suite_version. It is both the dataset id stored by TC runs and the only version field in the file. It is not a freeze declaration and it is not the file hash.'))
    if not isinstance(dataset_id, str) or not dataset_id:
        return None, warnings + warn('dataset_id_missing', 'Dataset file does not record an id.')
    declared = document.get('case_count')
    if isinstance(declared, int) and not isinstance(declared, bool) and declared != len(cases):
        warnings.append(DiscoveryWarning('declared_case_count_differs', source.paired_root_id, source.dataset_type,
                                         'The declared case_count differs from the number of cases. The case list length is used.'))
    dataset = DiscoveredDataset(
        dataset_id=dataset_id, dataset_version=dataset_version, dataset_hash=hashlib.sha256(data).hexdigest(),
        dataset_type=source.dataset_type, case_count=len(cases), source=source.source_ref,
        freeze_status=FREEZE_STATUS, paired_root_id=source.paired_root_id)
    return dataset, warnings
