// Mirrors backend/app/evaluation/admin_views.py and contracts.py (Phase 2-B1/B2).
// Enumerations are declared once here; pages import them instead of redefining values.

export const runTypes = ['golden', 'tc_regression'] as const;
export const datasetTypes = ['golden', 'tc'] as const;
export const runStatuses = ['FINISHED', 'INCOMPLETE'] as const;
export const integrityStatuses = ['VERIFIED', 'INVALID', 'INCOMPLETE', 'UNVERIFIED'] as const;
export const executionStatuses = ['PENDING', 'RUNNING', 'WAITING_APPROVAL', 'COMPLETED', 'BLOCKED', 'FAILED', 'TIMEOUT', 'CANCELLED'] as const;
export const verdicts = ['PASS', 'FAIL', 'NOT_EVALUATED', 'EVALUATOR_ERROR'] as const;
export const e2eVerdicts = [...verdicts, 'INFRA_ERROR'] as const;
export const provenances = ['recorded', 'legacy_projection'] as const;
export const relations = ['hash_match', 'weak_path', 'hash_mismatch'] as const;
export const trustLabels = ['verified', 'partial_verified', 'unverified', 'incomplete', 'none'] as const;
export const caseStates = ['present', 'missing', 'not_started', 'unreadable'] as const;
export const attributions = ['none', 'agent_execution', 'business_quality', 'evaluator_error', 'evaluation_infrastructure',
  'undetermined', 'evidence_integrity', 'not_executed'] as const;
export const fileRoles = ['config', 'summary', 'case_result', 'case_trace', 'artifact'] as const;
export const fileCheckStatuses = ['ok', 'mismatch', 'missing', 'outside_run', 'unexpected_ref'] as const;

export type RunType = typeof runTypes[number];
export type DatasetType = typeof datasetTypes[number];
export type RunStatus = typeof runStatuses[number];
export type IntegrityStatus = typeof integrityStatuses[number];
export type ExecutionStatus = typeof executionStatuses[number];
export type Verdict = typeof verdicts[number];
export type E2EVerdict = typeof e2eVerdicts[number];
export type Provenance = typeof provenances[number];
export type Relation = typeof relations[number];
export type TrustLabel = typeof trustLabels[number];
export type CaseState = typeof caseStates[number];
export type Attribution = typeof attributions[number];
export type FileRole = typeof fileRoles[number];
export type FileCheckStatus = typeof fileCheckStatuses[number];
export type FreezeStatus = 'UNDECLARED';
export type Requirement = 'required' | 'optional' | 'required_when_applicable';
export type Scope = 'e2e' | 'node';
export type FailureOrigin = 'agent' | 'infrastructure';

export interface DiscoveryWarning { code: string; root_id: string | null; entry: string | null; detail: string | null }

export interface RunListItem {
  run_id: string; run_type: RunType; created_at: string | null; lifecycle_status: RunStatus;
  integrity_status: IntegrityStatus | null; agent_id: string | null; agent_version: string | null;
  dataset_id: string | null; dataset_version: string | null; dataset_hash: string | null;
  case_count: number; evaluated_case_count: number;
}
export interface RunListPage { items: RunListItem[]; total: number; page: number; page_size: number; discovery_warnings: DiscoveryWarning[] }

export interface DatasetListItem {
  dataset_id: string; dataset_version: string | null; dataset_hash: string; dataset_type: DatasetType;
  case_count: number; source: string; freeze_status: FreezeStatus; related_run_count: number;
  hash_matched_run_count: number; weak_path_run_count: number; hash_mismatch_run_count: number;
}
export interface DatasetListPage { items: DatasetListItem[]; total: number; page: number; page_size: number; discovery_warnings: DiscoveryWarning[] }

export interface FileCheckView { ref: string | null; role: FileRole; case_id: string | null; status: FileCheckStatus }
export interface IntegrityView {
  status: IntegrityStatus | null; trusted: boolean; notice: string; reasons: string[]; basis: string | null;
  files: FileCheckView[]; case_status: Record<string, IntegrityStatus>;
}
export interface EvaluatorManifestItem {
  evaluator_id: string; evaluator_version: string | null; config_sha256: string | null;
  required: boolean | null; requirement: Requirement | null; scope: Scope | null;
}
export interface Rate { numerator: number; denominator: number; rate: number | null }
export interface EvaluatorHealth { evaluator_id: string; counts: Record<string, number>; error_rate: Rate; not_evaluated_rate: Rate }
export interface TrustedMetrics {
  trust: TrustLabel; trusted: boolean; notice: string; oracle_evaluator_id: string | null;
  included_case_ids: string[]; excluded: Record<string, string>[]; counts: Record<string, unknown> | null;
  e2e_confirmed_success_rate: Rate | null; decidable_pass_rate: Rate | null;
  evaluation_coverage: Rate | null; execution_completion_rate: Rate | null; evaluators: EvaluatorHealth[];
}
export interface Attributed { value: Attribution; basis: string }
export interface CaseSummary {
  case_id: string; case_state: CaseState; execution_status: ExecutionStatus | null; blocking_stage: string | null;
  failure_origin: FailureOrigin | null; e2e_verdict: E2EVerdict | null; e2e_gate: string | null; e2e_reason: string | null;
  attribution: Attributed; case_integrity: IntegrityStatus | null; provenance: Provenance | null;
}
export interface CaseCounts { total: number; present: number; missing: number; not_started: number; unreadable: number }
export interface Derivation { value: unknown; sources: string[]; basis: string }
export interface RunDetail {
  run_id: string; run_type: RunType; provenance: Provenance; provenance_notice: string;
  agent_id: string | null; agent_version: string | null; dataset_id: string | null; dataset_version: string | null;
  dataset_hash: string | null; lifecycle_status: RunStatus; created_at: string | null; finished_at: string | null;
  execution_config: Record<string, unknown>; unverified_fields: string[]; projection: Record<string, Derivation>;
  integrity: IntegrityView; evaluator_manifest: EvaluatorManifestItem[] | null; evaluator_manifest_notice: string | null;
  case_counts: CaseCounts; missing_case_ids: string[]; not_started_case_ids: string[]; unreadable_case_ids: string[];
  recorded_distribution: Record<string, Record<string, number>>; metrics: TrustedMetrics; cases: CaseSummary[];
  redactions: Record<string, unknown>[];
}

export interface RelatedRun {
  run_id: string; run_type: RunType; created_at: string | null; lifecycle_status: RunStatus;
  integrity_status: IntegrityStatus | null; recorded_dataset_id: string | null; recorded_dataset_hash: string | null; relation: Relation;
}
export interface HashVariant { dataset_hash: string; matches_current_source: boolean; run_count: number }
export interface DatasetDetail {
  dataset_id: string; dataset_type: DatasetType; dataset_version: string | null; dataset_hash: string; case_count: number;
  source: string; freeze_status: FreezeStatus; freeze_notice: string; hash_variants: HashVariant[];
  related_runs: RelatedRun[]; discovery_warnings: DiscoveryWarning[];
}

export interface RunListQuery { page?: number | string; page_size?: number | string; run_type?: string; status?: string; integrity_status?: string }
export interface DatasetListQuery { page?: number | string; page_size?: number | string; dataset_type?: string }
