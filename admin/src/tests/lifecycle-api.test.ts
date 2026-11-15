import { expect, it, vi } from 'vitest';
import { lifecycleApi } from '../api/lifecycle';
import { lifecycleFixture } from './lifecycle-fixtures';
it('queries only the authenticated read endpoint and validates actual session identity', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(lifecycleFixture())));
  vi.stubGlobal('fetch', fetcher);
  const response = await lifecycleApi.get('session_fixture');
  expect(response.business_lifecycle.status).toBe('succeeded');
  expect(fetcher.mock.calls[0][0]).toBe('http://localhost:5174/api/v1/admin/workflows/session_fixture/lifecycle');
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'GET', cache: 'no-store', credentials: 'same-origin' });
});
it('accepts the five trace statuses on observed spans', async () => {
  const payload = lifecycleFixture();
  payload.collection.observed_spans = ['success', 'error', 'running', 'skipped', 'suspended'].map(status => ({
    span_id: 'span_' + status, run_id: 'run_fixture', node: 'fact_validator', node_key: 'fact_validator', node_attempt: 1, status: status as 'success',
  }));
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload))));
  const response = await lifecycleApi.get('session_fixture');
  expect(response.collection.observed_spans.map(span => span.status)).toEqual(['success', 'error', 'running', 'skipped', 'suspended']);
});
it.each(['different_session', 'missing_collection', 'illegal_status', 'contradiction', 'missing_ref', 'bad_span'])('rejects malformed or contradictory lifecycle data: %s', async kind => {
  const payload: any = lifecycleFixture();
  if (kind === 'different_session') payload.source_refs.session_id = 'other';
  if (kind === 'missing_collection') delete payload.collection;
  if (kind === 'illegal_status') payload.business_lifecycle.status = 'all_green';
  if (kind === 'contradiction') payload.consistency.status = 'inconsistent';
  if (kind === 'missing_ref') delete payload.source_refs.approval_id;
  if (kind === 'bad_span') payload.collection.observed_spans = [{ status: 'success' }];
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(payload))));
  await expect(lifecycleApi.get('session_fixture')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
});
it('retains permission errors instead of displaying a fake unknown or successful lifecycle', async () => {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 403 })));
  await expect(lifecycleApi.get('session_fixture')).rejects.toMatchObject({ status: 403 });
});
