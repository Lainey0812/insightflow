import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw, ChevronLeft } from 'lucide-react';
import { workflowApi } from '../api/workflows';
import type { WorkflowView, WorkflowObservation } from '../types/workflows';
import type { TraceSpan, Metadata } from '../types/traces';
import { InputSummary } from '../features/workflows/WorkflowShared';
import { TraceError } from '../features/traces/AccessPanel';
import { StatusBadge } from '../features/traces/TraceShared';
import { durationText, flattenSpans, nodeLabels, timeText, traceStatus, traceStatusLabels, valueText } from '../features/traces/presentation';

const names: Record<string, string> = { ...nodeLabels, analysis_engine: '分析执行', hitl: '人工审核', chart_builder: '图表构建' };
function ResultRefs({ attrs }: { attrs: Metadata }) {
  const refs = Object.fromEntries(['result_ref', 'report_id', 'approval_id', 'plan_version_id', 'dataset_id', 'dataset_version', 'operation_id', 'report_run_id', 'execution_id'].filter(k => attrs[k] != null).map(k => [k, attrs[k]]));
  return <dl className="wf-refs">{Object.entries(refs).map(([k, v]) => <div key={k}><dt>{k}</dt><dd><code>{valueText(v)}</code></dd></div>)}{Array.isArray(attrs.result_refs) && <div><dt>result_refs</dt><dd>{valueText(attrs.result_refs)}</dd></div>}{!Object.keys(refs).length && <p className="muted">未采集独立结果引用。</p>}</dl>;
}
function GraphNode({ node, pressed, onSelect }: { node: TraceSpan; pressed: boolean; onSelect: (id: string) => void }) {
  return <button type="button" id={'node-' + node.span_id} data-testid="workflow-node" className={`wf-graph-node ${pressed ? 'wf-graph-selected' : ''} wf-graph-${traceStatus(node.status)}`} aria-pressed={pressed} onClick={() => onSelect(node.span_id)}>
    <strong>{names[node.name] || node.name}</strong>
    <StatusBadge status={node.status} />
    <small>{durationText(node.duration_ms)}</small>
  </button>;
}
function NodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const events = trace.events.filter(e => e.span_id === node.span_id);
  const calls = trace.llm_calls.filter(c => c.span_id === node.span_id);
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header><h2>{names[node.name] || node.name}</h2><StatusBadge status={node.status} /></header>
    <code className="wf-id">{node.span_id}</code>
    <section><h3>状态</h3><dl className="wf-node-facts"><div><dt>开始</dt><dd>{timeText(node.started_at)}</dd></div><div><dt>结束</dt><dd>{timeText(node.finished_at)}</dd></div><div><dt>耗时</dt><dd>{durationText(node.duration_ms)}</dd></div><div><dt>错误代码</dt><dd>{node.error_code || valueText(attrs.skip_reason)}</dd></div></dl></section>
    <section><h3>输入</h3><InputSummary attrs={attrs} /></section>
    <section><h3>输出</h3><ResultRefs attrs={attrs} />
      <h3>事件</h3>{events.length ? <ol className="wf-event-list">{events.map(e => <li key={e.event_id}><time>{timeText(e.recorded_at)}</time><code>{e.event_type}</code></li>)}</ol> : <p className="muted">没有已保存的事件。</p>}
      <h3>LLM 调用</h3>{calls.length ? <ul className="wf-calls">{calls.map(c => <li key={c.call_id}><Link className="wf-link wf-id" to={'/prompts/calls/' + encodeURIComponent(c.call_id)}>{c.call_id}</Link><span>请求 #{c.call_sequence} · {traceStatusLabels[traceStatus(c.status)]} · {durationText(c.duration_ms)}</span>{c.retry_index > 0 && <span className="wf-warning">请求重试 #{c.retry_index}，前次：{c.retry_of_call_id || '引用未采集'}</span>}</li>)}</ul> : <p className="muted">0 条已采集调用。</p>}
    </section>
  </aside>;
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
      {view.trace && selected ? <NodeDetail node={selected} trace={view.trace} /> : <aside className="wf-node-detail" aria-label="节点详情"><h2>节点详情</h2><p className="muted">左侧没有可点击的节点。</p></aside>}
    </div>}
  </div>;
}
