import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw, ChevronLeft } from 'lucide-react';
import { workflowApi } from '../api/workflows';
import type { WorkflowView } from '../types/workflows';
import type { TraceSpan } from '../types/traces';
import { NodeKindDetail } from '../features/workflows/NodeKindDetail';
import { TraceError } from '../features/traces/AccessPanel';
import { StatusBadge } from '../features/traces/TraceShared';
import { durationText, flattenSpans, nodeLabels, traceStatus } from '../features/traces/presentation';

const names: Record<string, string> = { ...nodeLabels, analysis_engine: '分析执行', hitl: '人工审核', chart_builder: '图表构建' };
function GraphNode({ node, pressed, onSelect }: { node: TraceSpan; pressed: boolean; onSelect: (id: string) => void }) {
  return <button type="button" id={'node-' + node.span_id} data-testid="workflow-node" className={`wf-graph-node ${pressed ? 'wf-graph-selected' : ''} wf-graph-${traceStatus(node.status)}`} aria-pressed={pressed} onClick={() => onSelect(node.span_id)}>
    <strong>{names[node.name] || node.name}</strong>
    <StatusBadge status={node.status} />
    <small>{durationText(node.duration_ms)}</small>
  </button>;
}
export function WorkflowDetailPage() {
  const { workflowId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<WorkflowView | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => { const controller = new AbortController(); setView(null); setError(null); setLoading(true); workflowApi.get(workflowId, controller.signal).then(v => { if (!controller.signal.aborted) setView(v); }).catch(e => { if (!controller.signal.aborted) setError(e); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [workflowId, refresh]);
  const nodes = view?.trace?.nodes ?? [];
  const selectedId = params.get('span');
  const selected = nodes.find(node => node.span_id === selectedId) || nodes.find(node => { const viewStatus = traceStatus(node.status); return viewStatus === 'error' || viewStatus === 'suspended'; }) || nodes[0];
  const select = (spanId: string) => { const next = new URLSearchParams(params); next.set('span', spanId); setParams(next, { replace: true }); };
  const rows = flattenSpans(nodes);
  const nested = rows.some(row => row.depth > 0);
  return <div className="wf-page"><Link className="wf-back" to="/traces/workflows"><ChevronLeft size={15} />Workflow 列表</Link><header className="wf-heading"><div><h1>Workflow</h1><p className="wf-id">{workflowId}</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15} />手动刷新</button></header>
    {loading && <p role="status">正在读取 workflow…</p>}{error != null && <TraceError error={error} resource="Workflow 详情" retry={() => setRefresh(v => v + 1)} />}
    {view && <div className="wf-split">
      <section className="wf-graph-panel" aria-label="Workflow 图"><h2>完整 Workflow</h2>
        {nodes.length ? <div className="wf-graph">{nested ? rows.map(({ span, depth }) => <div key={span.span_id} style={{ marginLeft: depth * 28 }}><GraphNode node={span} pressed={selected?.span_id === span.span_id} onSelect={select} /></div>) : rows.map(({ span }, index) => <div key={span.span_id} className="wf-graph-step">{index > 0 && <span className="wf-graph-link" aria-hidden="true" />}<GraphNode node={span} pressed={selected?.span_id === span.span_id} onSelect={select} /></div>)}</div> : <div className="wf-empty"><h3>暂无可读取的实际节点</h3><p>没有已保存的节点，不据此判断业务没有执行。</p></div>}
      </section>
      {view.trace && selected ? <NodeKindDetail key={selected.span_id} node={selected} trace={view.trace} /> : <aside className="wf-node-detail" aria-label="节点详情"><h2>节点详情</h2><p className="muted">左侧没有可点击的节点。</p></aside>}
    </div>}
  </div>;
}
