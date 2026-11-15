import type { ReactNode } from 'react';

export type AdminPermission = 'dashboard:view' | 'traces:view' | 'versions:view' | 'settings:view' | 'workflows:view' | 'prompts:view' | 'evaluations:view' | 'bad-cases:view';
export type AccessResolver = (permission: AdminPermission) => 'allowed' | 'denied' | 'unconfigured';

// Shell route integration only; Trace data access is checked by the backend.
// Unconfigured is not an authenticated user or role. No credentials are stored here.
export function AccessBoundary({ permission, resolve, children }: {
  permission: AdminPermission; resolve?: AccessResolver; children: ReactNode;
}) {
  const decision = resolve?.(permission) ?? 'unconfigured';
  if (decision === 'denied') return <section className="notice-card" role="alert"><h1>暂时无法访问此页面</h1><p>权限检查未允许访问，请联系系统维护人员。</p></section>;
  return <>{children}</>;
}
