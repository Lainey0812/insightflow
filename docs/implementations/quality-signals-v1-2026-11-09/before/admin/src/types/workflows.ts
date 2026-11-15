import type { TraceRun, TraceSpan, TraceEvent, Metadata } from './traces';
export const businessStatuses = ['created','running','waiting_input','waiting_approval','succeeded','partially_succeeded','failed','interrupted','unknown'] as const;
export type BusinessStatus = typeof businessStatuses[number];
export type FindingCategory = 'not_executed' | 'executed_trace_missing' | 'observation_incomplete' | 'inconsistent' | 'unknown';
export interface Finding { category: FindingCategory; code: string; node_key?: string; evidence_refs: string[] }
export interface WorkflowCall { call_id: string; node_id: string; span_id: string | null; status: string; call_sequence: number; retry_index: number; retry_of_call_id?: string | null; duration_ms: number | null; request_snapshot_id: string; template_snapshot_id: string }
export interface WorkflowObservation {
  workflow_id: string; root_run_id: string; session_id: string; root: TraceRun | null;
  nodes: TraceSpan[]; events: TraceEvent[]; llm_calls: WorkflowCall[];
  plan_versions: Metadata[]; approvals: Metadata[]; executions: Metadata[]; report_generations: Metadata[]; reports: Metadata[]; report_artifact_runs: Metadata[];
}
export const failureCategories = ['file_input','data_content','model_service','model_output','capacity','plan_blocked','interrupted','unclassified'] as const;
export type FailureCategory = typeof failureCategories[number];
export interface WorkflowFailure {
  category: FailureCategory; label: string; hint: string; code: string;
  source: 'node' | 'business' | 'report_generation';
  node_name: string | null; node_key: string | null; span_id: string | null; inputs: Metadata;
}
export interface WorkflowView {
  failure?: WorkflowFailure | null;
  schema_version: 'workflow-observability-v1'; workflow_id: string; session_id: string; root_run_id: string;
  business_lifecycle: { status: BusinessStatus; execution_status: string | null; report_generation_status: string | null; report_status: string | null; report_delivery: string; goal_coverage: string | null };
  activity: string; reason_codes: string[]; source_refs: Metadata; consistency: { status: string; issues: string[] };
  created_at: string; updated_at: string | null; ended_at: string | null; duration_ms: number | null; duration_basis: string | null;
  has_exception: boolean; collection: { status: 'observed' | 'incomplete'; findings: Finding[]; notice: string };
  trace?: WorkflowObservation | null;
}
export interface WorkflowPage { schema_version: 'workflow-observability-page-v1'; items: WorkflowView[]; total: number; limit: number; offset: number; sort: string; notice: string }
