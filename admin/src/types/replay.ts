import type { WorkflowFailure, WorkflowQuality } from './workflows';

export const replayOutcomes = ['cleared', 'recurred', 'changed', 'unchanged', 'blocked', 'source_missing', 'not_run'] as const;
export type ReplayOutcome = typeof replayOutcomes[number];
export interface ReplayCase {
  case_id: string; title: string; category?: string; severity?: string; annotation_status?: string;
  observed: string; expected: string; outcome: ReplayOutcome; reason?: string;
  original_workflow_id?: string; workflow_id?: string; approved_by_runner?: boolean; approval_note?: string | null;
  final_status?: string; error_code?: string | null; execution_status?: string | null; report_status?: string | null;
  business_status?: string; duration_ms?: number; runner_error?: string;
  failure?: Pick<WorkflowFailure, 'code' | 'category' | 'label' | 'node_name'> | null;
  quality?: WorkflowQuality | null;
  source_ref?: { session_id?: string; dataset_id?: string; dataset_version?: string; file_sha256?: string };
}
export interface ReplaySummary {
  counts: Partial<Record<ReplayOutcome, number>>; auto_total: number; cleared: number; recurred: number;
  source_missing: number; llm_calls: number; duration_ms: number; prompt_templates: Record<string, string[]>; notice?: string;
}
export interface ReplayRunItem {
  run_id: string; label: string; started_at: string; finished_at: string | null; state: 'finished' | 'incomplete';
  environment: { model: string }; source_fingerprint: string; summary: ReplaySummary; selected_cases: string[];
}
export interface ReplayRun extends ReplayRunItem { approval_policy?: string; notice?: string; cases: ReplayCase[] }
export interface ReplayRunPage { schema_version: 'replay-run-page-v1'; items: ReplayRunItem[]; total: number; notice: string }
