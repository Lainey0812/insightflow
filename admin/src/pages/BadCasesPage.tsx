import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw, Search } from 'lucide-react';
import { badCaseApi } from '../api/badCases';
import { badCaseCategories, badCaseStatuses } from '../types/badCases';
import type { BadCasePage } from '../types/badCases';
import { BadCaseStatusBadge, SeverityBadge, categoryLabels, statusLabels } from '../features/badCases/BadCaseShared';
import { BusinessBadge } from '../features/workflows/WorkflowShared';
import { TraceError } from '../features/traces/AccessPanel';
import { timeText } from '../features/traces/presentation';
import { AttributionForm, causeLabels } from '../features/badCases/AttributionForm';

const FILTERS = ['status', 'category', 'workflow_id'] as const;
export function BadCasesPage() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<BadCasePage | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const start = Number(params.get('offset') || 0), offset = Number.isInteger(start) && start >= 0 ? start : 0;
  const query = new URLSearchParams({ limit: '20', offset: String(offset) });
  for (const k of FILTERS) if (params.get(k)) query.set(k, params.get(k)!);
  const key = query.toString();
  useEffect(() => { const c = new AbortController(); setLoading(true); setError(null); setPage(null);
    badCaseApi.list(key, c.signal).then(v => { if (!c.signal.aborted) setPage(v); }).catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort(); }, [key, refresh]);
  function filter(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const f = new FormData(event.currentTarget), next = new URLSearchParams();
    for (const k of FILTERS) { const v = String(f.get(k) || '').trim(); if (v) next.set(k, v); } setParams(next); }
  function move(value: number) { const next = new URLSearchParams(params); next.set('offset', String(value)); setParams(next); }
  return <div className="wf-page"><header className="wf-heading"><div><h1>Bad Case 问题列表</h1><p>人工确认的问题案例。只能从 Workflow 详情页“存为 Bad Case”创建，不会把 Trace 错误自动转为 Bad Case。</p></div><button className="secondary-button" onClick={() => setRefresh(v => v + 1)} disabled={loading}><RefreshCw size={15}/>手动刷新</button></header>
    <form className="wf-filters" onSubmit={filter} key={params.toString()}>
      <label>处理状态<select name="status" defaultValue={params.get('status') || ''}><option value="">全部</option>{badCaseStatuses.map(s => <option key={s} value={s}>{statusLabels[s]}</option>)}</select></label>
      <label>问题类型<select name="category" defaultValue={params.get('category') || ''}><option value="">全部</option>{badCaseCategories.map(c => <option key={c} value={c}>{categoryLabels[c]}</option>)}</select></label>
      <label>Workflow ID<input name="workflow_id" defaultValue={params.get('workflow_id') || ''} maxLength={120} placeholder="完整 Workflow ID"/></label>
      <button className="primary-button" type="submit"><Search size={15}/>查询</button></form>
    {loading && <p role="status">正在读取 Bad Case…</p>}{error != null && <TraceError error={error} resource="Bad Case 列表" retry={() => setRefresh(v => v + 1)}/>}
    {!loading && page && <><div className="wf-table-top"><strong>{page.total} 条 Bad Case</strong><span>按创建时间倒序</span></div>{page.items.length ? <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>问题</th><th>处理状态</th><th>严重程度</th><th>问题类型 / 节点</th><th>保存时业务状态</th><th>标注人 / 时间</th><th>归因判断 / 操作</th></tr></thead><tbody>
      {page.items.map(i => <tr key={i.case_id}><td><Link className="wf-link" to={'/bad-cases/' + encodeURIComponent(i.case_id)}>{i.title}</Link><code className="wf-subid">{i.workflow_id}</code></td><td><BadCaseStatusBadge status={i.status}/></td><td><SeverityBadge severity={i.severity}/></td><td>{categoryLabels[i.category]}<small className="wf-subid">{i.node_name || '整条 Workflow'}</small></td><td><BusinessBadge status={i.business_status}/></td><td>{i.created_by}<small className="wf-subid">{timeText(i.created_at)}</small></td><td className="bc-attribution-cell"><strong>{i.attribution?causeLabels[i.attribution.cause]:'未提交归因'}</strong>{i.attribution&&<p>{i.attribution.explanation}</p>}<details><summary>编辑归因判断</summary><AttributionForm key={i.sequence} item={i} onSaved={()=>setRefresh(v=>v+1)}/></details><Link className="wf-link" to={'/bad-cases/'+encodeURIComponent(i.case_id)}>查看详情</Link></td></tr>)}
    </tbody></table></div> : <div className="wf-empty"><h3>没有符合条件的 Bad Case</h3><p>在 Workflow 运行详情页的“人工标注”中保存。</p></div>}
      {page.total > 20 && <div className="wf-pagination"><button className="secondary-button" disabled={offset === 0} onClick={() => move(Math.max(0, offset - 20))}>上一页</button><span>{offset + 1}–{Math.min(offset + 20, page.total)} / {page.total}</span><button className="secondary-button" disabled={offset + 20 >= page.total} onClick={() => move(offset + 20)}>下一页</button></div>}</>}
  </div>;
}
