import { expect, it, vi } from 'vitest';
import { promptApi } from '../api/prompts';

it('rejects malformed lists and mismatched snapshot identities', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: 'bad' }), { status: 200 })));
  await expect(promptApi.catalog('')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ template: { template_snapshot_id: 'wrong', node_id: 'intent_parser' } }), { status: 200 })));
  await expect(promptApi.detail('intent_parser', 'pt_expected')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
});
it('sends snapshot credentials in a noncached header, never in URL', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ request_snapshot_id: 'req', payload: { messages: [] } }), { status: 200 }));
  vi.stubGlobal('fetch', fetcher); await promptApi.raw('call_id', 'snapshot-secret');
  const [url, options] = fetcher.mock.calls[0];
  expect(String(url)).not.toContain('snapshot-secret'); expect(options.headers.get('X-Admin-Snapshot-Token')).toBe('snapshot-secret'); expect(options.cache).toBe('no-store');
});
