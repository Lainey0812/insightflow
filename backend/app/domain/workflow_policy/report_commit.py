"""Pure report-commit evidence reconciliation; never reads or writes a store.

A trusted reader must query these records in a single business read transaction.
The protocol distinguishes committed facts from a lost in-memory return value.
No client boolean or Trace status is accepted as a commit receipt.
"""
from typing import Literal
from pydantic import Field, StrictBool
from .models import Bindings, BusinessFact, FrozenModel, Reference


class ReportAuthorization(FrozenModel):
    session_id: Reference
    workflow_id: Reference
    root_run_id: Reference
    binding: Bindings
    report_id: Reference
    persistence_span_id: Reference | None = None
    report_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_id: Reference
    payload_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    authorized_revision: int = Field(ge=0, strict=True)
    authorized_active_key: Reference


class ReportOwnership(FrozenModel):
    session_id: Reference
    workflow_id: Reference
    execution_id: Reference
    report_id: Reference
    accepted_report_attempt: int = Field(ge=1, strict=True)


class CommitMetadata(FrozenModel):
    authorization: ReportAuthorization
    committed_revision: int = Field(ge=1, strict=True)


class CommitRecords(FrozenModel):
    # 'transactional' is asserted only by the future trusted business reader.
    read_consistency: Literal['transactional', 'unavailable', 'unknown'] = 'unknown'
    writer_isolated: StrictBool = False
    report: BusinessFact | None = None
    generation: BusinessFact | None = None
    ownership: ReportOwnership | None = None
    metadata: CommitMetadata | None = None


class CommitReconciliation(FrozenModel):
    status: Literal['accepted', 'not_committed', 'unknown', 'inconsistent']
    accepted: StrictBool | None
    reason_code: str
    report_id: str | None = None
    committed_revision: int | None = None


class CompletionSpan(FrozenModel):
    span_id: Reference
    run_id: Reference
    session_id: Reference
    workflow_id: Reference
    node_key: Reference
    parent_span_id: str | None = None
    status: Literal['running', 'complete', 'partial', 'failed', 'skipped', 'interrupted']
    binding: Bindings
    report_id: Reference
    report_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    commit_request_id: Reference
    commit_payload_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    authorized_revision: int = Field(ge=0, strict=True)
    authorized_active_key: Reference


REFERENCE_FIELDS = ('dataset_id', 'dataset_version', 'plan_version_id', 'plan_id', 'plan_version',
                    'validation_version', 'approval_id', 'execution_id', 'execution_request_id', 'report_attempt')


def reconcile_report_commit(authorization: ReportAuthorization, records: CommitRecords | None) -> CommitReconciliation:
    """Resolve an acknowledged or lost-ack commit using only persistent evidence.

    Missing acknowledgement is not an input, because it proves neither commit nor
    rollback. Absence is conclusive only under a transactional read after fencing
    the writer; otherwise the verdict remains unknown.
    """
    a = ReportAuthorization.model_validate(authorization)
    r = CommitRecords.model_validate(records) if records is not None else None
    def verdict(status, accepted, code):
        return CommitReconciliation(status=status, accepted=accepted, reason_code=code,
            report_id=a.report_id if accepted else None,
            committed_revision=r.metadata.committed_revision if accepted and r and r.metadata else None)
    if r is None or r.read_consistency != 'transactional':
        return verdict('unknown', None, 'COMMIT_READ_UNCONFIRMED')
    if any(getattr(a.binding, key) is None for key in REFERENCE_FIELDS):
        return verdict('inconsistent', None, 'COMMIT_REFERENCE_MISSING')
    if r.report is None and r.ownership is None and r.metadata is None:
        g = r.generation
        if (r.writer_isolated and g is not None and g.kind == 'generation' and
                (g.session_id, g.workflow_id) == (a.session_id, a.workflow_id) and
                g.binding == a.binding and g.operation_key == a.authorized_active_key and
                g.generation_status == 'generating' and g.report_id is None):
            return verdict('not_committed', False, 'COMMIT_ABSENCE_VERIFIED')
        return verdict('unknown', None, 'COMMIT_ABSENCE_UNCONFIRMED')
    if any(x is None for x in (r.report, r.generation, r.ownership, r.metadata)):
        return verdict('inconsistent', None, 'COMMIT_RECORD_MISSING')
    report, generation, link, metadata = r.report, r.generation, r.ownership, r.metadata
    if metadata.authorization != a or metadata.committed_revision != a.authorized_revision + 1:
        return verdict('inconsistent', None, 'COMMIT_METADATA_MISMATCH')
    if (report.kind != 'report' or generation.kind != 'generation' or
            (report.session_id, report.workflow_id) != (a.session_id, a.workflow_id) or
            (generation.session_id, generation.workflow_id) != (a.session_id, a.workflow_id) or
            (link.session_id, link.workflow_id) != (a.session_id, a.workflow_id)):
        return verdict('inconsistent', None, 'COMMIT_OWNER_MISMATCH')
    if (report.binding != a.binding or generation.binding != a.binding or
            link.execution_id != a.binding.execution_id or link.accepted_report_attempt != a.binding.report_attempt):
        return verdict('inconsistent', None, 'COMMIT_BRANCH_MISMATCH')
    if (report.fact_id != a.report_id or generation.report_id != a.report_id or link.report_id != a.report_id or
            report.digest != a.report_digest or report.operation_key != a.authorized_active_key or
            generation.operation_key != a.authorized_active_key or generation.generation_status != 'completed' or
            report.report_status not in {'complete', 'partial'} or not report.evidence_ids or
            report.valid_core_insight_count < 1 or report.goal_coverage is None):
        return verdict('inconsistent', None, 'COMMIT_REPORT_MISMATCH')
    return verdict('accepted', True, 'COMMIT_PERSISTED')
