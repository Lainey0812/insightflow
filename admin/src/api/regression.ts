import { ApiError, createAdminClient } from './client';
import { caseStatuses, regressionChanges } from '../types/regression';
import type { RegressionCompare, RegressionRun, RegressionRunPage } from '../types/regression';

const client = createAdminClient();
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
function invalid(): never { throw new ApiError('INVALID_RESPONSE', '回归接口返回结构不正确。'); }
function runItem(v: unknown) {
  return object(v) && typeof v.run_id === 'string' && typeof v.label === 'string' && ['finished', 'incomplete'].includes(String(v.state))
    && object(v.summary) && typeof v.summary.passed === 'number' && typeof v.summary.auto_total === 'number' && object(v.environment);
}
export function isRegressionCompare(v: unknown): v is RegressionCompare {
  return object(v) && v.schema_version === 'regression-compare-v1' && runItem(v.left) && runItem(v.right) && object(v.counts) && Array.isArray(v.cases)
    && v.cases.every(c => object(c) && typeof c.case_id === 'string' && regressionChanges.includes(c.change as never)
      && (c.left_status === null || caseStatuses.includes(c.left_status as never)) && (c.right_status === null || caseStatuses.includes(c.right_status as never))
      && Array.isArray(c.check_changes));
}

export const regressionApi = {
  async list(signal?: AbortSignal) {
    const value = await client.get<RegressionRunPage>('regression-runs', { signal, cache: 'no-store' });
    if (!value || value.schema_version !== 'regression-run-page-v1' || !Array.isArray(value.items) || !value.items.every(runItem)) invalid();
    return value;
  },
  async get(id: string, signal?: AbortSignal) {
    const value = await client.get<RegressionRun>('regression-runs/' + encodeURIComponent(id), { signal, cache: 'no-store' });
    if (!runItem(value) || value.run_id !== id || !Array.isArray(value.cases)) invalid();
    return value;
  },
  async compare(left: string, right: string, signal?: AbortSignal) {
    const value = await client.get<RegressionCompare>('regression-compare?' + new URLSearchParams({ left, right }), { signal, cache: 'no-store' });
    if (!isRegressionCompare(value) || value.left.run_id !== left || value.right.run_id !== right) invalid();
    return value;
  },
};
