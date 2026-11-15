import { ApiError, createAdminClient } from './client';
import { replayOutcomes } from '../types/replay';
import type { ReplayRun, ReplayRunPage } from '../types/replay';

const client = createAdminClient();
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
function invalid(): never { throw new ApiError('INVALID_RESPONSE', '回放接口返回结构不正确。'); }
function runItem(v: unknown) {
  return object(v) && typeof v.run_id === 'string' && typeof v.label === 'string' && ['finished', 'incomplete'].includes(String(v.state))
    && object(v.environment) && typeof v.environment.model === 'string' && object(v.summary)
    && typeof v.summary.auto_total === 'number' && typeof v.summary.cleared === 'number';
}
export function isReplayRun(v: unknown): v is ReplayRun {
  if (!runItem(v)) return false;
  const cases = (v as { cases?: unknown }).cases;
  return Array.isArray(cases) && cases.every(c => object(c) && typeof c.case_id === 'string' && replayOutcomes.includes(c.outcome as never));
}

export const replayApi = {
  async list(signal?: AbortSignal) {
    const value = await client.get<ReplayRunPage>('replay-runs', { signal, cache: 'no-store' });
    if (!value || value.schema_version !== 'replay-run-page-v1' || !Array.isArray(value.items) || !value.items.every(runItem)) invalid();
    return value;
  },
  async get(id: string, signal?: AbortSignal) {
    const value = await client.get<ReplayRun>('replay-runs/' + encodeURIComponent(id), { signal, cache: 'no-store' });
    if (!isReplayRun(value) || value.run_id !== id) invalid();
    return value;
  },
};
