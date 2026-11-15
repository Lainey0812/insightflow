export type ChartType = 'bar' | 'line' | 'pie' | 'kpi' | 'table';
export type Cell = string | number | boolean | null;
export interface ResultColumn { field: string; label: string; logical_type: string; role: 'dimension' | 'metric'; unit: string | null }
export interface ResultTable { result_id: string; columns: ResultColumn[]; rows: Record<string, Cell>[]; truncated: boolean; total_result_rows: number }
export interface Evidence {
  evidence_id: string; task_id: string; data_ref: string; result_field: string; evidence_type: string;
  value: Record<string, Cell>; scope: string; calculation: string; statement: string;
  source_row_indices: number[]; related_result_refs: string[];
}
export interface ChartSpec {
  chart_id: string; task_id: string; title: string; chart_type: ChartType; dimension: string | null;
  metrics: string[]; data_ref: string; supported_chart_types: ChartType[]; evidence_refs: string[];
  display_limit: number; order: 'value_desc' | 'dimension_asc' | 'original'; note: string | null;
}
export interface Insight {
  insight_id: string; task_id: string; fact: string; finding: string; implication: string; recommendation: string;
  evidence_refs: string[]; limitations: string[];
}
export interface AnalysisReport {
  report_id: string; execution_id: string; dataset_id: string; dataset_version: string; plan_version: number;
  report_status: 'complete' | 'partial' | 'unavailable'; goal_coverage: 'complete' | 'partial' | 'blocked';
  analysis_goal: string; dataset_name: string; dataset_row_count: number; execution_source: 'engine' | 'imported';
  summary: { headline: string; overview: string; evidence_refs: string[] };
  key_metrics: { label: string; value: Cell; unit: string | null; evidence_ref: string }[];
  insights: Insight[]; charts: ChartSpec[]; recommendations: { text: string; evidence_refs: string[] }[];
  limitations: string[]; uncompleted_tasks: { task_id: string; title: string; priority: string; reason: string }[];
  evidence: Evidence[]; result_data: Record<string, ResultTable>;
  task_metadata: Record<string, { title: string; priority: string }>;
  execution_metadata: Record<string, { approved_scope?: string[]; original_query?: string | null; sample_definition?: string; effective_row_count?: number; valid_sample_count?: number | null }>;
  fact_validation: string; llm: { provider: string; model: string | null; is_mock: boolean } | null;
  preview_url: string; download_url: string; generated_at: string;
}

export interface ReportPresentation {
  presentation_version: 'business-report-v1' | 'business-report-v1.1'; report_id: string; kind: 'ranking' | 'general';
  title: string; subtitle: string; executive_summary: string;
  key_metrics: {label: string; display_value: string; caption: string; evidence_refs: string[]}[];
  findings: {title: string; body: string; evidence_refs: string[]}[];
  recommendations: string[]; data_notes: string[]; scope: string[]; evidence: Evidence[];
}
