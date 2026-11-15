// Phase 2-C1 live contract check. Calls the real B1/B2 API through the Admin dev proxy using the
// same evaluationApi the pages use, then compares response field sets with admin/src/types/evaluations.ts.
// Run from admin/: npx vitest run --root ../docs/evaluations/evaluation-admin-c1-2026-11-13 --environment node
import { writeFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const ORIGIN = process.env.C1_ADMIN_ORIGIN || 'http://127.0.0.1:5174';
Object.defineProperty(globalThis, 'location', { value: new URL(ORIGIN), configurable: true });

const KEYS = {
  runItem: ['run_id', 'run_type', 'created_at', 'lifecycle_status', 'integrity_status', 'agent_id', 'agent_version', 'dataset_id',
    'dataset_version', 'dataset_hash', 'case_count', 'evaluated_case_count'],
  datasetItem: ['dataset_id', 'dataset_version', 'dataset_hash', 'dataset_type', 'case_count', 'source', 'freeze_status',
    'related_run_count', 'hash_matched_run_count', 'weak_path_run_count', 'hash_mismatch_run_count'],
  page: ['items', 'total', 'page', 'page_size', 'discovery_warnings'],
  runDetail: ['run_id', 'run_type', 'provenance', 'provenance_notice', 'agent_id', 'agent_version', 'dataset_id', 'dataset_version',
    'dataset_hash', 'lifecycle_status', 'created_at', 'finished_at', 'execution_config', 'unverified_fields', 'projection', 'integrity',
    'evaluator_manifest', 'evaluator_manifest_notice', 'case_counts', 'missing_case_ids', 'not_started_case_ids', 'unreadable_case_ids',
    'recorded_distribution', 'metrics', 'cases', 'redactions'],
  metrics: ['trust', 'trusted', 'notice', 'oracle_evaluator_id', 'included_case_ids', 'excluded', 'counts', 'e2e_confirmed_success_rate',
    'decidable_pass_rate', 'evaluation_coverage', 'execution_completion_rate', 'evaluators'],
  integrity: ['status', 'trusted', 'notice', 'reasons', 'basis', 'files', 'case_status'],
  caseSummary: ['case_id', 'case_state', 'execution_status', 'blocking_stage', 'failure_origin', 'e2e_verdict', 'e2e_gate', 'e2e_reason',
    'attribution', 'case_integrity', 'provenance'],
  datasetDetail: ['dataset_id', 'dataset_type', 'dataset_version', 'dataset_hash', 'case_count', 'source', 'freeze_status', 'freeze_notice',
    'hash_variants', 'related_runs', 'discovery_warnings'],
  relatedRun: ['run_id', 'run_type', 'created_at', 'lifecycle_status', 'integrity_status', 'recorded_dataset_id', 'recorded_dataset_hash', 'relation'],
};
const sorted = (o: object) => Object.keys(o).sort();
const same = (o: object, keys: string[]) => expect(sorted(o)).toEqual([...keys].sort());

it('pages and the real API agree on every field', async () => {
  const { evaluationApi } = await import('../../../admin/src/api/evaluations');
  const { ApiError } = await import('../../../admin/src/api/client');
  const log: Record<string, unknown> = { origin: ORIGIN, checked_at: new Date().toISOString() };

  const runs = await evaluationApi.listRuns({ page_size: 100 });
  same(runs, KEYS.page); runs.items.forEach(item => same(item, KEYS.runItem));
  const datasets = await evaluationApi.listDatasets({ page_size: 100 });
  same(datasets, KEYS.page); datasets.items.forEach(item => same(item, KEYS.datasetItem));
  log.runs = runs.items.map(r => ({ run_id: r.run_id, run_type: r.run_type, lifecycle: r.lifecycle_status, integrity: r.integrity_status, cases: r.case_count }));
  log.datasets = datasets.items.map(d => ({ dataset_id: d.dataset_id, version: d.dataset_version, freeze: d.freeze_status, related: d.related_run_count }));

  const details: Record<string, unknown> = {};
  for (const item of runs.items) {
    const run = await evaluationApi.getRun(item.run_id);
    same(run, KEYS.runDetail); same(run.metrics, KEYS.metrics); same(run.integrity, KEYS.integrity);
    run.cases.forEach(c => same(c, KEYS.caseSummary));
    expect(run.lifecycle_status).toBe(item.lifecycle_status);
    expect(run.integrity.status).toBe(item.integrity_status);
    details[run.run_id] = { trust: run.metrics.trust, cases: Object.fromEntries(run.cases.map(c => [c.case_id, [c.execution_status, c.e2e_verdict, c.e2e_gate, c.case_integrity]])) };
  }
  log.run_details = details;

  const legacy = await evaluationApi.getRun('gf_20261112-143406_cde1fd');
  const byId = Object.fromEntries(legacy.cases.map(c => [c.case_id, c]));
  for (const id of ['RF-01', 'RF-03']) expect([byId[id].execution_status, byId[id].e2e_verdict]).toEqual(['BLOCKED', 'FAIL']);
  expect([byId['RF-04'].execution_status, byId['RF-04'].e2e_verdict]).toEqual(['FAILED', 'FAIL']);
  for (const id of ['RF-02', 'RF-05']) expect([byId[id].e2e_verdict, byId[id].case_integrity]).toEqual(['PASS', 'UNVERIFIED']);
  const oracle = legacy.metrics.evaluators.find(e => e.evaluator_id === legacy.metrics.oracle_evaluator_id);
  expect(oracle?.counts.NOT_EVALUATED).toBe(3);
  expect(legacy.metrics.trusted).toBe(false);

  for (const item of datasets.items) {
    const detail = await evaluationApi.getDataset(item.dataset_id);
    same(detail, KEYS.datasetDetail); detail.related_runs.forEach(r => same(r, KEYS.relatedRun));
    expect(detail.freeze_status).toBe('UNDECLARED');
  }

  const errors: Record<string, unknown> = {};
  for (const [label, call] of [
    ['run_404', () => evaluationApi.getRun('gf_20991212-000000_aaaaaa')],
    ['run_422', () => evaluationApi.getRun('not-a-run')],
    ['dataset_404', () => evaluationApi.getDataset('no-such-dataset')],
    ['list_422', () => evaluationApi.listRuns({ status: 'BROKEN' })],
  ] as const) {
    try { await call(); errors[label] = 'unexpected success'; }
    catch (e) { errors[label] = e instanceof ApiError ? { status: e.status, server_code: e.serverCode } : String(e); }
  }
  expect(errors).toEqual({
    run_404: { status: 404, server_code: 'EVALUATION_RUN_NOT_FOUND' },
    run_422: { status: 422, server_code: 'VALIDATION_ERROR' },
    dataset_404: { status: 404, server_code: 'EVALUATION_DATASET_NOT_FOUND' },
    list_422: { status: 422, server_code: 'VALIDATION_ERROR' },
  });
  log.errors = errors;

  const text = JSON.stringify(log);
  expect(text).not.toMatch(/\/Users\/|https?:\/\/(?!127\.0\.0\.1)/);
  writeFileSync(new URL('./live-contract-result.json', import.meta.url), JSON.stringify(log, null, 2) + '\n');
});
