export interface AdminConfig {
  apiBaseUrl: string;
}

export function readAdminConfig(env: Pick<ImportMetaEnv, 'VITE_ADMIN_API_BASE_URL'> = import.meta.env): AdminConfig {
  const apiBaseUrl = env.VITE_ADMIN_API_BASE_URL?.trim() || '/api/v1/admin';
  const absolute = /^https?:\/\//i.test(apiBaseUrl);
  if ((!absolute && (!apiBaseUrl.startsWith('/') || apiBaseUrl.startsWith('//'))) ||
      apiBaseUrl.includes('?') || apiBaseUrl.includes('#')) {
    throw new Error('VITE_ADMIN_API_BASE_URL 需要使用 HTTP(S) 地址或以 / 开头的相对路径。');
  }
  const parsed = new URL(apiBaseUrl, 'http://localhost');
  if (parsed.username || parsed.password) {
    throw new Error('Admin API 地址不能包含用户名或密码。');
  }
  return { apiBaseUrl: apiBaseUrl.replace(/\/+$/, '') || '/' };
}
