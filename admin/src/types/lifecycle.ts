/** lifecycle-read-v1: projection only; never an execution or approval permission. */
import type { RunStatus } from './traces';
export const lifecycleStatuses = ['created', 'running', 'waiting_input', 'waiting_approval', 'succeeded', 'partially_succeeded', 'failed', 'interrupted', 'unknown'] as const;
export const lifecycleActivities = ['not_started', 'preparing', 'profiling', 'parsing_intent', 'planning', 'validating', 'clarification', 'review', 'approved_not_started', 'executing', 'report_not_started', 'report_queued', 'reporting', 'finished', 'unknown'] as const;
export const lifecycleReasons = ['clarification_required', 'approval_required', 'approved_not_started', 'core_requirements_unmet', 'uncertainties_unresolved', 'execution_partial', 'execution_failed', 'report_failed', 'report_not_delivered', 'report_unavailable', 'report_partial', 'goal_not_fully_covered', 'report_not_started', 'report_retry', 'process_interrupted', 'trace_not_collected', 'trace_unavailable', 'trace_incomplete', 'trace_stale', 'trace_binding_mismatch', 'trace_state_conflict', 'unsupported_workflow', 'record_missing', 'record_invalid', 'branch_mismatch', 'historical_branch_ignored', 'execution_ambiguous', 'session_changed', 'business_store_unavailable', 'business_state_conflict'] as const;
export type LifecycleStatus = typeof lifecycleStatuses[number];
export type LifecycleActivity = typeof lifecycleActivities[number];
export type LifecycleReason = typeof lifecycleReasons[number];
export interface LifecycleRefs {
  session_id: string; session_revision: number | null;
  dataset_id: string | null; dataset_version: string | null;
  plan_id: string | null; plan_version: number | null; validation_version: string | null;
  approval_id: string | null; execution_id: string | null; report_attempt: number | null;
  report_id: string | null; workflow_run_id: string | null; report_run_id: string | null;
}
export interface LifecycleReadModel {
  schema_version: 'lifecycle-read-v1';
  business_lifecycle: {
    status: LifecycleStatus;
    execution_status: 'running' | 'success' | 'partial_success' | 'failed' | null;
    report_generation_status: 'queued' | 'generating' | 'completed' | 'failed' | 'unavailable' | null;
    report_status: 'complete' | 'partial' | 'unavailable' | null;
    goal_coverage: 'complete' | 'partial' | 'blocked' | null;
    report_delivery: 'delivered' | 'not_delivered' | 'unknown';
  };
  activity: LifecycleActivity; reason_codes: LifecycleReason[]; source_refs: LifecycleRefs;
  collection: {
    availability: 'available' | 'not_collected' | 'unavailable' | 'unknown'; integrity: 'incomplete' | 'unknown';
    capture_scope: string | null; root_status: string | null; root_business_revision: number | null;
    report_trace_status: string | null;
    observed_spans: { span_id: string; run_id: string; node: string; node_key: string | null; node_attempt: number | null; status: RunStatus }[];
    event_count: number; report_attempt_history: 'not_guaranteed';
  };
  consistency: {
    status: 'consistent' | 'unknown' | 'inconsistent'; business_snapshot: 'transactional' | 'unavailable';
    cross_store_snapshot: 'non_atomic'; revision_rechecked: boolean; issues: LifecycleReason[];
  };
}
