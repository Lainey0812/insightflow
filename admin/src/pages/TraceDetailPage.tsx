import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { RefreshCw, ArrowLeft } from 'lucide-react';
import { traceApi } from '../api/traces';
import type { RunDetail, TraceSpan } from '../types/traces';
import { TraceError, RevokeAccess } from '../features/traces/AccessPanel';
import { CoverageNotice, KeyValues, ManifestView, StatusBadge } from '../features/traces/TraceShared';
import { NodeInspector } from '../features/traces/NodeInspector';
import { WorkflowWaterfall } from '../features/traces/Waterfall';
import { LifecyclePanel } from '../features/traces/LifecyclePanel';
import { durationText, metadata, timeText, traceStatus, valueText } from '../features/traces/presentation';

export function TraceDetailPage() {
  const { runId = '' } = useParams(); const [params, setParams] = useSearchParams();
  const [detail, setDetail] = useState<RunDetail | null>(null), [spans, setSpans] = useState<TraceSpan[]>([]);
  const [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh(value => value + 1);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setDetail(null); setSpans([]);
    Promise.all([traceApi.run(runId, controller.signal), traceApi.spans(runId, controller.signal)])
      .then(async ([record, stages]) => {
        let merged = stages;
        const sessionId = record.run.session_id;
        if (sessionId && record.run.kind !== 'workflow' && typeof traceApi.workflow === 'function') {
          try {
            const root = await traceApi.workflow(sessionId, controller.signal);
            if (root && root.run_id !== record.run.run_id) {
              const all = await traceApi.spans(root.run_id, controller.signal);
              const byId = new Map(stages.map(span => [span.span_id, span]));
              const seen = new Set<string>();
              merged = all.map(span => { seen.add(span.span_id); return byId.get(span.span_id) ?? span; });
              merged.push(...stages.filter(span => !seen.has(span.span_id)));
            }
          } catch { if (controller.signal.aborted) return; }
        }
        if (!controller.signal.aborted) { setDetail(record); setSpans(merged); }
      })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, refresh]);
  const selectedId = params.get('span');
  const selected = selectedId ? spans.find(span => span.span_id === selectedId) : spans.find(span => { const view = traceStatus(span.status); return view === 'error' || view === 'suspended'; }) || spans[0];
  const phases = spans.length ? [{ label: '本次运行', spans }] : [];
  const selectSpan = (spanId: string) => { const next = new URLSearchParams(params); next.set('span', spanId); setParams(next); };
  const run = detail?.run;
  return <>
    <Link className="trace-link" to="/traces"><ArrowLeft size={14} />返回运行列表</Link>
    <div className="trace-heading"><div><span className="eyebrow">TRACE DETAIL</span><h1>运行详情</h1><p className="wrap-code">{runId}</p></div><div className="trace-actions"><button className="secondary-button" disabled={loading} onClick={reload}><RefreshCw size={14} />手动刷新</button>{detail && <RevokeAccess done={reload} />}</div></div>
    {loading ? <div className="trace-message" role="status">正在读取运行与节点记录…</div> : error ? <TraceError error={error} retry={reload} /> : run && detail && <>
      <div className="trace-detail-grid"><section className="trace-card run-summary waterfall-panel"><div className="section-heading"><h2>{run.kind === 'workflow' ? (run.manifest?.capture_scope === 'workflow_preparation' ? 'Workflow 准备阶段追踪' : 'Workflow 追踪记录') : '报告生成尝试'}</h2><StatusBadge status={run.status} /></div>
        <p className="muted">左侧是这条任务已保存的 workflow。条形按开始时间和耗时排布，缺失时间不估算。</p>
        {run.status === 'error' && <p className="trace-notice trace-warning">本次按错误展示。部分成功、失败和无可用报告都归入错误，不能按完整成功使用。</p>}
        {run.error_code && <p className="trace-danger"><strong>运行错误：</strong><code>{run.error_code}</code></p>}
        {run.retry_of_run_id ? <p>这是重试尝试。<Link className="trace-link" to={'/traces/' + encodeURIComponent(run.retry_of_run_id)}>查看上一次运行</Link></p> : typeof run.attempt === 'number' && run.attempt > 1 ? <p className="trace-warning">已记录第 {run.attempt} 次尝试，上一次 Trace 未采集或不可用。</p> : null}
        <h2>执行节点</h2>
        {phases.length ? <WorkflowWaterfall phases={phases} selectedId={selected?.span_id} onSelect={selectSpan} /> : <p>此 Run 没有已保存的 Span。可能在阶段开始前失败或发生追踪缺口。</p>}
        <p className="muted">节点身份 / 重试序号：{valueText(selected?.node_key)} / {valueText(selected?.node_attempt)}。Run 级尝试次数：{valueText(run.attempt)}。</p>
        <details><summary>运行字段与业务状态</summary><div className="run-summary-grid"><KeyValues source={{ ...run, start: timeText(run.started_at), queued: timeText(run.queued_at), finish: timeText(run.finished_at), recovered: timeText(run.recovered_at), duration: durationText(run.duration_ms), prompt: metadata(run.manifest?.versions).prompt_version }} fields={{ session_id: '会话', execution_id: '执行', report_id: '报告引用', attempt: run.kind === 'workflow' ? 'Root 记录序号' : '报告尝试次数', queued: '排队时间', start: '实际开始', finish: '实际结束', recovered: '恢复发现时间', duration: '整体耗时', prompt: 'Prompt 版本' }} /></div>
          {run.kind !== 'workflow' && <><KeyValues source={metadata(detail.business_source)} fields={{ available: '业务来源可读', status: '最新报告生成状态', latest_attempt: '最新业务尝试', same_attempt: '是否对应本次尝试', report_status: '报告内容状态', goal_coverage: '目标覆盖' }} /><p className="muted">业务 completed 不等于报告内容 complete；部分成功、无证据和追踪中断各自保留。</p></>}
        </details>
      </section>{selected ? <NodeInspector key={`${selected.span_id}:${refresh}`} span={selected} manifest={run.manifest} /> : <section className="trace-card trace-message"><h2>节点信息</h2><p>{selectedId ? 'URL 中所选节点不属于当前 Run，请从左侧重新选择。' : '没有可检查的节点。'}</p></section>}</div>
      <CoverageNotice degraded={detail.collector_degraded} incomplete={run.integrity === 'incomplete'} scope={run.manifest?.capture_scope || (run.kind === 'workflow' ? 'unknown_workflow' : undefined)} />
      <LifecyclePanel run={run} refresh={refresh} />
      <p><Link className="trace-link" to={'/traces/compare?' + new URLSearchParams({ left: runId, ...(run.retry_of_run_id ? { right: run.retry_of_run_id } : {}) })}>与另一次运行对比</Link></p>
      <ManifestView manifest={run.manifest} />
    </>}
  </>;
}
