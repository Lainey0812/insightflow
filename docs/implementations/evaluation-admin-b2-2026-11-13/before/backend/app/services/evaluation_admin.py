"""Read-only evaluation discovery: run list and dataset list.

Run content comes from runs.read_run. This service only filters, sorts, and pages.
It does not open SQLite and it does not return filesystem paths.
"""
import os
from typing import Literal

from app.domain.errors import AppError
from app.evaluation.admin_views import DatasetListItem, DatasetListPage, DatasetType, DiscoveryWarningModel, RunListItem, RunListPage, RunType
from app.evaluation.contracts import IntegrityStatus, RunStatus
from app.evaluation.datasets import DatasetRegistry, DiscoveredDataset
from app.evaluation.run_index import PREFIX_KIND, DiscoveryWarning, IndexedRun, RunIndex
from app.evaluation.runs import RunView, read_run

RunSort = Literal['created_at', '-created_at', 'run_id', '-run_id']
DatasetSort = Literal['dataset_id', '-dataset_id', 'case_count', '-case_count']


def build_evaluation_admin(roots, sources, golden_dataset_path=None) -> 'EvaluationAdminService':
    def reader(path):
        if golden_dataset_path is not None:
            return read_run(path, gold_path=golden_dataset_path)
        return read_run(path)
    return EvaluationAdminService(RunIndex(roots, reader=reader), DatasetRegistry(sources))


def _warning(item: DiscoveryWarning) -> DiscoveryWarningModel:
    return DiscoveryWarningModel(code=item.code, root_id=item.root_id, entry=item.entry, detail=item.detail)


def _page(items, page, page_size):
    start = (page - 1) * page_size
    return items[start:start + page_size]


def _counts(view: RunView) -> tuple[int, int]:
    run = view.run
    evaluated = {result.case_execution_ref for result in view.evaluator_results}
    return (len(view.executions) + len(run.missing_case_ids) + len(run.not_started_case_ids),
            sum(1 for execution in view.executions if execution.locator in evaluated))


def _run_item(indexed: IndexedRun) -> RunListItem:
    run = indexed.view.run
    case_count, evaluated = _counts(indexed.view)
    return RunListItem(
        run_id=run.run_id, run_type=indexed.run_type, created_at=run.created_at, lifecycle_status=run.status,
        integrity_status=run.integrity.status if run.integrity else None, agent_id=run.agent_id,
        agent_version=run.agent_version, dataset_id=run.dataset_id, dataset_version=run.dataset_version,
        dataset_hash=run.dataset_hash, case_count=case_count, evaluated_case_count=evaluated)


class _Reverse:
    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return self.value > other.value


def _run_key(item: RunListItem, sort: RunSort):
    if sort == 'run_id':
        return (item.run_id,)
    if sort == '-run_id':
        return (_Reverse(item.run_id),)
    # Missing timestamps sort last. Dated values stay in their own comparison type.
    missing = item.created_at is None
    if sort == 'created_at':
        return (missing, item.created_at or '', item.run_id)
    return (missing, _Reverse(item.created_at or ''), item.run_id)


def _dataset_key(item: DatasetListItem, sort: DatasetSort):
    locator = f'{item.dataset_type}:{item.dataset_id}'
    if sort == 'dataset_id':
        return (item.dataset_id, locator)
    if sort == '-dataset_id':
        return (_Reverse(item.dataset_id), locator)
    if sort == 'case_count':
        return (item.case_count, locator)
    return (_Reverse(item.case_count), locator)


class EvaluationAdminService:
    def __init__(self, index: RunIndex, datasets: DatasetRegistry):
        self.index = index
        self.datasets = datasets

    def _salt(self) -> tuple:
        salt = []
        for source in self.datasets.sources:
            try:
                stat = os.stat(source.path)
                salt.append((source.source_ref, stat.st_size, stat.st_mtime_ns))
            except OSError:
                salt.append((source.source_ref, None, None))
        return tuple(salt)

    def _scan(self):
        if not self.index.roots:
            raise AppError('EVALUATION_ROOTS_UNAVAILABLE', '没有配置可扫描的评测运行根目录。', 503)
        result = self.index.scan(self._salt())
        if not result.scanned_root_ids:
            raise AppError('EVALUATION_ROOTS_UNAVAILABLE', '配置的评测运行根目录都不可用。', 503)
        return result

    def list_runs(self, *, page: int, page_size: int, run_type: RunType | None, status: RunStatus | None,
                  integrity_status: IntegrityStatus | None, sort: RunSort) -> RunListPage:
        result = self._scan()
        items = [_run_item(indexed) for indexed in result.runs.values()]
        if run_type is not None:
            items = [item for item in items if item.run_type == run_type]
        if status is not None:
            items = [item for item in items if item.lifecycle_status == status]
        if integrity_status is not None:
            items = [item for item in items if item.integrity_status == integrity_status]
        items.sort(key=lambda item: _run_key(item, sort))
        return RunListPage(items=_page(items, page, page_size), total=len(items), page=page, page_size=page_size,
                           discovery_warnings=[_warning(item) for item in result.warnings])

    def list_datasets(self, *, page: int, page_size: int, dataset_type: DatasetType | None, sort: DatasetSort) -> DatasetListPage:
        if not self.datasets.sources:
            raise AppError('EVALUATION_DATASETS_UNAVAILABLE', '没有配置评测数据集来源。', 503)
        datasets, warnings = self.datasets.load()
        run_warnings: list[DiscoveryWarning] = []
        runs: dict[str, IndexedRun] = {}
        if self.index.roots:
            try:
                scanned = self._scan()
            except AppError:
                run_warnings = [DiscoveryWarning('run_roots_unavailable', None, None, 'Run roots could not be scanned. Related run counts are zero.')]
            else:
                runs = scanned.runs
                run_warnings = list(scanned.warnings)
        relations = [_relate(dataset, runs, run_warnings) for dataset in datasets]
        items = [item for item, _ in relations]
        warnings = warnings + run_warnings + [warning for _, extra in relations for warning in extra]
        if dataset_type is not None:
            items = [item for item in items if item.dataset_type == dataset_type]
        items.sort(key=lambda item: _dataset_key(item, sort))
        return DatasetListPage(items=_page(items, page, page_size), total=len(items), page=page, page_size=page_size,
                               discovery_warnings=[_warning(item) for item in warnings])


def _family(dataset: DiscoveredDataset, run: IndexedRun) -> bool:
    return PREFIX_KIND['gf' if dataset.dataset_type == 'golden' else 'rg'] == run.run_type


def _relate(dataset: DiscoveredDataset, runs: dict[str, IndexedRun], _run_warnings) -> tuple[DatasetListItem, list[DiscoveryWarning]]:
    hash_matched, weak = 0, 0
    warnings = []
    for run_id in sorted(runs):
        indexed = runs[run_id]
        if not _family(dataset, indexed):
            continue
        recorded = indexed.view.run
        same_root = indexed.root_id == dataset.paired_root_id
        id_conflict = recorded.dataset_id is not None and recorded.dataset_id != dataset.dataset_id
        hash_ok = recorded.dataset_hash is not None and recorded.dataset_hash == dataset.dataset_hash
        if hash_ok and not id_conflict:
            hash_matched += 1
            continue
        if hash_ok and id_conflict:
            warnings.append(DiscoveryWarning(
                'dataset_hash_id_conflict', indexed.root_id, run_id,
                'Dataset hash matches but the recorded dataset id does not. The run is not counted.'))
            continue
        if same_root and not id_conflict:
            weak += 1
    item = DatasetListItem(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, dataset_hash=dataset.dataset_hash,
        dataset_type=dataset.dataset_type, case_count=dataset.case_count, source=dataset.source,
        freeze_status=dataset.freeze_status, related_run_count=hash_matched + weak,
        hash_matched_run_count=hash_matched, weak_path_run_count=weak)
    return item, warnings
