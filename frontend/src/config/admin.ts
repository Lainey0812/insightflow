const DEFAULT_ADMIN_URL = 'http://127.0.0.1:5174';

export function adminBaseUrl(value: string | undefined = import.meta.env.VITE_ADMIN_URL): string | null {
  const raw = value?.trim() || DEFAULT_ADMIN_URL;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    return url.href.replace(/\/+$/, '');
  } catch {
    return null;
  }
}

export function adminWorkflowUrl(workflowId: string, base: string | null = adminBaseUrl()): string | null {
  return base ? `${base}/traces/workflows/${encodeURIComponent(workflowId)}` : null;
}
