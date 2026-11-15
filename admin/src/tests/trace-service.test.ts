import { describe, expect, it, vi } from 'vitest';
import { traceApi } from '../api/traces';

describe('Trace service uses authenticated backend only', () => {
  it('exchanges a credential without persisting it in browser storage or URLs', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"access":"read_only"}'));
    vi.stubGlobal('fetch', fetcher);
    const store = vi.spyOn(Storage.prototype, 'setItem');
    await traceApi.grant('temporary-test-value');
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toBe('http://localhost:5174/api/v1/admin/access');
    expect(new Headers(init?.headers).get('X-Admin-Token')).toBe('temporary-test-value');
    expect(init?.credentials).toBe('same-origin'); expect(store).not.toHaveBeenCalled();
  });
  it('rejects an HTML or malformed JSON shape instead of displaying an empty trace', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('{"items":null}')));
    await expect(traceApi.runs('limit=20')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('rejects events from a different span', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('{"items":[{"span_id":"other","event_id":"event"}]}')));
    await expect(traceApi.events('current', 0)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('retains lack of permission as an error, with no fallback data', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response('{}', { status: 403 })));
    await expect(traceApi.runs('limit=20')).rejects.toMatchObject({ status: 403 });
  });
});

it('sends comparison IDs in the authenticated namespace and rejects mismatched runs', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"left":{"run_id":"wrong"},"right":{"run_id":"b"}}'));
  vi.stubGlobal('fetch', fetcher);
  await expect(traceApi.comparison('a', 'b')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  expect(String(fetcher.mock.calls[0][0])).toBe('http://localhost:5174/api/v1/admin/comparison?left=a&right=b');
  expect(fetcher.mock.calls[0][1]?.credentials).toBe('same-origin');
});
