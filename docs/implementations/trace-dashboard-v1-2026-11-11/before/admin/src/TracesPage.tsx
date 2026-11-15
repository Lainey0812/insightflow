import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw, ArrowUpRight, Workflow } from 'lucide-react';
import { traceApi } from '../api/traces';
import type { RunPage } from '../types/traces';
import { TraceError, RevokeAccess } from '../features/traces/AccessPanel';
import { CoverageNotice, StatusBadge } from '../features/traces/TraceShared';
import { durationText, metadata, nodeLabels, timeText, traceStatuses, traceStatusLabels, valueText } from '../features/traces/presentation';
import { EmptyState } from '../components/EmptyState';

function positive(value: string | null, fallback: number, min: number, max: number) {
  const parsed = value === null ? fallback : Number(value);
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : fallback;
}
export function TracesPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.getAll('compare').slice(0, 2);
  function selectRun(id: string) {
    const next = new URLSearchParams(params); next.delete('compare');
    const chosen = selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id].slice(-2);
    chosen.forEach(item => next.append('compare', item)); setParams(next);
  }
  const [page, setPage] = useState<RunPage | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0), [formError, setFormError] = useState('');
  const limit = positive(params.get('limit'), 20, 1, 100), offset = positive(params.get('offset'), 0, 0, 1000000);
  const workflow = params.get('kind') === 'workflow';
  const request = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (workflow) request.set('kind', 'workflow');
  for (const key of ['status', 'from_time', 'to_time', 'node', 'version']) if (params.get(key)) request.set(key, params.get(key)!);
  const query = request.toString();
  const reload = () => setRefresh(value => value + 1);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setPage(null);
    traceApi.runs(query, controller.signal).then(value => { if (!controller.signal.aborted) setPage(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, refresh]);
  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); const next = new URLSearchParams({ limit: String(limit) });
    setFormError('');
    if (data.get('kind') === 'workflow') next.set('kind', 'workflow');
    const start = String(data.get('from_time') || ''), end = String(data.get('to_time') || '');
    if (start && end && new Date(start) > new Date(end)) { setFormError('开始时间不能晚于结束时间。'); return; }
    for (const key of ['status', 'node', 'version']) { const value = String(data.get(key) || '').trim(); if (value) next.set(key, value); }
    for (const [key, value] of [['from_time', start], ['to_time', end]]) if (value) {
      const date = new Date(value); if (!Number.isFinite(date.getTime())) { setFormError('时间格式不正确。'); return; } next.set(key, date.toISOString());
    }
    setParams(next);
  }
  const localInput = (key: string) => {
    const value = params.get(key); if (!value || !Number.isFinite(Date.parse(value))) return '';
    const date = new Date(value); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
  };
  function move(nextOffset: number) { const next = new URLSearchParams(params); next.set('offset', String(nextOffset)); next.set('limit', String(limit)); setParams(next); }
  return <>
    <div className="trace-heading"><div><span className="eyebrow">WORKFLOW TRACES</span><h1>Workflow Trace</h1><p>查询真实流程与报告追踪，在详情中核对任务生命周期。</p></div><div className="trace-actions"><button className="secondary-button" onClick={reload} disabled={loading}><RefreshCw size={14} />手动刷新</button>{page && <RevokeAccess done={reload} />}</div></div>
    <form key={params.toString()} className="trace-filters trace-card" onSubmit={filter} aria-label="运行筛选">
      <label>记录范围<select name="kind" defaultValue={workflow ? 'workflow' : 'report_generation'}><option value="report_generation">报告生成尝试</option><option value="workflow">分析流程（准备阶段）</option></select></label>
      <label>状态<select name="status" defaultValue={params.get('status') || ''}><option value="">全部</option>{traceStatuses.map(status => <option key={status} value={status}>{traceStatusLabels[status]}</option>)}</select></label>
      <label>排队时间从（本地）<input name="from_time" type="datetime-local" step="1" defaultValue={localInput('from_time')} /></label>
      <label>排队时间至（本地）<input name="to_time" type="datetime-local" step="1" defaultValue={localInput('to_time')} /></label>
      <label>包含节点<input aria-label="包含节点" name="node" list="trace-nodes" placeholder="全部节点" defaultValue={params.get('node') || ''} maxLength={128} /><datalist id="trace-nodes">{Object.entries(nodeLabels).map(([name, label]) => <option key={name} value={name}>{label}</option>)}</datalist></label>
      <label>版本精确匹配<input name="version" placeholder="Prompt / 生成 / Schema / 校验版本" defaultValue={params.get('version') || ''} maxLength={160} /></label>
      <div className="filter-actions"><button className="primary-button" type="submit">应用筛选</button><button className="secondary-button" type="button" onClick={() => { setFormError(''); setParams({ limit: String(limit) }); }}>重置</button></div>
      {formError && <p role="alert">{formError}</p>}
      <p className="muted">成功含已完成。错误含失败、部分成功和无可用报告。暂停含等待补充、等待审核和进程中断。跳过只出现在节点上。</p>
    </form>
    <div className="trace-card compare-selection"><span>选择两次历史运行 · 已选 {selected.length}/2（跨页保留）</span>
      {selected.length === 2 ? <Link className="primary-button" to={'/traces/compare?' + new URLSearchParams({ left: selected[0], right: selected[1] })}>对比所选运行</Link> : <span className="muted">勾选列表中的两次运行</span>}
      <Link className="trace-link" to="/traces/compare">通过 Run ID 对比</Link>
    </div>
    <CoverageNotice degraded={page?.collector_degraded} scope={workflow ? 'workflow_preparation' : 'report_generation'} />
    {!workflow && <p className="muted">分析尚未生成报告时，可<Link className="trace-link" to="/traces?kind=workflow">查看分析流程记录</Link>。</p>}
    {loading ? <div className="trace-message" role="status">正在读取后端运行记录…</div> : error ? <TraceError error={error} retry={reload} /> : page && <>
      {page.items.length === 0 ? <EmptyState icon={Workflow} statusLabel="已连接真实数据" title={offset ? '当前页没有记录' : '没有匹配的运行记录'} description="接口已返回空结果。可调整筛选条件；未生成演示数据。" note="没有埋点的历史任务不会自动出现 Trace。" /> : <div className="trace-card trace-table-wrap"><table className="trace-table"><caption className="visually-hidden">真实运行列表</caption><thead><tr><th>对比</th><th>运行</th><th>Trace 状态</th><th>排队时间</th><th>整体耗时</th><th>版本</th><th>尝试</th><th>操作</th></tr></thead><tbody>{page.items.map(run => <tr key={run.run_id}>
        <td><input type="checkbox" aria-label={'选择对比 ' + run.run_id} checked={selected.includes(run.run_id)} onChange={() => selectRun(run.run_id)} /></td><td><code className="run-id">{run.run_id}</code><small>{run.kind === 'workflow' ? (run.manifest?.capture_scope === 'workflow_preparation' ? 'Workflow 准备阶段' : 'Workflow Root') : '执行：' + valueText(run.execution_id)}</small>{run.integrity === 'incomplete' && <span className="integrity-tag">追踪不完整</span>}</td><td><StatusBadge status={run.status} /></td><td>{timeText(run.queued_at)}</td><td>{durationText(run.duration_ms)}</td><td><span>{valueText(metadata(run.manifest?.versions).prompt_version)}</span><small>{valueText(metadata(run.manifest?.versions).schema_version)}</small></td><td>{typeof run.attempt === 'number' ? `第 ${run.attempt} 次` : '未采集'}</td><td><Link className="trace-link" to={'/traces/' + encodeURIComponent(run.run_id)}>查看详情 <ArrowUpRight size={13} /></Link></td>
      </tr>)}</tbody></table></div>}
      <div className="trace-pagination"><span>匹配 {page.total} 条 · 第 {Math.floor(offset / limit) + 1} 页</span><label>每页<select aria-label="每页记录数" value={limit} onChange={e => { const next = new URLSearchParams(params); next.set('limit', e.target.value); next.delete('offset'); setParams(next); }}>{Array.from(new Set([limit, 10, 20, 50, 100])).sort((a, b) => a - b).map(value => <option key={value} value={value}>{value}</option>)}</select></label><button className="secondary-button" disabled={offset === 0} onClick={() => move(Math.max(0, offset - limit))}>上一页</button><button className="secondary-button" disabled={offset + limit >= page.total} onClick={() => move(offset + limit)}>下一页</button></div>
    </>}
  </>;
}
