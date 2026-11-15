"""Read-only evaluation discovery, run and case detail, evidence, and dataset detail.

Runs are located only through the run index; request values never form a path. Run content comes
from runs.read_run and metrics from runs.trusted_metrics. This service filters, sorts, pages and
labels trust. It does not score, does not open SQLite, and does not return filesystem paths.
"""
import json
import os
from typing import Literal

from app.domain.errors import AppError
from app.evaluation import evidence as evidence_store
from app.evaluation.admin_views import (Attributed, Availability, CaseCounts, CaseDetail, CaseSummary, DatasetDetail,
                                        DatasetListItem, DatasetListPage, DatasetType, DiscoveryWarningModel, E2EView,
                                        EvaluatorHealth, EvaluatorManifestItem, EvaluatorResultView, EvaluatorSlot,
                                        EvidenceIndexItem, EvidenceIntegrityView, EvidenceLimits, EvidenceView, ExecutionView,
                                        FileCheckView, HashVariant, IntegrityView, Rate, RelatedRun, RunDetail, RunListItem,
                                        RunListPage, RunType, TrustedMetrics)
from app.evaluation.contracts import E2ESummary, IntegrityStatus, RunStatus
from app.evaluation.datasets import DatasetRegistry, DiscoveredDataset
from app.evaluation.evaluators import GoldenOracleEvaluator, RequirementFidelityNodeEvaluator
from app.evaluation.must_forbid import MustForbidEvaluator
from app.evaluation.run_index import PREFIX_KIND, DiscoveryWarning, IndexedRun, RunIndex
from app.evaluation.runs import GOLDEN_LEGACY_EVALUATOR, TC_LEGACY_EVALUATOR, RunView, read_run, trusted_metrics

RunSort = Literal['created_at', '-created_at', 'run_id', '-run_id']
DatasetSort = Literal['dataset_id', '-dataset_id', 'case_count', '-case_count']
RUN_ID_PATTERN = r'^(gf|rg)_\d{8}-\d{6}_[0-9a-f]{6}$'
CASE_ID_PATTERN = r'^[A-Za-z0-9_-]{1,40}$'
DATASET_ID_PATTERN = r'^[A-Za-z0-9._-]{1,80}$'
UNREADABLE_CODES = {'run_required_file_missing', 'run_json_corrupt', 'run_record_malformed', 'run_dir_unreadable',
                    'run_read_error', 'run_dir_too_many_entries'}
CONFLICT_CODES = {'duplicate_run_id', 'run_id_mismatch'}
ROLES = {GoldenOracleEvaluator.evaluator_id: 'oracle', MustForbidEvaluator.evaluator_id: 'must_forbid',
         RequirementFidelityNodeEvaluator.evaluator_id: 'node_fidelity', GOLDEN_LEGACY_EVALUATOR: 'legacy_oracle',
         TC_LEGACY_EVALUATOR: 'tc_checks'}
INTEGRITY_NOTICE = {
    'VERIFIED': 'Every file named in the final manifest exists inside the run and matches its recorded hash.',
    'INVALID': 'The final manifest does not match the files on disk. Only cases whose files verified are used for metrics.',
    'INCOMPLETE': 'The run has a config snapshot but no final manifest. It did not finish and cannot be verified.',
    'UNVERIFIED': 'Historical run format without a manifest. Records are shown as written; integrity cannot be verified.',
}
LEGACY_CASE_KEYS = ('verdict', 'status', 'checks', 'execution_status', 'final_status', 'business_status', 'error_code',
                    'approved_by_runner', 'runner_error', 'failure', 'nodes')
TEXT_LIMIT = 500
FREEZE_NOTICE = 'No formal freeze declaration exists. The file hash identifies content; it is not a dataset version.'


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


def _family(dataset: DiscoveredDataset, run: IndexedRun) -> bool:
    return PREFIX_KIND['gf' if dataset.dataset_type == 'golden' else 'rg'] == run.run_type


def _relation(dataset: DiscoveredDataset, indexed: IndexedRun):
    """hash_match, weak_path, hash_mismatch, 'id_conflict', or None when the run is unrelated."""
    if not _family(dataset, indexed):
        return None
    recorded = indexed.view.run
    same_root = indexed.root_id == dataset.paired_root_id
    id_conflict = recorded.dataset_id is not None and recorded.dataset_id != dataset.dataset_id
    if recorded.dataset_hash is not None and recorded.dataset_hash == dataset.dataset_hash:
        return 'id_conflict' if id_conflict else 'hash_match'
    if id_conflict:
        return None
    if recorded.dataset_hash is None:
        return 'weak_path' if same_root else None
    if recorded.dataset_id == dataset.dataset_id or same_root:
        return 'hash_mismatch'
    return None


def _relations(dataset: DiscoveredDataset, runs: dict[str, IndexedRun]):
    related, warnings = [], []
    for run_id in sorted(runs):
        relation = _relation(dataset, runs[run_id])
        if relation == 'id_conflict':
            warnings.append(DiscoveryWarning('dataset_hash_id_conflict', runs[run_id].root_id, run_id,
                                             'Dataset hash matches but the recorded dataset id does not. The run is not counted.'))
        elif relation is not None:
            related.append((runs[run_id], relation))
    return related, warnings


def _list_item(dataset: DiscoveredDataset, related) -> DatasetListItem:
    count = lambda name: sum(1 for _, relation in related if relation == name)
    return DatasetListItem(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, dataset_hash=dataset.dataset_hash,
        dataset_type=dataset.dataset_type, case_count=dataset.case_count, source=dataset.source,
        freeze_status=dataset.freeze_status, related_run_count=count('hash_match') + count('weak_path'),
        hash_matched_run_count=count('hash_match'), weak_path_run_count=count('weak_path'),
        hash_mismatch_run_count=count('hash_mismatch'))


def _rate(numerator: int, denominator: int) -> Rate:
    return Rate(numerator=numerator, denominator=denominator, rate=None if denominator == 0 else numerator / denominator)


def _safe_text(value: str | None, redactor: evidence_store.Redactor) -> str | None:
    if value is None:
        return None
    text = redactor.clean(value[:TEXT_LIMIT] if isinstance(value, str) else value, '$')
    return text if isinstance(text, str) else str(text)


def _safe_ref(ref: str | None) -> str | None:
    if ref is None:
        return None
    if ref.startswith(('/', '\\')) or '..' in ref.replace('\\', '/').split('/') or '\x00' in ref:
        return '[redacted:ref_outside_run]'
    return ref


def _oracle_id(view: RunView) -> str | None:
    if view.run.run_kind == 'tc_regression':
        return None
    return GoldenOracleEvaluator.evaluator_id if view.run.provenance == 'recorded' else GOLDEN_LEGACY_EVALUATOR


def _case_integrity(view: RunView, case_id: str):
    """Recorded case status, or the run's UNVERIFIED status for formats that record none per case."""
    report = view.run.integrity
    if report is None:
        return None
    return report.case_status.get(case_id) or ('UNVERIFIED' if report.status == 'UNVERIFIED' else None)


def _attribute(summary: E2ESummary, case_integrity) -> Attributed:
    if case_integrity == 'INVALID':
        return Attributed(value='evidence_integrity',
                          basis='Case files failed manifest verification. The recorded verdict is shown but not trusted.')
    basis = f'E2E gate {summary.gate}: {summary.reason}'
    verdict = summary.verdict
    if verdict == 'INFRA_ERROR':
        return Attributed(value='evaluation_infrastructure', basis=basis)
    if verdict == 'FAIL':
        return Attributed(value='agent_execution' if summary.gate == 'task_condition' else 'business_quality', basis=basis)
    if verdict == 'EVALUATOR_ERROR':
        return Attributed(value='evaluator_error', basis=basis)
    if verdict == 'NOT_EVALUATED':
        return Attributed(value='undetermined', basis=basis)
    return Attributed(value='none', basis=basis)


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

    def _runs_for_datasets(self):
        if not self.index.roots:
            return {}, []
        try:
            scanned = self._scan()
        except AppError:
            return {}, [DiscoveryWarning('run_roots_unavailable', None, None, 'Run roots could not be scanned. Related run counts are zero.')]
        return scanned.runs, list(scanned.warnings)

    def _locate(self, run_id: str) -> IndexedRun:
        result = self._scan()
        if run_id in result.runs:
            return result.runs[run_id]
        mine = [warning for warning in result.warnings if warning.entry == run_id]
        conflict = next((warning for warning in mine if warning.code in CONFLICT_CODES), None)
        if conflict:
            raise AppError('EVALUATION_RUN_ID_CONFLICT', '该运行 ID 无法唯一定位。', 409,
                           details={'reason': conflict.code, 'detail': conflict.detail})
        unreadable = next((warning for warning in mine if warning.code in UNREADABLE_CODES), None)
        if unreadable:
            raise AppError('EVALUATION_RUN_UNREADABLE', '运行目录存在但无法读取。', 409, details={'reason': unreadable.code})
        raise AppError('EVALUATION_RUN_NOT_FOUND', '评测运行不存在。', 404)

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
        runs, run_warnings = self._runs_for_datasets()
        items = []
        for dataset in datasets:
            related, extra = _relations(dataset, runs)
            items.append(_list_item(dataset, related))
            run_warnings += extra
        if dataset_type is not None:
            items = [item for item in items if item.dataset_type == dataset_type]
        items.sort(key=lambda item: _dataset_key(item, sort))
        return DatasetListPage(items=_page(items, page, page_size), total=len(items), page=page, page_size=page_size,
                               discovery_warnings=[_warning(item) for item in warnings + run_warnings])

    def get_dataset(self, dataset_id: str) -> DatasetDetail:
        if not self.datasets.sources:
            raise AppError('EVALUATION_DATASETS_UNAVAILABLE', '没有配置评测数据集来源。', 503)
        found, warnings = self.datasets.load_all()
        matches = [dataset for dataset in found if dataset.dataset_id == dataset_id]
        if not matches:
            raise AppError('EVALUATION_DATASET_NOT_FOUND', '数据集不存在。', 404)
        if len(matches) > 1:
            raise AppError('EVALUATION_DATASET_ID_CONFLICT', '同一数据集 ID 对应多个来源，无法合并为一个版本。', 409,
                           details={'dataset_hashes': sorted({d.dataset_hash for d in matches}),
                                    'sources': sorted(d.source for d in matches)})
        dataset = matches[0]
        runs, run_warnings = self._runs_for_datasets()
        related, extra = _relations(dataset, runs)
        variants: dict[str, int] = {dataset.dataset_hash: 0}
        for indexed, relation in related:
            recorded = indexed.view.run.dataset_hash
            if recorded is not None:
                variants[recorded] = variants.get(recorded, 0) + 1
        own = [w for w in warnings if w.entry == dataset.dataset_type or w.entry == f'{dataset.dataset_type}:{dataset.dataset_id}']
        return DatasetDetail(
            dataset_id=dataset.dataset_id, dataset_type=dataset.dataset_type, dataset_version=dataset.dataset_version,
            dataset_hash=dataset.dataset_hash, case_count=dataset.case_count, source=dataset.source,
            freeze_status=dataset.freeze_status, freeze_notice=FREEZE_NOTICE,
            hash_variants=[HashVariant(dataset_hash=value, matches_current_source=value == dataset.dataset_hash, run_count=count)
                           for value, count in sorted(variants.items(), key=lambda pair: (pair[0] != dataset.dataset_hash, pair[0]))],
            related_runs=[RelatedRun(run_id=indexed.run_id, run_type=indexed.run_type, created_at=indexed.view.run.created_at,
                                     lifecycle_status=indexed.view.run.status,
                                     integrity_status=indexed.view.run.integrity.status if indexed.view.run.integrity else None,
                                     recorded_dataset_id=indexed.view.run.dataset_id,
                                     recorded_dataset_hash=indexed.view.run.dataset_hash, relation=relation)
                          for indexed, relation in related],
            discovery_warnings=[_warning(w) for w in own + extra])

    # ---- run detail ----

    def _integrity(self, view: RunView, redactor) -> IntegrityView:
        report = view.run.integrity
        status = report.status if report else None
        return IntegrityView(
            status=status, trusted=status == 'VERIFIED', notice=INTEGRITY_NOTICE.get(status or 'UNVERIFIED'),
            reasons=[_safe_text(reason, redactor) for reason in (report.reasons if report else [])],
            basis=report.basis if report else None,
            files=[FileCheckView(ref=_safe_ref(f.ref), role=f.role, case_id=f.case_id, status=f.status)
                   for f in (report.files if report else [])],
            case_status=dict(report.case_status) if report else {})

    def _metrics(self, view: RunView) -> TrustedMetrics:
        oracle = _oracle_id(view)
        trusted = trusted_metrics(view, oracle_evaluator_id=oracle)
        status = trusted['integrity']
        included = trusted['included_case_ids']
        if status == 'VERIFIED':
            trust, notice = 'verified', 'All cases verified against the final manifest.'
        elif status == 'INVALID' and included:
            trust = 'partial_verified'
            notice = f'Evidence integrity failed. {len(trusted["excluded"])} case(s) excluded; values cover verified cases only and are not a trusted run result.'
        elif status == 'INVALID':
            trust, notice = 'none', 'Evidence integrity failed and no case verified. No metric is reported.'
        elif status == 'INCOMPLETE':
            trust, notice = 'incomplete', 'Run did not finish. Values cover the recorded cases only.'
        else:
            trust, notice = 'unverified', 'Historical run without a manifest. Values are computed from records that cannot be verified.'
        if trust == 'none':
            return TrustedMetrics(trust=trust, trusted=False, notice=notice, oracle_evaluator_id=oracle, included_case_ids=[],
                                  excluded=trusted['excluded'], counts=None, e2e_confirmed_success_rate=None,
                                  decidable_pass_rate=None, evaluation_coverage=None, execution_completion_rate=None, evaluators=[])
        values = trusted['metrics']
        counts = values['counts']
        e2e = counts['e2e']
        passed, decided, valid = e2e.get('PASS', 0), e2e.get('PASS', 0) + e2e.get('FAIL', 0), counts['valid']
        known = sum(counts['execution'].values())
        evaluators = [EvaluatorHealth(evaluator_id=evaluator_id, counts=item['counts'],
                                      error_rate=_rate(item['counts'].get('EVALUATOR_ERROR', 0), sum(item['counts'].values())),
                                      not_evaluated_rate=_rate(item['counts'].get('NOT_EVALUATED', 0), sum(item['counts'].values())))
                      for evaluator_id, item in values['evaluators'].items()]
        return TrustedMetrics(
            trust=trust, trusted=trust == 'verified', notice=notice, oracle_evaluator_id=oracle, included_case_ids=included,
            excluded=trusted['excluded'], counts=counts, e2e_confirmed_success_rate=_rate(passed, valid),
            decidable_pass_rate=_rate(passed, decided), evaluation_coverage=_rate(decided, valid),
            execution_completion_rate=_rate(counts['execution'].get('COMPLETED', 0), known), evaluators=evaluators)

    @staticmethod
    def _unreadable(view: RunView) -> list[str]:
        report = view.run.integrity
        prefix = 'case_result_unreadable:'
        return sorted(r[len(prefix):] for r in (report.reasons if report else []) if r.startswith(prefix))

    def _universe(self, view: RunView) -> dict[str, str]:
        states = {e.case_id: 'present' for e in view.executions}
        for case_id in view.run.missing_case_ids:
            states.setdefault(case_id, 'missing')
        for case_id in self._unreadable(view):
            states.setdefault(case_id, 'unreadable')
        for case_id in view.run.not_started_case_ids:
            states.setdefault(case_id, 'not_started')
        return dict(sorted(states.items()))

    def get_run(self, run_id: str) -> RunDetail:
        indexed = self._locate(run_id)
        view, run = indexed.view, indexed.view.run
        redactor = evidence_store.Redactor()
        case_status = {case_id: _case_integrity(view, case_id) for case_id in self._universe(view)}
        summaries = {s.case_id: s for s in view.e2e}
        universe = self._universe(view)
        cases = []
        for case_id, state in universe.items():
            execution = next((e for e in view.executions if e.case_id == case_id), None)
            summary = summaries.get(case_id)
            if state == 'present' and execution is not None and summary is not None:
                cases.append(CaseSummary(
                    case_id=case_id, case_state=state, execution_status=execution.execution_status,
                    blocking_stage=execution.blocking_stage, failure_origin=execution.failure_origin,
                    e2e_verdict=summary.verdict, e2e_gate=summary.gate, e2e_reason=summary.reason,
                    attribution=_attribute(summary, case_status.get(case_id)), case_integrity=case_status.get(case_id),
                    provenance=execution.provenance))
            else:
                cases.append(CaseSummary(
                    case_id=case_id, case_state=state, execution_status=None, blocking_stage=None, failure_origin=None,
                    e2e_verdict=None, e2e_gate=None, e2e_reason=None,
                    attribution=Attributed(value='evidence_integrity' if state == 'unreadable' else 'not_executed',
                                           basis=f'Case is {state}; no execution record was read.'),
                    case_integrity=case_status.get(case_id), provenance=None))
        distribution = {
            'execution': dict(sorted(_tally(e.execution_status or 'UNKNOWN' for e in view.executions).items())),
            'e2e': dict(sorted(_tally(s.verdict for s in view.e2e).items())),
            'case_state': dict(sorted(_tally(universe.values()).items())),
        }
        config = redactor.clean(run.execution_config, '$.execution_config')
        manifest = None if run.evaluator_manifest is None else [
            EvaluatorManifestItem(evaluator_id=e.evaluator_id, evaluator_version=e.evaluator_version, config_sha256=e.config_sha256,
                                  required=e.required, requirement=e.requirement, scope=e.scope) for e in run.evaluator_manifest]
        integrity = self._integrity(view, redactor)
        states = list(universe.values())
        return RunDetail(
            run_id=run.run_id, run_type=indexed.run_type, provenance=run.provenance,
            provenance_notice=('Recorded by the current runner with a config snapshot.' if run.provenance == 'recorded' else
                               'Projected from a historical run format. Missing fields stay null and are listed in unverified_fields.'),
            agent_id=run.agent_id, agent_version=run.agent_version, dataset_id=run.dataset_id,
            dataset_version=run.dataset_version, dataset_hash=run.dataset_hash, lifecycle_status=run.status,
            created_at=run.created_at, finished_at=run.finished_at, execution_config=config,
            unverified_fields=list(run.unverified), projection=dict(run.projection), integrity=integrity,
            evaluator_manifest=manifest,
            evaluator_manifest_notice=None if manifest is not None else 'This run format did not record an evaluator manifest.',
            case_counts=CaseCounts(total=len(states), present=states.count('present'), missing=states.count('missing'),
                                   not_started=states.count('not_started'), unreadable=states.count('unreadable')),
            missing_case_ids=list(run.missing_case_ids), not_started_case_ids=list(run.not_started_case_ids),
            unreadable_case_ids=self._unreadable(view), recorded_distribution=distribution, metrics=self._metrics(view),
            cases=cases, redactions=redactor.report())

    # ---- case detail ----

    def _case_state(self, view: RunView, case_id: str) -> str:
        universe = self._universe(view)
        if case_id not in universe:
            raise AppError('EVALUATION_CASE_NOT_FOUND', '该运行中没有这个 Case。', 404)
        return universe[case_id]

    @staticmethod
    def _file_integrity(view: RunView, case_id: str, file_ref: str | None):
        report = view.run.integrity
        status = report.status if report else None
        case_ok = bool(report) and report.case_status.get(case_id) == 'VERIFIED'
        if file_ref is None:
            return 'not_applicable', case_ok, None
        if status in (None, 'UNVERIFIED'):
            return 'unverified', False, None
        if status == 'INCOMPLETE':
            return 'incomplete', False, None
        check = next((f for f in report.files if f.ref == file_ref), None)
        if check is None:
            return 'not_in_manifest', False, None
        return check.status, check.status == 'ok' and case_ok, check

    def _availability(self, indexed: IndexedRun, case_id: str, ref: str | None, notice_missing: str) -> Availability:
        if not ref:
            return Availability(available=False, ref=None, integrity='not_applicable', notice=notice_missing)
        file_ref = ref.split('#', 1)[0]
        path = evidence_store.contained_path(indexed.path, file_ref)
        present = path is not None and not path.is_symlink() and path.is_file()
        integrity, _trusted, _check = self._file_integrity(indexed.view, case_id, file_ref)
        return Availability(available=present, ref=ref, integrity=integrity,
                            notice=None if present else 'Referenced file is missing or outside the run directory.')

    def _evidence_index(self, indexed: IndexedRun, case_id: str) -> list[EvidenceIndexItem]:
        view = indexed.view
        items = []
        for kind in evidence_store.EVIDENCE_KINDS:
            if kind == 'trace':
                execution = next((e for e in view.executions if e.case_id == case_id), None)
                if view.run.run_kind == 'tc_regression':
                    items.append(EvidenceIndexItem(kind=kind, status='UNAVAILABLE', reason='trace_only_in_sqlite_not_exposed'))
                    continue
                if execution is None or not execution.trace_ref:
                    items.append(EvidenceIndexItem(kind=kind, status='NOT_RECORDED', reason='trace_not_recorded'))
                    continue
                path = evidence_store.contained_path(indexed.path, execution.trace_ref)
                ok = path is not None and not path.is_symlink() and path.is_file()
                items.append(EvidenceIndexItem(kind=kind, status='AVAILABLE' if ok else 'UNAVAILABLE',
                                               reason=None if ok else 'file_missing_or_outside_run'))
                continue
            try:
                read = evidence_store.locate(view, indexed.path, case_id, kind)
            except evidence_store.EvidenceTooLarge:
                items.append(EvidenceIndexItem(kind=kind, status='UNAVAILABLE', reason='too_large'))
                continue
            items.append(EvidenceIndexItem(kind=kind, status=read.status, reason=read.reason))
        return items

    def get_case(self, run_id: str, case_id: str) -> CaseDetail:
        indexed = self._locate(run_id)
        view, run = indexed.view, indexed.view.run
        state = self._case_state(view, case_id)
        redactor = evidence_store.Redactor()
        report = run.integrity
        case_integrity = _case_integrity(view, case_id)
        case_files = [FileCheckView(ref=_safe_ref(f.ref), role=f.role, case_id=f.case_id, status=f.status)
                      for f in (report.files if report else []) if f.case_id == case_id]
        execution = next((e for e in view.executions if e.case_id == case_id), None)
        if state != 'present' or execution is None:
            reasons = {'missing': 'Listed in the run but no case result file exists.',
                       'not_started': 'The runner recorded this case as not run.',
                       'unreadable': 'The case result file exists but could not be parsed. Nothing from it is reported.'}
            return CaseDetail(
                run_id=run.run_id, run_type=indexed.run_type, case_id=case_id, case_state=state,
                case_state_reason=reasons.get(state), case_integrity=case_integrity, case_files=case_files,
                execution=None, e2e=None,
                attribution=Attributed(value='evidence_integrity' if state == 'unreadable' else 'not_executed', basis=reasons.get(state, state)),
                evaluators=[], slots=self._slots(view, []),
                execution_record=Availability(available=False, ref=None, integrity='not_applicable', notice=reasons.get(state)),
                final_output=Availability(available=False, ref=None, integrity='not_applicable', notice=reasons.get(state)),
                evidence=[EvidenceIndexItem(kind=kind, status='NOT_RECORDED', reason='case_not_executed')
                          for kind in evidence_store.EVIDENCE_KINDS],
                legacy_labels=None, redactions=[])
        summary = next(s for s in view.e2e if s.case_id == case_id)
        requirement = {e.evaluator_id: e.requirement for e in run.evaluator_manifest or []}
        results = [r for r in view.evaluator_results if r.case_execution_ref == execution.locator]
        evaluators = [EvaluatorResultView(
            evaluator_id=r.evaluator_id, role=ROLES.get(r.evaluator_id, 'other'), evaluator_version=r.evaluator_version,
            evaluator_config_hash=r.evaluator_config_hash, required=r.required, requirement=requirement.get(r.evaluator_id),
            scope=r.evaluation_scope, verdict=r.verdict, failure_code=r.failure_code, reason=_safe_text(r.reason, redactor),
            evidence_refs=[_safe_ref(ref) for ref in r.evidence_refs], evaluated_at=r.evaluated_at, provenance=r.provenance,
            basis=r.basis, legacy_label=redactor.clean(r.legacy, '$.legacy_label') if r.legacy is not None else None)
            for r in results]
        legacy = None
        if execution.legacy is not None:
            picked = {key: execution.legacy[key] for key in LEGACY_CASE_KEYS if key in execution.legacy}
            if isinstance(picked.get('runner_error'), str):
                picked['runner_error'] = picked['runner_error'][:TEXT_LIMIT]
            legacy = redactor.clean(picked, '$.legacy_labels')
        final_ref = execution.output_ref
        if final_ref is None and run.run_kind == 'tc_regression' and execution.record_ref and (execution.legacy or {}).get('result_tables'):
            final_ref = execution.record_ref + '.result_tables'
        missing_output = ('Historical Golden runs did not save the final output.' if run.provenance != 'recorded' and run.run_kind == 'golden'
                          else 'No final output was recorded for this case.')
        trusted_case = case_integrity == 'VERIFIED'
        return CaseDetail(
            run_id=run.run_id, run_type=indexed.run_type, case_id=case_id, case_state=state, case_state_reason=None,
            case_integrity=case_integrity, case_files=case_files,
            execution=ExecutionView(
                execution_id=execution.execution_id, attempt=execution.attempt, execution_status=execution.execution_status,
                failure_origin=execution.failure_origin, blocking_stage=execution.blocking_stage, error_code=execution.error_code,
                expect_blocked=execution.expect_blocked, started_at=execution.started_at, finished_at=execution.finished_at,
                workflow_id=execution.workflow_id, workflow_store='isolated_run_store', workflow_linkable=False,
                provenance=execution.provenance, projection=dict(execution.projection), unverified_fields=list(execution.unverified)),
            e2e=E2EView(verdict=summary.verdict, gate=summary.gate, reason=summary.reason, task_condition_met=summary.task_condition_met,
                        required_verdicts=dict(summary.required_verdicts), optional_verdicts=dict(summary.optional_verdicts),
                        trusted=trusted_case),
            attribution=_attribute(summary, case_integrity), evaluators=evaluators, slots=self._slots(view, evaluators),
            execution_record=self._availability(indexed, case_id, execution.record_ref, 'No execution record was written.'),
            final_output=self._availability(indexed, case_id, final_ref, missing_output),
            evidence=self._evidence_index(indexed, case_id), legacy_labels=legacy, redactions=redactor.report())

    @staticmethod
    def _slots(view: RunView, evaluators: list[EvaluatorResultView]) -> dict[str, EvaluatorSlot]:
        run = view.run
        listed = {e.evaluator_id for e in run.evaluator_manifest or []}
        slots = {}
        for slot, roles, evaluator_id in (('oracle', ('oracle', 'legacy_oracle'), GoldenOracleEvaluator.evaluator_id),
                                          ('must_forbid', ('must_forbid',), MustForbidEvaluator.evaluator_id),
                                          ('node_fidelity', ('node_fidelity',), RequirementFidelityNodeEvaluator.evaluator_id)):
            found = next((e for e in evaluators if e.role in roles), None)
            if found is not None:
                slots[slot] = EvaluatorSlot(state='recorded', evaluator_id=found.evaluator_id, verdict=found.verdict, notice=None)
            elif run.run_kind == 'tc_regression':
                slots[slot] = EvaluatorSlot(state='not_applicable', evaluator_id=None, verdict=None,
                                            notice='TC regression runs use their own checks; this evaluator does not apply.')
            else:
                notice = ('Listed in the evaluator manifest but no result was recorded.' if evaluator_id in listed else
                          'This run format did not record this evaluator. This is not NOT_EVALUATED.')
                slots[slot] = EvaluatorSlot(state='not_recorded', evaluator_id=None, verdict=None, notice=notice)
        return slots

    # ---- evidence ----

    def get_evidence(self, run_id: str, case_id: str, kind: str) -> EvidenceView:
        indexed = self._locate(run_id)
        view = indexed.view
        self._case_state(view, case_id)
        limits = EvidenceLimits(max_file_bytes=evidence_store.MAX_FILE_BYTES, max_response_bytes=evidence_store.MAX_RESPONSE_BYTES,
                                max_values=evidence_store.MAX_VALUES, max_depth=evidence_store.MAX_DEPTH)
        try:
            read = evidence_store.locate(view, indexed.path, case_id, kind)
            if read.status == 'AVAILABLE':
                content, redactor = evidence_store.redact(read.content)
            else:
                content, redactor = None, evidence_store.Redactor()
        except evidence_store.EvidenceTooLarge as error:
            raise AppError('EVIDENCE_TOO_LARGE', '证据超过响应大小限制。', 413,
                           details={'reason': error.reason, 'limit': error.limit, 'actual': error.actual}) from None
        size = len(json.dumps(content, ensure_ascii=False).encode('utf-8'))
        if size > evidence_store.MAX_RESPONSE_BYTES:
            raise AppError('EVIDENCE_TOO_LARGE', '证据超过响应大小限制。', 413,
                           details={'reason': 'response_too_large', 'limit': evidence_store.MAX_RESPONSE_BYTES, 'actual': size})
        integrity, trusted, check = self._file_integrity(view, case_id, read.file_ref)
        return EvidenceView(
            run_id=view.run.run_id, case_id=case_id, kind=kind, status=read.status, reason=read.reason, ref=_safe_ref(read.ref),
            integrity=EvidenceIntegrityView(status=integrity, trusted=trusted and read.status == 'AVAILABLE',
                                            expected_sha256=check.expected_sha256 if check else None,
                                            actual_sha256=check.actual_sha256 if check else None),
            file_size_bytes=read.size_bytes, file_sha256=read.file_sha256, limits=limits,
            depth_truncated_paths=sorted(set(redactor.depth_cuts)), redactions=redactor.report(), content=content)


def _tally(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out
