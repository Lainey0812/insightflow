"""Response models for the evaluation discovery lists.

Fields the run or dataset did not record stay null. Counts come from the Phase 1 RunView.
The two relation counts are how a dataset is tied to a run: a verified hash match, or only
the configured run root (a weak path link).
"""
from typing import Literal

from pydantic import Field

from .contracts import IntegrityStatus, Record, RunStatus

RunType = Literal['golden', 'tc_regression']
DatasetType = Literal['golden', 'tc']
FreezeStatus = Literal['UNDECLARED']


class DiscoveryWarningModel(Record):
    code: str
    root_id: str | None = None
    entry: str | None = None
    detail: str | None = None


class RunListItem(Record):
    run_id: str
    run_type: RunType
    created_at: str | None
    lifecycle_status: RunStatus
    integrity_status: IntegrityStatus | None
    agent_id: str | None
    agent_version: str | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_hash: str | None
    case_count: int
    evaluated_case_count: int


class RunListPage(Record):
    items: list[RunListItem]
    total: int
    page: int
    page_size: int
    discovery_warnings: list[DiscoveryWarningModel]


class DatasetListItem(Record):
    dataset_id: str
    dataset_version: str | None
    dataset_hash: str
    dataset_type: DatasetType
    case_count: int
    source: str
    freeze_status: FreezeStatus
    related_run_count: int
    hash_matched_run_count: int
    weak_path_run_count: int


class DatasetListPage(Record):
    items: list[DatasetListItem]
    total: int
    page: int
    page_size: int
    discovery_warnings: list[DiscoveryWarningModel] = Field(default_factory=list)
