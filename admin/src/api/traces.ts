import { ApiError, createAdminClient } from './client';
import type { EventPage, RunDetail, RunPage, TraceRun, TraceSpan, RunComparison } from '../types/traces';

const client = createAdminClient();
function invalid(): never { throw new ApiError('INVALID_RESPONSE', '追踪接口返回结构不正确。'); }
export const traceApi = {
  async runs(query: string, signal?: AbortSignal): Promise<RunPage> {
    const value = await client.get<RunPage>('runs?' + query, { signal, cache: 'no-store' });
    if (!value || !Array.isArray(value.items) || !Number.isInteger(value.total) || value.total < 0 ||
        value.items.some(run => !run || typeof run.run_id !== 'string' || typeof run.status !== 'string')) invalid();
    return value;
  },
  async run(id: string, signal?: AbortSignal): Promise<RunDetail> {
    const value = await client.get<RunDetail>('runs/' + encodeURIComponent(id), { signal, cache: 'no-store' });
    if (!value?.run || value.run.run_id !== id || typeof value.run.status !== 'string') invalid();
    return value;
  },
  async workflow(sessionId: string, signal?: AbortSignal): Promise<TraceRun | null> {
    const value = await client.get<{ run?: TraceRun | null }>('workflows/' + encodeURIComponent(sessionId), { signal, cache: 'no-store' });
    if (!value || typeof value !== 'object') invalid();
    if (!value.run) return null;
    if (value.run.session_id !== sessionId || typeof value.run.run_id !== 'string' || typeof value.run.status !== 'string') invalid();
    return value.run;
  },
  async spans(id: string, signal?: AbortSignal): Promise<TraceSpan[]> {
    const value = await client.get<{ items: TraceSpan[] }>('runs/' + encodeURIComponent(id) + '/spans', { signal, cache: 'no-store' });
    // A report run can project spans that still belong to the workflow root. Keep that run_id.
    if (!value || !Array.isArray(value.items) || value.items.some(s => !s || typeof s.run_id !== 'string' || typeof s.span_id !== 'string' || typeof s.name !== 'string')) invalid();
    return value.items;
  },
  async events(id: string, offset: number, signal?: AbortSignal): Promise<EventPage> {
    const value = await client.get<EventPage>(`spans/${encodeURIComponent(id)}/events?limit=100&offset=${offset}`, { signal, cache: 'no-store' });
    if (!value || !Array.isArray(value.items) || value.items.some(e => !e || e.span_id !== id || typeof e.event_id !== 'string')) invalid();
    return value;
  },
  async comparison(left: string, right: string, signal?: AbortSignal): Promise<RunComparison> {
    const query = new URLSearchParams({ left, right });
    const value = await client.get<RunComparison>('comparison?' + query, { signal, cache: 'no-store' });
    if (!value || value.left?.run_id !== left || value.right?.run_id !== right || !Array.isArray(value.spans) ||
        !value.comparability || !Array.isArray(value.comparability.checks) || !value.artifacts || !value.diagnostics) invalid();
    return value;
  },
  grant(token: string) { return client.request('access', { method: 'POST', headers: { 'X-Admin-Token': token }, cache: 'no-store' }); },
  revoke() { return client.request('access', { method: 'DELETE', headers: { 'X-Admin-Request': '1' }, cache: 'no-store' }); },
};
