import { ApiError, createAdminClient } from './client';
import {
  attributions, caseStates, datasetTypes, e2eVerdicts, executionStatuses, fileCheckStatuses, fileRoles, integrityStatuses, provenances,
  relations, runStatuses, runTypes, trustLabels,
} from '../types/evaluations';
import type {
  DatasetDetail, DatasetListPage, DatasetListQuery, RunDetail, RunListPage, RunListQuery,
} from '../types/evaluations';

const client = createAdminClient();
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown) => typeof v === 'string';
const optStr = (v: unknown) => v === null || typeof v === 'string';
const int = (v: unknown) => Number.isInteger(v);
const oneOf = (values: readonly string[], v: unknown) => typeof v === 'string' && values.includes(v);
const optOneOf = (values: readonly string[], v: unknown) => v === null || oneOf(values, v);
function invalid(): never { throw new ApiError('INVALID_RESPONSE', '评测接口返回结构不正确。'); }

export function isRunListPage(v: unknown): v is RunListPage { return page(v) && v.items.every(runItem); }
export function isDatasetListPage(v: unknown): v is DatasetListPage { return page(v) && v.items.every(datasetItem); }

function page(v: unknown): v is { items: unknown[]; total: number; page: number; page_size: number; discovery_warnings: unknown[] } {
  return object(v) && Array.isArray(v.items) && int(v.total) && int(v.page) && int(v.page_size) && Array.isArray(v.discovery_warnings)
    && v.discovery_warnings.every(w => object(w) && str(w.code));
}
function runItem(v: unknown) {
  return object(v) && str(v.run_id) && oneOf(runTypes, v.run_type) && optStr(v.created_at) && oneOf(runStatuses, v.lifecycle_status)
    && optOneOf(integrityStatuses, v.integrity_status) && optStr(v.agent_id) && optStr(v.agent_version)
    && optStr(v.dataset_id) && optStr(v.dataset_version) && optStr(v.dataset_hash) && int(v.case_count) && int(v.evaluated_case_count);
}
function datasetItem(v: unknown) {
  return object(v) && str(v.dataset_id) && optStr(v.dataset_version) && str(v.dataset_hash) && oneOf(datasetTypes, v.dataset_type)
    && int(v.case_count) && str(v.source) && v.freeze_status === 'UNDECLARED' && int(v.related_run_count)
    && int(v.hash_matched_run_count) && int(v.weak_path_run_count) && int(v.hash_mismatch_run_count);
}
const rate = (v: unknown) => v === null || (object(v) && int(v.numerator) && int(v.denominator) && (v.rate === null || typeof v.rate === 'number'));
function caseSummary(v: unknown) {
  return object(v) && str(v.case_id) && oneOf(caseStates, v.case_state) && optOneOf(executionStatuses, v.execution_status)
    && optStr(v.blocking_stage) && optOneOf(e2eVerdicts, v.e2e_verdict) && optStr(v.e2e_gate) && optStr(v.e2e_reason)
    && object(v.attribution) && oneOf(attributions, v.attribution.value) && str(v.attribution.basis)
    && optOneOf(integrityStatuses, v.case_integrity) && optOneOf(provenances, v.provenance);
}
export function isRunDetail(v: unknown): v is RunDetail {
  if (!object(v) || !str(v.run_id) || !oneOf(runTypes, v.run_type) || !oneOf(provenances, v.provenance)
    || !oneOf(runStatuses, v.lifecycle_status) || !Array.isArray(v.unverified_fields)) return false;
  const { integrity, metrics, case_counts: counts } = v;
  if (!object(integrity) || !optOneOf(integrityStatuses, integrity.status) || typeof integrity.trusted !== 'boolean'
    || !Array.isArray(integrity.reasons) || !integrity.reasons.every(str) || !Array.isArray(integrity.files)
    || !integrity.files.every(f => object(f) && optStr(f.ref) && oneOf(fileRoles, f.role) && optStr(f.case_id) && oneOf(fileCheckStatuses, f.status))) return false;
  if (!object(metrics) || !oneOf(trustLabels, metrics.trust) || typeof metrics.trusted !== 'boolean' || !Array.isArray(metrics.evaluators)
    || !Array.isArray(metrics.excluded) || !Array.isArray(metrics.included_case_ids)
    || ![metrics.e2e_confirmed_success_rate, metrics.decidable_pass_rate, metrics.evaluation_coverage, metrics.execution_completion_rate].every(rate)
    || !metrics.evaluators.every(e => object(e) && str(e.evaluator_id) && object(e.counts) && rate(e.error_rate) && rate(e.not_evaluated_rate))) return false;
  if (!object(counts) || !['total', 'present', 'missing', 'not_started', 'unreadable'].every(k => int(counts[k]))
    || ![v.missing_case_ids, v.not_started_case_ids, v.unreadable_case_ids, v.unverified_fields].every(ids => Array.isArray(ids) && ids.every(str))) return false;
  if (!optStr(v.agent_id) || !optStr(v.agent_version) || !optStr(v.dataset_id) || !optStr(v.dataset_version) || !optStr(v.dataset_hash)
    || !optStr(v.created_at) || !optStr(v.finished_at)) return false;
  if (!metrics.included_case_ids.every(str) || !metrics.excluded.every(e => object(e) && str(e.case_id)) || !optStr(metrics.oracle_evaluator_id)) return false;
  if (v.evaluator_manifest !== null && !(Array.isArray(v.evaluator_manifest) && v.evaluator_manifest.every(m => object(m) && str(m.evaluator_id)
    && optStr(m.evaluator_version) && optStr(m.config_sha256) && (m.requirement === null || oneOf(['required', 'optional', 'required_when_applicable'], m.requirement))
    && optStr(m.scope)))) return false;
  return Array.isArray(v.cases) && v.cases.every(caseSummary);
}
export function isDatasetDetail(v: unknown): v is DatasetDetail {
  return object(v) && str(v.dataset_id) && oneOf(datasetTypes, v.dataset_type) && optStr(v.dataset_version) && str(v.dataset_hash)
    && int(v.case_count) && str(v.source) && v.freeze_status === 'UNDECLARED' && Array.isArray(v.hash_variants)
    && v.hash_variants.every(h => object(h) && str(h.dataset_hash) && typeof h.matches_current_source === 'boolean' && int(h.run_count))
    && Array.isArray(v.related_runs)
    && v.related_runs.every(r => object(r) && str(r.run_id) && oneOf(runTypes, r.run_type) && optStr(r.created_at) && oneOf(relations, r.relation)
      && oneOf(runStatuses, r.lifecycle_status) && optOneOf(integrityStatuses, r.integrity_status) && optStr(r.recorded_dataset_hash))
    && Array.isArray(v.discovery_warnings) && v.discovery_warnings.every(w => object(w) && str(w.code));
}

function query(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value));
  const text = params.toString();
  return text ? '?' + text : '';
}

export const evaluationApi = {
  async listRuns(filters: RunListQuery, signal?: AbortSignal) {
    const value = await client.get<RunListPage>('evaluations/runs' + query({ ...filters }), { signal, cache: 'no-store' });
    if (!isRunListPage(value)) invalid();
    return value;
  },
  async getRun(runId: string, signal?: AbortSignal) {
    const value = await client.get<RunDetail>('evaluations/runs/' + encodeURIComponent(runId), { signal, cache: 'no-store' });
    if (!isRunDetail(value) || value.run_id !== runId) invalid();
    return value;
  },
  async listDatasets(filters: DatasetListQuery, signal?: AbortSignal) {
    const value = await client.get<DatasetListPage>('evaluations/datasets' + query({ ...filters }), { signal, cache: 'no-store' });
    if (!isDatasetListPage(value)) invalid();
    return value;
  },
  async getDataset(datasetId: string, signal?: AbortSignal) {
    const value = await client.get<DatasetDetail>('evaluations/datasets/' + encodeURIComponent(datasetId), { signal, cache: 'no-store' });
    if (!isDatasetDetail(value) || value.dataset_id !== datasetId) invalid();
    return value;
  },
};
