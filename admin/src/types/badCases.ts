import type { BusinessStatus, WorkflowFailure, WorkflowQuality } from './workflows';
import type { Metadata } from './traces';

export const badCaseCategories = ['understanding','planning','calculation','insight','report','failure','other'] as const;
export type BadCaseCategory = typeof badCaseCategories[number];
export const badCaseSeverities = ['high','medium','low'] as const;
export type BadCaseSeverity = typeof badCaseSeverities[number];
export const badCaseStatuses = ['open','confirmed','fixed','wont_fix','invalid','in_progress','pending_verification'] as const;
export type BadCaseStatus = typeof badCaseStatuses[number];

export interface BadCaseSummary {
  attribution?: Attribution | null;
  case_id: string; workflow_id: string; span_id: string | null; node_name: string | null;
  category: BadCaseCategory; severity: BadCaseSeverity; title: string; created_at: string; created_by: string;
  business_status: BusinessStatus; status: BadCaseStatus; sequence: number; updated_at: string;
}
export interface BadCasePage { schema_version: 'bad-case-page-v1'; items: BadCaseSummary[]; total: number; limit: number; offset: number }
export interface Attribution {cause:'prompt'|'data'|'capability'|'validation'|'code'|'unknown';node_id:'intent_parser'|'analysis_planner'|'insight_generator'|null;explanation:string}
export interface BadCaseEvent { event_id: string; sequence: number; created_at: string; kind: 'created' | 'status_changed' | 'note' | 'attribution_submitted' | 'repair_submitted'; status: BadCaseStatus; note: string; annotator: string; attribution?:Attribution;repair?:{template_snapshot_id:string;node_id:string} }
export interface EvidenceNode { span_id: string; name: string; node_key: string | null; status: string; error_code: string | null; started_at: string | null; finished_at: string | null; duration_ms: number | null; attributes: Metadata }
export interface EvidenceCall { call_id: string; node_id: string; span_id: string | null; status: string; retry_index: number; error_code: string | null; request_snapshot_id: string; template_snapshot_id: string; response_hash: string | null }
export interface BadCaseEvidence {
  schema_version: 'bad-case-evidence-v1'; workflow_id: string; root_run_id: string;
  business_lifecycle: { status: BusinessStatus; execution_status: string | null; report_status: string | null; goal_coverage: string | null };
  failure: WorkflowFailure | null; quality: WorkflowQuality | null; consistency: { status: string; issues: string[] }; collection_status: string;
  nodes: EvidenceNode[]; llm_calls: EvidenceCall[]; replay_refs: Record<string, string | number | null | string[]>;
}
export interface BadCase {
  attribution?:Attribution|null;repair?:{template_snapshot_id:string;node_id:string}|null;
  schema_version: 'bad-case-v1'; case_id: string; workflow_id: string; span_id: string | null; node_name: string | null;
  category: BadCaseCategory; severity: BadCaseSeverity; title: string; observed: string; expected: string;
  created_at: string; created_by: string; status: BadCaseStatus; sequence: number; events: BadCaseEvent[];
  evidence: BadCaseEvidence; evidence_sha256: string; evidence_intact: boolean; evidence_notice: string;
}
export interface BadCaseDraft { workflow_id: string; span_id: string | null; category: BadCaseCategory; severity: BadCaseSeverity; title: string; observed: string; expected: string; annotator: string }
export interface BadCaseTransition { status: BadCaseStatus; note: string; annotator: string; expected_sequence: number }
