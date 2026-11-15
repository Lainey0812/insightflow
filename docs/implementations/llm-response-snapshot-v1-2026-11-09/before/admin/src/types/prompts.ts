export type PromptNode = 'intent_parser' | 'analysis_planner' | 'insight_generator';
export interface TemplateSummary {
  template_snapshot_id: string; node_id: PromptNode; version: string; content_hash: string;
  created_at: string; source_commit: string | null; source_dirty?: boolean | null; provenance: string; change_summary: string;
}
export interface RegistrationState {
  latest_registered: TemplateSummary | null; runtime_snapshot_id: string | null;
  runtime_registration: 'registered' | 'not_registered' | 'unknown';
}
export interface PromptCatalogItem extends RegistrationState { prompt_id: PromptNode; node_id: PromptNode; label: string; version_count: number }
export interface PromptCatalog { items: PromptCatalogItem[]; notice: string }
export interface TemplateHistory extends RegistrationState { prompt_id: PromptNode; label: string; items: TemplateSummary[]; total: number; limit: number; offset: number }
export interface PromptTemplate extends TemplateSummary {
  system_template: string; user_composition: Record<string, unknown>; output_schema_definition: Record<string, unknown>;
  source_files: Record<string, { source?: string; source_hash?: string; [key: string]: unknown }>;
}
export interface TemplateDetail extends RegistrationState {
  template: PromptTemplate; availability: string; variables_schema_availability: string; variables_notice: string;
}
export interface LLMCall {
  call_id: string; node_id: PromptNode; operation_id: string; call_sequence: number; retry_index: number;
  retry_reason: string | null; retry_of_call_id: string | null; template_snapshot_id: string; request_snapshot_id: string;
  run_id: string | null; span_id: string | null; status: string; started_at: string; finished_at: string | null;
  duration_ms: number | null; error_code: string | null; outcome_scope: string;
}
export interface CallPage { items: { call: LLMCall; model: string | null; trace_available: boolean }[]; total: number; limit: number; offset: number }
export interface RequestMetadata {
  request_snapshot_id: string; template_snapshot_id: string; messages_hash: string; schema_hash: string; request_hash: string;
  model_parameters: Record<string, unknown>; client_config: Record<string, unknown>; created_at: string; expires_at: string | null;
}
export interface CallSummary {
  call: LLMCall; request_snapshot: RequestMetadata | null; trace_available: boolean;
  raw_availability: 'retained' | 'expired' | 'unavailable'; redaction: Record<string, string>;
}
export interface DiffLine { kind: 'equal' | 'replace' | 'insert' | 'delete'; left_number: number | null; right_number: number | null; left: string | null; right: string | null }
export interface DiffSection { key: string; label: string; availability: string; changed: boolean | null; lines: DiffLine[] }
export interface PromptDiff { left: TemplateSummary; right: TemplateSummary; content_hash_equal: boolean; sections: DiffSection[]; notice: string }
