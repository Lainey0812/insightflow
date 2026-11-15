import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../api/client';
import { readAdminConfig } from '../config/env';

describe('API foundation, not monitoring endpoints', () => {
  it('uses a configurable base and a consistent JSON request', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('{"available":true}'));
    const client = new ApiClient('/api/v1/admin', 1000, fetcher);
    await expect(client.get('/example?limit=2')).resolves.toEqual({ available: true });
    expect(fetcher.mock.calls[0][0]).toBe('http://localhost:5174/api/v1/admin/example?limit=2');
    expect(fetcher.mock.calls[0][1]?.credentials).toBe('same-origin');
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
  });
  it.each([403, 500])('keeps HTTP %s as an explicit error', async status => {
    const client = new ApiClient('/api', 1000, vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status })));
    await expect(client.get('example')).rejects.toMatchObject({ code: 'HTTP_ERROR', status });
  });
  it('distinguishes network failures and malformed successful responses', async () => {
    const network = new ApiClient('/api', 1000, vi.fn<typeof fetch>().mockRejectedValue(new TypeError('network')));
    await expect(network.get('example')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    const html = new ApiClient('/api', 1000, vi.fn<typeof fetch>().mockResolvedValue(new Response('<html>not JSON</html>')));
    await expect(html.get('example')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('times out and cancels the actual fetch signal', async () => {
    vi.useFakeTimers();
    const pending = vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const request = new ApiClient('/api', 20, pending).get('example');
    const assertion = expect(request).rejects.toMatchObject({ code: 'REQUEST_TIMEOUT' });
    await vi.advanceTimersByTimeAsync(20); await assertion;
    expect(pending.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
  it('rejects requests outside its API namespace', async () => {
    const fetcher = vi.fn<typeof fetch>(); const client = new ApiClient('/api/v1/admin', 1000, fetcher);
    for (const path of ['https://example.com/private', '//example.com/private', '../sessions', '%2e%2e/sessions']) {
      await expect(client.get(path)).rejects.toThrow('API Base URL');
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('validates environment URLs without accepting client-side credentials', () => {
    expect(readAdminConfig({}).apiBaseUrl).toBe('/api/v1/admin');
    expect(readAdminConfig({ VITE_ADMIN_API_BASE_URL: 'https://api.example.com/admin/' }).apiBaseUrl).toBe('https://api.example.com/admin');
    for (const value of ['javascript:alert(1)', '//api.example.com', 'https://user:password@example.com']) {
      expect(() => readAdminConfig({ VITE_ADMIN_API_BASE_URL: value })).toThrow();
    }
  });
});
