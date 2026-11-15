import { readAdminConfig } from '../config/env';

export type ApiErrorCode = 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'REQUEST_TIMEOUT' | 'REQUEST_ABORTED';

export class ApiError extends Error {
  constructor(public readonly code: ApiErrorCode, message: string, public readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body' | 'signal'> {
  body?: unknown;
  signal?: AbortSignal;
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs = 15_000,
    private readonly fetcher: typeof fetch = (input, init) => fetch(input, init),
  ) {}

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    // Keep request paths in the configured namespace, including URL-normalized ..
    // segments. Browser access uses a server-issued HttpOnly cookie.
    const base = new URL(this.baseUrl.replace(/\/+$/, '') + '/', globalThis.location?.origin || 'http://localhost');
    const target = new URL(path.replace(/^\/(?!\/)/, ''), base);
    if (target.origin !== base.origin || !target.pathname.startsWith(base.pathname)) {
      throw new Error('API 请求路径必须位于配置的 API Base URL 内。');
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, this.timeoutMs);
    const { body, signal, ...rest } = options;
    try {
      const headers = new Headers(options.headers);
      headers.set('Accept', 'application/json');
      if (body !== undefined) headers.set('Content-Type', 'application/json');
      const response = await this.fetcher(target.toString(), {
        ...rest, credentials: 'same-origin', headers, signal: controller.signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (!response.ok) throw new ApiError('HTTP_ERROR', `请求未完成，服务返回 ${response.status}。`, response.status);
      if (response.status === 204) return undefined as T;
      try { return await response.json() as T; }
      catch { throw new ApiError('INVALID_RESPONSE', '服务返回的内容不是有效 JSON。'); }
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted) {
        throw signal?.aborted
          ? new ApiError('REQUEST_ABORTED', '请求已取消。')
          : new ApiError('REQUEST_TIMEOUT', '请求超时，请稍后重试。');
      }
      throw new ApiError('NETWORK_ERROR', '暂时无法连接 API 服务。');
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  get<T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>): Promise<T> {
    return this.request<T>(path, { ...options, method: 'GET' });
  }

  post<T>(path: string, body: unknown, options?: Omit<RequestOptions, 'method' | 'body'>): Promise<T> {
    return this.request<T>(path, { ...options, method: 'POST', body, cache: 'no-store' });
  }
}

// Public API configuration only; no client-side stored admin secret.
export function createAdminClient(): ApiClient {
  return new ApiClient(readAdminConfig().apiBaseUrl);
}
