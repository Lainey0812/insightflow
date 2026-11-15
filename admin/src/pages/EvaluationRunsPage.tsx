import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { evaluationApi } from '../api/evaluations';
import { integrityStatuses, runStatuses, runTypes } from '../types/evaluations';
import type { RunListPage } from '../types/evaluations';
import { timeText } from '../features/traces/presentation';
import {
  DiscoveryWarnings, EvaluationError, IntegrityBadge, LifecycleBadge, Pager, Recorded, integrityLabels, lifecycleLabels, runTypeLabels,
} from '../features/evaluations/EvaluationShared';

const PAGE_SIZE = 20;
const FILTERS = ['run_type', 'status', 'integrity_status'] as const;

function versioned(id: string | null, version: string | null) {
  return <>{id ? <span>{id}</span> : <Recorded value={null} />}<small className="wf-subid">版本 <Recorded value={version} /></small></>;
}

export function EvaluationRunsPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<RunListPage | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const runType = params.get('run_type') || '', status = params.get('status') || '';
  const integrity = params.get('integrity_status') || '', page = params.get('page') || '';
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setData(null);
    evaluationApi.listRuns({ run_type: runType, status, integrity_status: integrity, page, page_size: PAGE_SIZE }, c.signal)
      .then(v => { if (!c.signal.aborted) setData(v); })
      .catch(e => { if (!c.signal.aborted) setError(e); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [runType, status, integrity, page, refresh]);
  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  }
  const filtered = FILTERS.some(key => params.get(key)) || Boolean(page);
  return <div className="wf-page">
    <header className="wf-heading"><div><h1>Evaluation Runs</h1>
      <p>Golden 与 TC 回归运行的统一只读列表。页面不启动评测。“运行已结束”只表示运行器写完了记录，不代表 E2E 通过。</p></div>
      <button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15} />手动刷新</button></header>
    <div className="ev-filters">
      <label>运行类型<select aria-label="运行类型" value={runType} onChange={e => update('run_type', e.target.value)}>
        <option value="">全部</option>{runTypes.map(t => <option key={t} value={t}>{runTypeLabels[t]}</option>)}</select></label>
      <label>生命周期<select aria-label="生命周期" value={status} onChange={e => update('status', e.target.value)}>
        <option value="">全部</option>{runStatuses.map(s => <option key={s} value={s}>{lifecycleLabels[s]}</option>)}</select></label>
      <label>完整性<select aria-label="完整性" value={integrity} onChange={e => update('integrity_status', e.target.value)}>
        <option value="">全部</option>{integrityStatuses.map(s => <option key={s} value={s}>{integrityLabels[s]}</option>)}</select></label>
      <button className="secondary-button" disabled={!filtered} onClick={() => setParams(new URLSearchParams())}>清除筛选</button>
    </div>
    {loading && <p role="status">正在读取评测运行…</p>}
    {error != null && <EvaluationError error={error} resource="评测运行" retry={() => setRefresh(v => v + 1)} back={{ to: '/evaluations/runs', label: '清除筛选' }} />}
    {data && <>
      <DiscoveryWarnings warnings={data.discovery_warnings} />
      <div className="wf-table-top"><strong>{data.total} 次运行</strong><span>按创建时间倒序</span></div>
      {data.items.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">评测运行</caption>
        <thead><tr><th>运行</th><th>类型</th><th>Agent</th><th>数据集</th><th>创建时间</th><th>生命周期</th><th>完整性</th><th>Case</th><th>E2E 指标</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.run_id}>
          <td><Link className="wf-link" to={'/evaluations/runs/' + encodeURIComponent(item.run_id)}>{item.run_id}</Link></td>
          <td>{runTypeLabels[item.run_type]}</td>
          <td>{versioned(item.agent_id, item.agent_version)}</td>
          <td>{versioned(item.dataset_id, item.dataset_version)}</td>
          <td>{item.created_at ? timeText(item.created_at) : <Recorded value={null} />}</td>
          <td><LifecycleBadge status={item.lifecycle_status} /></td>
          <td><IntegrityBadge status={item.integrity_status} /></td>
          <td>共 {item.case_count}<small className="wf-subid">已评测 {item.evaluated_case_count}</small></td>
          <td><span className="muted">列表接口不提供，进入详情查看</span></td>
        </tr>)}</tbody></table></div>
        : <div className="wf-empty"><h3>没有符合条件的评测运行</h3><p>{filtered ? '清除筛选后重试。' : '配置的评测目录中还没有可识别的运行。'}</p></div>}
      {(data.total > data.page_size || data.page > 1) && <Pager page={data.page} pageSize={data.page_size} total={data.total} label="评测运行" onPage={p => update('page', String(p))} />}
      <p className="muted">“未校验”表示历史格式没有可校验的 manifest，不等于“证据校验失败”。</p>
    </>}
  </div>;
}
