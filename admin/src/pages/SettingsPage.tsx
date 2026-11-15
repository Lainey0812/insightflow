import { Shield, Settings2 } from 'lucide-react';
import { readAdminConfig } from '../config/env';

export function SettingsPage() {
  const { apiBaseUrl } = readAdminConfig();
  return <><div className="page-heading"><span className="eyebrow">CONFIGURATION</span><h1>环境配置</h1><p>当前工程配置与后续接入位置。</p></div>
    <section className="settings-card" aria-label="当前工程配置"><div className="card-heading"><Settings2 size={19} /><h2>本地配置</h2><span>只读</span></div>
      <dl><div><dt>Admin 版本</dt><dd>V0.3 · Trace 追溯与对比</dd></div><div><dt>API Base URL</dt><dd><code>{apiBaseUrl}</code><small>配置项：VITE_ADMIN_API_BASE_URL。当前页面未发起接口请求。</small></dd></div><div><dt>数据状态</dt><dd>Trace 已接入；其他监控尚未接入</dd></div></dl>
    </section>
    <section className="access-note"><Shield size={21} /><div><h2>账户身份认证尚未接入</h2><p>Trace 复用后端管理员只读凭证，以短期 HttpOnly Cookie 维持访问；未实现多用户账户或角色管理。</p></div></section>
  </>;
}
