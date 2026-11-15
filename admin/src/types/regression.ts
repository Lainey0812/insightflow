import type { WorkflowFailure, WorkflowQuality } from './workflows';

export const caseStatuses = ['passed','failed','blocked','needs_review','not_run'] as const;
export type CaseStatus = typeof caseStatuses[number];
export interface RegressionCheck { key: string; label: string; status: 'pass' | 'fail' | 'skip'; expected: unknown; actual: unknown }
export interface RegressionCase {
  case_id: string; title: string; status: CaseStatus; checks: RegressionCheck[]; manual_review: string[]; reason?: string;
  approval_note?: string | null; approved_by_runner?: boolean; workflow_id?: string; session_id?: string;
  initial_status?: string; final_status?: string; error_code?: string | null; runner_error?: string; runner_error_message?: string;
  intent?: { analysis_mode: string | null; next_action: string | null };
  plan?: { coverage_status: string; task_count: number; executable_count: number; blocked_count: number; f0_count: number; f1_count: number; unmet_core_count: number };
  execution_status?: string | null; report_generation_status?: string | null; report_status?: string | null; goal_coverage?: string | null; insight_count?: number;
  duration_ms?: number; llm?: { calls: number; retries: number; failed: number; duration_ms: number };
  prompt_templates?: Record<string, string[]>; quality?: WorkflowQuality | null; failure?: WorkflowFailure | null;
}
export interface RunSummary { counts: Partial<Record<CaseStatus, number>>; auto_total: number; passed: number; llm_calls: number; duration_ms: number; prompt_templates: Record<string, string[]> }
export interface RegressionEnvironment { model: string; timeout_seconds?: number; intent_enable_thinking?: boolean | null; planner_enable_thinking?: boolean | null; report_enable_thinking?: boolean | null; intent_max_attempts?: number; planner_max_attempts?: number }
export interface RegressionRunItem {
  run_id: string; label: string; started_at: string; finished_at: string | null; state: 'finished' | 'incomplete';
  suite: { version?: string; cases_sha256?: string }; environment: RegressionEnvironment; source_fingerprint: string; summary: RunSummary; selected_cases: string[];
}
export interface RegressionRun extends RegressionRunItem { approval_policy?: string; cases: RegressionCase[] }
export interface RegressionRunPage { schema_version: 'regression-run-page-v1'; items: RegressionRunItem[]; total: number; notice: string }
export const regressionChanges = ['improved','regressed','unchanged','changed','not_compared','only_one'] as const;
export type RegressionChange = typeof regressionChanges[number];
export interface RegressionCheckChange { key: string; label: string | null; left: string | null; right: string | null }
export interface RegressionCaseCompare { case_id: string; title: string | null; left_status: CaseStatus | null; right_status: CaseStatus | null; change: RegressionChange; check_changes: RegressionCheckChange[] }
export interface RegressionCompare {
  schema_version: 'regression-compare-v1';
  left: Pick<RegressionRunItem, 'run_id' | 'label' | 'state' | 'environment' | 'source_fingerprint' | 'summary'>;
  right: Pick<RegressionRunItem, 'run_id' | 'label' | 'state' | 'environment' | 'source_fingerprint' | 'summary'>;
  cases: RegressionCaseCompare[]; counts: Partial<Record<RegressionChange, number>>; notice: string;
}
