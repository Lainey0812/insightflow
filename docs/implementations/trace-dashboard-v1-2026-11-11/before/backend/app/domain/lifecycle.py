"""Read-only projections; these enums are NOT stored Workflow/Trace transitions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

LifecycleStatus = Literal['created', 'running', 'waiting_input', 'waiting_approval',
    'succeeded', 'partially_succeeded', 'failed', 'interrupted', 'unknown']
Activity = Literal['not_started', 'preparing', 'profiling', 'parsing_intent', 'planning',
    'validating', 'clarification', 'review', 'approved_not_started', 'executing',
    'report_not_started', 'report_queued', 'reporting', 'finished', 'unknown']
Reason = Literal['clarification_required', 'approval_required', 'approved_not_started',
    'core_requirements_unmet', 'uncertainties_unresolved', 'execution_partial', 'execution_failed',
    'report_failed', 'report_not_delivered', 'report_unavailable', 'report_partial', 'goal_not_fully_covered',
    'report_not_started', 'report_retry', 'process_interrupted', 'trace_not_collected',
    'trace_unavailable', 'trace_incomplete', 'trace_stale', 'trace_binding_mismatch',
    'trace_state_conflict', 'unsupported_workflow', 'record_missing', 'record_invalid',
    'branch_mismatch', 'historical_branch_ignored', 'execution_ambiguous', 'session_changed',
    'business_store_unavailable', 'business_state_conflict']

class Projection(BaseModel):
    model_config = ConfigDict(extra='forbid')

class BusinessLifecycle(Projection):
    status: LifecycleStatus = 'unknown'
    execution_status: Literal['running','success','partial_success','failed'] | None = None
    report_generation_status: Literal['queued','generating','completed','failed','unavailable'] | None = None
    report_status: Literal['complete','partial','unavailable'] | None = None
    goal_coverage: Literal['complete','partial','blocked'] | None = None
    report_delivery: Literal['delivered','not_delivered','unknown'] = 'unknown'

class SourceRefs(Projection):
    session_id: str
    session_revision: int | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    plan_id: str | None = None
    plan_version: int | None = None
    validation_version: str | None = None
    approval_id: str | None = None
    execution_id: str | None = None
    report_attempt: int | None = None
    report_id: str | None = None
    workflow_run_id: str | None = None
    report_run_id: str | None = None

class ObservedSpan(Projection):
    span_id: str
    run_id: str
    node: str
    node_key: str | None = None
    node_attempt: int | None = None
    status: Literal['running','complete','partial','failed','skipped','interrupted']

class Collection(Projection):
    availability: Literal['available','not_collected','unavailable','unknown'] = 'unknown'
    integrity: Literal['incomplete','unknown'] = 'unknown'
    capture_scope: str | None = None
    root_status: str | None = None
    root_business_revision: int | None = None
    report_trace_status: str | None = None
    observed_spans: list[ObservedSpan] = Field(default_factory=list)
    event_count: int = 0
    # No complete flag: existing instrumentation cannot prove end-to-end collection.
    report_attempt_history: Literal['not_guaranteed'] = 'not_guaranteed'

class Consistency(Projection):
    status: Literal['consistent','unknown','inconsistent'] = 'unknown'
    business_snapshot: Literal['transactional','unavailable'] = 'unavailable'
    cross_store_snapshot: Literal['non_atomic'] = 'non_atomic'
    revision_rechecked: bool = False
    issues: list[Reason] = Field(default_factory=list)

class LifecycleReadModel(Projection):
    schema_version: Literal['lifecycle-read-v1'] = 'lifecycle-read-v1'
    business_lifecycle: BusinessLifecycle = Field(default_factory=BusinessLifecycle)
    activity: Activity = 'unknown'
    reason_codes: list[Reason] = Field(default_factory=list)
    source_refs: SourceRefs
    collection: Collection = Field(default_factory=Collection)
    consistency: Consistency = Field(default_factory=Consistency)
