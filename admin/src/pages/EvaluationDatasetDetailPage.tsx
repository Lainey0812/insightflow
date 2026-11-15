import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { evaluationApi } from '../api/evaluations';
import type { DatasetDetail } from '../types/evaluations';
import { timeText } from '../features/traces/presentation';
import {
  DiscoveryWarnings, EvaluationError, FreezeBadge, IntegrityBadge, LifecycleBadge, Recorded, RelationBadge, ShortHash,
  datasetTypeLabels, relationExplanations, runTypeLabels, safeRef,
} from '../features/evaluations/EvaluationShared';
import { GOLDEN_BUNDLED_SHA256, GoldenSetContent } from './GoldenSetPage';

export function EvaluationDatasetDetailPage() {
  const { datasetId = '' } = useParams();
  const [data, setData] = useState<DatasetDetail | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setData(null);
    evaluationApi.getDataset(datasetId, c.signal)
      .then(v => { if (!c.signal.aborted) setData(v); })
      .catch(e => { if (!c.signal.aborted) setError(e); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [datasetId, refresh]);
  const source = data ? safeRef(data.source) : null;
  const relations = data ? Array.from(new Set(data.related_runs.map(r => r.relation))) : [];
  return <div className="wf-page"><Link className="wf-back" to="/evaluations/datasets"><ChevronLeft size={15} />数据集列表</Link>
    <header className="wf-heading"><div><h1>数据集详情</h1><p className="wf-id">{datasetId}</p></div>
      <button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15} />手动刷新</button></header>
    {loading && <p role="status">正在读取数据集…</p>}
    {error != null && <EvaluationError error={error} resource="数据集" retry={() => setRefresh(v => v + 1)} back={{ to: '/evaluations/datasets', label: '返回数据集列表' }} />}
    {data && <>
      <section className="trace-card" aria-labelledby="dataset-meta"><h2 id="dataset-meta">元数据</h2>
        <dl className="trace-keyvalues">
          <div><dt>数据集 ID</dt><dd>{data.dataset_id}</dd></div>
          <div><dt>类型</dt><dd>{datasetTypeLabels[data.dataset_type]}</dd></div>
          <div><dt>版本</dt><dd><Recorded value={data.dataset_version} /></dd></div>
          <div><dt>内容哈希（SHA-256）</dt><dd><code>{data.dataset_hash}</code></dd></div>
          <div><dt>Case 数</dt><dd>{data.case_count}</dd></div>
          <div><dt>来源</dt><dd>{source ? <code>{source}</code> : '已隐藏（非仓库相对路径）'}</dd></div>
          <div><dt>冻结声明</dt><dd><FreezeBadge /> 没有正式冻结声明。文件哈希只标识内容，不是数据集版本。</dd></div>
        </dl>
      </section>
      <DiscoveryWarnings warnings={data.discovery_warnings} />
      <section aria-labelledby="hash-variants">
        <div className="wf-table-top"><strong id="hash-variants">运行记录的内容哈希</strong><span>{data.hash_variants.length} 种</span></div>
        {data.hash_variants.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">内容哈希</caption>
          <thead><tr><th>哈希</th><th>与当前来源</th><th>运行数</th></tr></thead>
          <tbody>{data.hash_variants.map(h => <tr key={h.dataset_hash}><td><ShortHash value={h.dataset_hash} /></td>
            <td>{h.matches_current_source ? '一致' : '不同（另一份内容，不代表损坏）'}</td><td>{h.run_count}</td></tr>)}</tbody></table></div>
          : <div className="wf-empty"><p>没有运行记录这个数据集的哈希。</p></div>}
      </section>
      <section aria-labelledby="related-runs">
        <div className="wf-table-top"><strong id="related-runs">关联运行</strong><span>{data.related_runs.length} 次</span></div>
        {relations.map(r => <p key={r} className="muted"><RelationBadge relation={r} /> {relationExplanations[r]}</p>)}
        {data.related_runs.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">关联运行</caption>
          <thead><tr><th>运行</th><th>类型</th><th>创建时间</th><th>生命周期</th><th>完整性</th><th>关联方式</th><th>运行记录的哈希</th></tr></thead>
          <tbody>{data.related_runs.map(r => <tr key={r.run_id}>
            <td><Link className="wf-link" to={'/evaluations/runs/' + encodeURIComponent(r.run_id)}>{r.run_id}</Link></td>
            <td>{runTypeLabels[r.run_type]}</td><td>{r.created_at ? timeText(r.created_at) : <Recorded value={null} />}</td>
            <td><LifecycleBadge status={r.lifecycle_status} /></td><td><IntegrityBadge status={r.integrity_status} /></td>
            <td><RelationBadge relation={r.relation} /></td><td><ShortHash value={r.recorded_dataset_hash} /></td>
          </tr>)}</tbody></table></div>
          : <div className="wf-empty"><p>暂无关联运行。</p></div>}
      </section>
      {data.dataset_type === 'golden' && (data.dataset_hash === GOLDEN_BUNDLED_SHA256
        ? <section aria-label="数据集内容"><p className="muted">内容来自前端打包副本，其哈希与当前来源一致。</p><GoldenSetContent /></section>
        : <p className="trace-notice trace-warning">前端打包的 Golden 副本与当前来源哈希不同，不展示内容，避免把旧内容当作当前数据集。</p>)}
    </>}
  </div>;
}
