export type SessionStatus = 'CREATED' | 'PREPARING' | 'PROFILING' | 'PARSING_INTENT' | 'PLANNING' | 'VALIDATING' | 'WAITING_FOR_CLARIFICATION' | 'AWAITING_APPROVAL' | 'APPROVED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
export type AnalysisMode = 'goal_driven' | 'exploratory' | 'undetermined';
export type Operation = 'summary' | 'trend' | 'category' | 'region';
export interface Provenance { source: 'mock' | 'uploaded' | 'llm' | 'input_guard'; dataset: string; dataset_version?: string | null; plan_version: number | null; notice: string }
export interface Task { id: string; title: string; description: string; operation: Operation; priority: number }
export interface Plan { version: number; tasks: Task[]; reason: string; created_at: string; provenance: Provenance }
export interface Message { id: string; role: 'user' | 'assistant' | 'system'; kind: 'text' | 'plan' | 'report' | 'status' | 'error'; content: string; plan_version: number | null; created_at: string }
export interface TaskResult { task_id: string; operation: Operation; title: string; labels: string[]; values: number[]; evidence: string }
export interface ReportSection { title: string; insight: string; evidence: string; result: TaskResult; chart_option: Record<string, unknown> }
export interface Report { title: string; sections: ReportSection[]; provenance: Provenance; generated_at: string }
export interface FileInfo { id: string; name: string; size: number; extension: string; content_sha256?: string | null }
export interface DatasetRef { dataset_id: string; dataset_version: string }
export interface UnverifiedConstraint { raw_text: string; validation_status: 'unverified' }
export type IntentUncertainty = {
  id: string; action: 'clarify' | 'defer' | 'annotate'; resolve_at: 'before_planning' | 'plan_approval' | 'before_execution';
} & ({ issue: string; reason: string; description?: string; impact?: string } | { description: string; impact: string; issue?: string; reason?: string });
export interface ParsedIntent {
  analysis_mode: AnalysisMode; next_action: 'proceed' | 'clarify';
  analysis_goal: { analysis_object: string | null; business_goal: string | null; decision_goal: string | null };
  constraints: { time_range: UnverifiedConstraint | null; filters: UnverifiedConstraint[]; metric_requirements: UnverifiedConstraint[]; analysis_limits: UnverifiedConstraint[] };
  uncertainties: IntentUncertainty[];
  clarification_questions: string[];
}
export interface IntentArtifact extends ParsedIntent {
  user_query: string; clarification_answers: string[]; dataset_ref: DatasetRef;
  parse_origin: 'llm' | 'input_guard'; llm: { provider: string; model: string | null; is_mock: boolean } | null;
  provenance: Provenance; parser_version: '1.0' | '1.1';
  prompt_version?: string | null; llm_attempts?: number | null; parse_id?: string | null;
}
export type PhysicalType = 'null' | 'boolean' | 'integer' | 'float' | 'string' | 'date' | 'datetime' | 'time' | 'mixed';
export type LogicalType = 'empty' | 'boolean' | 'integer' | 'number' | 'date' | 'datetime' | 'time' | 'text' | 'mixed';
export interface ProfileOptions { header_row: number; sheet_name: string | null; encoding: 'utf-8-sig' | 'gb18030'; delimiter: ',' | ';' | '\t' | '|' }
export interface FieldProfile {
  field_id: string; position: number; original_name: string | null; display_name: string;
  physical_type: PhysicalType; logical_type: LogicalType;
  missing_count: number; missing_rate: number; non_missing_count: number; unique_count: number;
  physical_type_counts: Partial<Record<PhysicalType, number>>;
  logical_type_counts: Partial<Record<LogicalType, number>>;
  samples: { value: string | number | boolean; physical_type: PhysicalType; truncated: boolean }[];
}
export interface DatasetProfile extends DatasetRef {
  schema_version: '1.0'; profiler_version: string; content_sha256: string; file_name: string;
  file_format: 'csv' | 'xlsx'; sheet_name: string | null; available_sheets: string[]; options: ProfileOptions;
  row_count: number; column_count: number; total_cell_count: number;
  missing_cell_count: number; missing_cell_rate: number; duplicate_row_count: number; duplicate_row_rate: number;
  fields: FieldProfile[];
  quality_issues: { code: string; severity: 'warning' | 'info'; message: string; affected_count: number; field_ids: string[]; example_row_numbers: number[] }[];
  provenance: Provenance;
}
export interface SessionSummary { id: string; title: string; status: SessionStatus; updated_at: string; data_source: 'mock' | 'uploaded' }
export interface ReportGeneration {
  execution_id: string; session_id: string; status: 'queued' | 'generating' | 'completed' | 'failed' | 'unavailable';
  attempt: number; report_id: string | null; error: {code: string; message: string; retryable: boolean} | null;
  queued_at: string; started_at: string | null; finished_at: string | null;
}
export interface Session extends SessionSummary {
  workflow_id?: string | null;
  report_generations?: ReportGeneration[];
  workflow_kind?: 'legacy_mock' | 'manual_review' | 'real_v1';
  workflow_events?: {status: SessionStatus; recorded_at: string}[];
  revision: number; created_at: string; file: FileInfo; user_goal: string; analysis_mode: AnalysisMode;
  current_plan_version: number | null; approved_plan_version: number | null;
  plans: Plan[]; messages: Message[]; report: Report | null;
  review_access_token?: string;
  review_plan?: PlanVersion | null; review_status?: ReviewStatus | null; engine_execution_ids?: string[];
  profile?: DatasetProfile | { rows: number; columns: string[]; quality_notes: string[]; provenance: Provenance } | null;
  dataset_ref?: DatasetRef | null;
  intent?: IntentArtifact | { mode: AnalysisMode; goal: string; ambiguities: string[]; provenance: Provenance } | null;
  intent_history?: IntentArtifact[]; clarification_answers?: string[];
  error: { code: string; message: string; node_name: string | null; retryable: boolean } | null;
}
export interface Health { status: string; mode: string; service: string; version: string }
export const statusLabels: Record<SessionStatus, string> = {
  CREATED: '已创建', PREPARING: '准备中', WAITING_FOR_CLARIFICATION: '待补充需求', AWAITING_APPROVAL: '待确认计划',
  PROFILING: '数据画像中', PARSING_INTENT: '理解需求中', PLANNING: '生成计划中', VALIDATING: '校验计划中',
  APPROVED: '计划已确认', RUNNING: '分析中', COMPLETED: '已完成', FAILED: '处理失败',
};

export type ReviewStatus = 'awaiting_review' | 'validating' | 'awaiting_approval' | 'approved' | 'executing' | 'completed' | 'execution_failed';
export interface AnalysisTaskV1 {
  task_id: string; title: string; business_question: string; priority: 'P0' | 'P1' | 'P2'; priority_reason: string;
  requirement_ids: string[]; depends_on: string[]; missing_inputs?: string[];
  steps: {step_id: string; operation: string; params: Record<string, unknown>}[];
}
export interface AnalysisPlanV1 extends DatasetRef {
  plan_id: string; plan_version: number; tasks: AnalysisTaskV1[];
  core_requirements: {requirement_id: string; description: string}[];
}
export interface ValidatedAnalysisPlan {
  plan: AnalysisPlanV1;
  validation_results: {task_id: string; feasibility: 'F0' | 'F1' | 'F2'; executable: boolean; reason_code: string; validation_issues: {code: string; message: string; step_id?: string | null}[]}[];
  coverage_status: 'complete' | 'partial' | 'blocked'; executable_task_ids: string[]; blocked_task_ids: string[];
  unmet_core_requirements: {requirement_id: string; description: string}[];
  validation_version: string; registry_version: string; intent_snapshot: ParsedIntent;
}
export interface PlanVersion extends DatasetRef {
  session_id: string; plan_id: string; plan_version: number; validation_version: string;
  created_at: string; change_type: string; change_summary: string; validated_plan: ValidatedAnalysisPlan;
}
export interface AnalysisBasis {
  version: string; digest: string; plan_version: number;
  row_grain: 'unknown' | 'record' | 'entity' | 'detail'; entity_field_id: string | null;
  metrics: {task_id:string; step_id:string; alias:string; field_id:string|null; label:string; function:string; basis:string; unit_status:string}[];
  entity_field_options: {field_id:string; label:string; unique_non_null:boolean}[];
}
export interface ReviewDataOverview {
  dataset_id:string; dataset_version:string; file_name:string; sheet_name:string|null;
  row_count:number; column_count:number; missing_cell_count:number; duplicate_row_count:number;
  fields_with_missing:{name:string;missing_count:number}[]; quality_notes:string[];
  cleaning_status:'not_performed'; cleaning_notice:string; sample_notice:string;
}
export interface ReviewPresentation {
  data_overview?:ReviewDataOverview|null;
  analysis_basis?: AnalysisBasis | null;
  report_capacity?: {policy_version:string; supported:boolean; metric_count:number; core_metric_count:number;
    estimated_batches:number; max_groups_per_call:number; max_groups:number; max_batches:number;
    estimated_metadata_bytes:number; context_estimate_only:boolean; message:string} | null;
  session_id: string; revision: number; plan_id: string; plan_version: number;
  goal: string; coverage: string;
  conditions: {label: string; text: string; verification: string; source: string}[];
  directions: {task_id: string; title: string; question: string; importance: string; reason: string;
    readiness: string; executable: boolean; details: string[]; gaps: string[]; can_remove: boolean}[];
  issues: {code: string; message: string; next_step: string}[];
  warnings: {id: string; label: string}[];
  can_approve: boolean; can_execute: boolean;
  audit: {all_verified: boolean; digest: string; items: {source: string; raw_text: string; status: string; message: string}[]};
  technical_details: Record<string, unknown>;
}
export interface ExecutionResultV1 extends DatasetRef {
  execution_id: string; approval_id: string; plan_id: string; plan_version: number;
  execution_status: 'success' | 'partial_success' | 'failed'; warnings: string[]; tasks: {task_id: string; status: string; failure_reason: string | null;
    row_count: number; result: import('./report').ResultTable | null}[];
}

export interface ScopeTarget {field_id:string;filter_index:number;keyword:string}
export interface ScopePreview {scope:{field_id:string;keyword:string;mode:'exact'|'normalized_contains';values:string[]};matched_row_count:number;dataset_row_count:number;summary:string;preview_digest:string;dataset_id:string;dataset_version:string}
