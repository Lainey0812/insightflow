export type RunStatus = 'queued' | 'running' | 'waiting_input' | 'waiting_approval' | 'complete' | 'partial' | 'unavailable' | 'failed' | 'interrupted';
export type Metadata = Record<string, unknown>;
export interface RunManifest {
  prompt_template_snapshots?: Record<string, string>;
  git?: Metadata; input_sha256?: Record<string, string>; capture_scope?: string;
  schema_version?: string; bindings?: Metadata; versions?: Metadata;
  model_config_snapshot?: Metadata; source_sha256?: Record<string, string>; raw_content_retained?: boolean;
}
export interface TraceRun {
  run_id: string; kind?: string; session_id?: string; execution_id?: string | null; workflow_run_id?: string | null; attempt?: number;
  retry_of_run_id?: string | null; status: RunStatus; queued_at?: string; started_at?: string | null;
  finished_at?: string | null; recovered_at?: string | null; duration_ms?: number | null;
  report_id?: string | null; error_code?: string | null; integrity?: string; manifest?: RunManifest;
}
export interface TraceSpan {
  span_id: string; run_id: string; parent_span_id?: string | null; node_key?: string | null; node_attempt?: number | null; name: string; status: string;
  started_at?: string; finished_at?: string | null; recovered_at?: string | null;
  duration_ms?: number | null; error_code?: string | null; attributes?: Metadata;
}
export interface TraceEvent {
  event_id: string; run_id: string; span_id?: string | null; sequence: number;
  event_type: string; recorded_at?: string; payload?: Metadata;
}
export interface RunPage {
  items: TraceRun[]; total: number; limit: number; offset: number;
  collector_degraded?: boolean; coverage_notice?: string;
}
export interface RunDetail {
  run: TraceRun; business_source?: Metadata; collector_degraded?: boolean; coverage_notice?: string;
}
export interface EventPage { items: TraceEvent[]; limit: number; offset: number }
export interface CompareCheck { key: string; left?: unknown; right?: unknown; status: 'same' | 'different' | 'unknown'; basis?: string }
export interface SavedArtifact { availability: 'available' | 'unknown'; source?: string | null; content_sha256?: string; snapshot_id?: string; captured_at?: string; projection?: Metadata | null; reason?: string }
export interface RunComparison {
  left: TraceRun; right: TraceRun; scope: string; live: boolean;
  comparability: { status: 'comparable' | 'partially_comparable' | 'unknown'; checks: CompareCheck[]; bindings: CompareCheck[]; versions: CompareCheck[]; models: CompareCheck[]; git: CompareCheck; notice: string };
  source_files?: CompareCheck[];
  spans: { node_key: string; node_attempt?: number | null; match_basis: string; left?: TraceSpan | null; right?: TraceSpan | null }[];
  artifacts: { left: Record<string, SavedArtifact>; right: Record<string, SavedArtifact> };
  diagnostics: { left: { span_id?: string | null; event_type: string; sequence: number; payload: Metadata }[]; right: { span_id?: string | null; event_type: string; sequence: number; payload: Metadata }[] };
}
