import { useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { traceApi } from '../../api/traces';

export function TraceError({ error, retry, resource = '追踪数据' }: { error: unknown; retry: () => void; resource?: string }) {
  const [token, setToken] = useState(''), [pending, setPending] = useState(false), [denied, setDenied] = useState(false);
  const accessDenied = error instanceof ApiError && error.status === 403;
  const notFound = error instanceof ApiError && error.status === 404;
  async function submit(event: FormEvent) {
    event.preventDefault(); setPending(true); setDenied(false);
    try { await traceApi.grant(token); setToken(''); retry(); }
    catch { setDenied(true); }
    finally { setPending(false); setToken(''); }
  }
  return <section className="trace-message" role="alert">
    <h2>{accessDenied ? '需要管理员只读访问' : notFound ? resource === '追踪数据' ? '追踪记录不存在' : resource.startsWith('Workflow') ? 'Workflow 不存在或未登记' : '历史内容 unavailable' : '无法加载' + resource}</h2>
    <p>{accessDenied ? '使用后端配置的管理员只读凭证。凭证不会写入 URL 或本地存储；短期访问由 HttpOnly Cookie 保存。' :
      notFound ? '该记录可能未采集或已不可用。请返回列表核对。' : error instanceof ApiError && error.status === 503 ? resource === '追踪数据' ? '后端未配置管理员访问或追踪存储不可用，请检查服务配置。' : '后端未配置管理员访问或 Prompt Registry 存储不可用，请检查服务配置。' : '请求失败，未将失败当作空数据。请检查连接后重试。'}</p>
    {accessDenied ? <form className="access-form" onSubmit={submit}><label>管理员只读凭证<input aria-label="管理员只读凭证" type="password" value={token} autoComplete="off" onChange={e => setToken(e.target.value)} required maxLength={2048} /></label><button className="primary-button" disabled={pending}>{pending ? '验证中…' : '启用只读访问'}</button>{denied && <span>验证失败，请检查凭证或服务配置。</span>}</form> : <button className="secondary-button" onClick={retry}>重新加载</button>}
  </section>;
}
export function RevokeAccess({ done }: { done: () => void }) {
  const [pending, setPending] = useState(false), [failed, setFailed] = useState(false);
  return <><button className="secondary-button" disabled={pending} onClick={async () => {
    setPending(true); setFailed(false);
    try { await traceApi.revoke(); done(); } catch { setFailed(true); } finally { setPending(false); }
  }}>退出只读访问</button>{failed && <span role="alert">退出请求失败，请重试。</span>}</>;
}
