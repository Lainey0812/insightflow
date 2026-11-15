import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw, ArrowLeft } from 'lucide-react';
import { traceApi } from '../api/traces';
import type { RunDetail, TraceSpan } from '../types/traces';
import { TraceError, RevokeAccess } from '../features/traces/AccessPanel';
import { CoverageNotice, KeyValues, ManifestView, StatusBadge } from '../features/traces/TraceShared';
import { NodeInspector } from '../features/traces/NodeInspector';
import { LifecyclePanel } from '../features/traces/LifecyclePanel';
import { durationText, flattenSpans, metadata, nodeLabels, nodeType, nodeTypes, timeText, traceStatus, valueText } from '../features/traces/presentation';

export function TraceDetailPage() {
  const { runId = '' } = useParams(); const [params, setParams] = useSearchParams();
  const [detail, setDetail] = useState<RunDetail | null>(null), [spans, setSpans] = useState<TraceSpan[]>([]);
  const [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh(value => value + 1);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setDetail(null); setSpans([]);
    Promise.all([traceApi.run(runId, controller.signal), traceApi.spans(runId, controller.signal)])
      .then(([record, stages]) => { if (!controller.signal.aborted) { setDetail(record); setSpans(stages); } })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, refresh]);
  const selectedId = params.get('span');
  const selected = selectedId ? spans.find(span => span.span_id === selectedId) : spans.find(span => { const view = traceStatus(span.status); return view === 'error' || view === 'suspended'; }) || spans[0];
  const run = detail?.run;
  return <>
    <Link className="trace-link" to="/traces"><ArrowLeft size={14} />返回运行列表</Link>
    <div className="trace-heading"><div><span className="eyebrow">TRACE DETAIL</span><h1>运行详情</h1><p className="wrap-code">{runId}</p></div><div className="trace-actions"><button className="secondary-button" disabled={loading} onClick={reload}><RefreshCw size={14} />手动刷新</button>{detail && <RevokeAccess done={reload} />}</div></div>
    {loading ? <div className="trace-message" role="status">正在读取运行与节点记录…</div> : error ? <TraceError error={error} retry={reload} /> : run && detail && <>
      <LifecyclePanel run={run} refresh={refresh} />
      <CoverageNotice degraded={detail.collector_degraded} incomplete={run.integrity === 'incomplete'} scope={run.manifest?.capture_scope || (run.kind === 'workflow' ? 'unknown_workflow' : undefined)} />
      <section className="trace-card run-summary"><div className="section-heading"><h2>{run.kind === 'workflow' ? (run.manifest?.capture_scope === 'workflow_preparation' ? 'Workflow 准备阶段追踪' : 'Workflow 追踪记录') : '报告生成尝试'}</h2><StatusBadge status={run.status} /></div>
        <p className="muted">此处为当前查看的 Trace 保存状态；完整任务状态以上方生命周期查询为准。</p>
        {run.status === 'error' && <p className="trace-notice trace-warning">本次按错误展示。部分成功、失败和无可用报告都归入错误，不能按完整成功使用。</p>}
        {run.error_code && <p className="trace-danger"><strong>运行错误：</strong><code>{run.error_code}</code></p>}
        <div className="run-summary-grid"><KeyValues source={{ ...run, start: timeText(run.started_at), queued: timeText(run.queued_at), finish: timeText(run.finished_at), recovered: timeText(run.recovered_at), duration: durationText(run.duration_ms), prompt: metadata(run.manifest?.versions).prompt_version }} fields={{ session_id: '会话', execution_id: '执行', report_id: '报告引用', attempt: run.kind === 'workflow' ? 'Root 记录序号' : '报告尝试次数', queued: '排队时间', start: '实际开始', finish: '实际结束', recovered: '恢复发现时间', duration: '整体耗时', prompt: 'Prompt 版本' }} /></div>
        {run.retry_of_run_id ? <p>这是重试尝试。<Link className="trace-link" to={'/traces/' + encodeURIComponent(run.retry_of_run_id)}>查看上一次运行</Link></p> : typeof run.attempt === 'number' && run.attempt > 1 ? <p className="trace-warning">已记录第 {run.attempt} 次尝试，上一次 Trace 未采集或不可用。</p> : null}
        {run.kind !== 'workflow' && <details><summary>业务状态与追踪状态的区别</summary><KeyValues source={metadata(detail.business_source)} fields={{ available: '业务来源可读', status: '最新报告生成状态', latest_attempt: '最新业务尝试', same_attempt: '是否对应本次尝试', report_status: '报告内容状态', goal_coverage: '目标覆盖' }} /><p className="muted">业务 completed 不等于报告内容 complete；部分成功、无证据和追踪中断各自保留。</p></details>}
      </section>
      <div className="trace-detail-grid"><section className="trace-card span-panel"><h2>执行节点</h2><p className="muted">按真实父子关系与保存顺序展示。节点耗时不包含排队时间；缺失的时间不估算。</p>
        {spans.length ? <div className="span-tree" role="list" aria-label="Span 层级">{flattenSpans(spans).map(({ span, depth, warning }) => {
          const start = run.started_at && span.started_at ? Date.parse(span.started_at) - Date.parse(run.started_at) : NaN;
          const timeline = typeof run.duration_ms === 'number' && run.duration_ms > 0 && Number.isFinite(start) && typeof span.duration_ms === 'number';
          const view = traceStatus(span.status);
          const kind = nodeType(span.name);
          return <div role="listitem" key={span.span_id} style={{ marginLeft: `${depth * 14}px` }}><button className={`span-node ${view === 'error' || view === 'suspended' ? 'span-failed' : ''} ${selected?.span_id === span.span_id ? 'span-selected' : ''}`} aria-pressed={selected?.span_id === span.span_id} onClick={() => { const next = new URLSearchParams(params); next.set('span', span.span_id); setParams(next); }}>
            <div><strong>{nodeLabels[span.name] || span.name}</strong><StatusBadge status={span.status} /></div><small>{kind ? nodeTypes[kind] : '未归类'} · {span.name}</small><span>{durationText(span.duration_ms)}</span><time>{timeText(span.started_at)}</time>
            {timeline && <span className="span-time-track" aria-label="相对本次运行的真实时间位置"><i style={{ marginLeft: `${Math.min(99, Math.max(0, start / run.duration_ms! * 100))}%`, width: `${Math.min(100, Math.max(0.2, span.duration_ms! / run.duration_ms! * 100))}%` }} /></span>}
            {warning && <em>{warning}</em>}{span.error_code && <code>{span.error_code}</code>}
          </button></div>;
        })}</div> : <p>此 Run 没有已保存的 Span。可能在阶段开始前失败或发生追踪缺口。</p>}
        <p className="muted">节点身份 / 重试序号：{valueText(selected?.node_key)} / {valueText(selected?.node_attempt)}。Run 级尝试次数：{valueText(run.attempt)}。</p>
      </section>{selected ? <NodeInspector key={`${selected.span_id}:${refresh}`} span={selected} manifest={run.manifest} /> : <section className="trace-card trace-message"><h2>节点 Inspector</h2><p>{selectedId ? 'URL 中所选节点不属于当前 Run，请从左侧重新选择。' : '没有可检查的节点。'}</p></section>}</div>
      <p><Link className="trace-link" to={'/traces/compare?' + new URLSearchParams({ left: runId, ...(run.retry_of_run_id ? { right: run.retry_of_run_id } : {}) })}>与另一次运行对比</Link></p>
      <ManifestView manifest={run.manifest} />
    </>}
  </>;
}
