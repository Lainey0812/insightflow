import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { evaluationApi } from '../api/evaluations';
import { datasetTypes } from '../types/evaluations';
import type { DatasetListPage } from '../types/evaluations';
import {
  DiscoveryWarnings, EvaluationError, FreezeBadge, Pager, Recorded, ShortHash, datasetTypeLabels,
} from '../features/evaluations/EvaluationShared';

const PAGE_SIZE = 20;

export function EvaluationDatasetsPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<DatasetListPage | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const datasetType = params.get('dataset_type') || '', page = params.get('page') || '';
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setData(null);
    evaluationApi.listDatasets({ dataset_type: datasetType, page, page_size: PAGE_SIZE }, c.signal)
      .then(v => { if (!c.signal.aborted) setData(v); })
      .catch(e => { if (!c.signal.aborted) setError(e); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [datasetType, page, refresh]);
  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  }
  const filtered = Boolean(datasetType || page);
  return <div className="wf-page">
    <header className="wf-heading"><div><h1>测试数据集</h1>
      <p>读取配置的 Golden 与 TC 数据集来源。页面只读，不提供编辑、发布或冻结操作。</p></div>
      <button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15} />手动刷新</button></header>
    <div className="ev-filters">
      <label>数据集类型<select aria-label="数据集类型" value={datasetType} onChange={e => update('dataset_type', e.target.value)}>
        <option value="">全部</option>{datasetTypes.map(t => <option key={t} value={t}>{datasetTypeLabels[t]}</option>)}</select></label>
      <button className="secondary-button" disabled={!filtered} onClick={() => setParams(new URLSearchParams())}>清除筛选</button>
    </div>
    {loading && <p role="status">正在读取数据集…</p>}
    {error != null && <EvaluationError error={error} resource="数据集" retry={() => setRefresh(v => v + 1)} back={{ to: '/evaluations/datasets', label: '清除筛选' }} />}
    {data && <>
      <DiscoveryWarnings warnings={data.discovery_warnings} />
      <div className="wf-table-top"><strong>{data.total} 个数据集</strong><span>按数据集 ID 排序</span></div>
      {data.items.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">评测数据集</caption>
        <thead><tr><th>数据集</th><th>类型</th><th>版本</th><th>内容哈希</th><th>Case 数</th><th>冻结声明</th><th>关联运行</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.dataset_type + item.dataset_id}>
          <td><Link className="wf-link" to={'/evaluations/datasets/' + encodeURIComponent(item.dataset_id)}>{item.dataset_id}</Link></td>
          <td>{datasetTypeLabels[item.dataset_type]}</td>
          <td><Recorded value={item.dataset_version} /></td>
          <td><ShortHash value={item.dataset_hash} /></td>
          <td>{item.case_count}</td>
          <td><FreezeBadge /></td>
          <td><span className="ev-relations">共 {item.related_run_count} 次 · 哈希一致 {item.hash_matched_run_count} · 仅目录关联 {item.weak_path_run_count}
            {item.hash_mismatch_run_count > 0 ? ` · 另有 ${item.hash_mismatch_run_count} 次记录的哈希不同` : ''}</span></td>
        </tr>)}</tbody></table></div>
        : <div className="wf-empty"><h3>没有符合条件的数据集</h3><p>{filtered ? '清除筛选后重试。' : '后端没有发现可用的数据集来源。'}</p></div>}
      {(data.total > data.page_size || data.page > 1) && <Pager page={data.page} pageSize={data.page_size} total={data.total} label="数据集" onPage={p => update('page', String(p))} />}
      <p className="muted">“哈希不同”只说明运行记录的是另一份内容，不代表数据损坏，也不计入关联运行总数。</p>
    </>}
  </div>;
}
