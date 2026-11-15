import { useState } from 'react';
import type { ReactNode } from 'react';
import type { TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { durationText, timeText, traceStatus } from '../traces/presentation';
import { StatusBadge } from '../traces/TraceShared';
import { jsonText, LlmCallSections, useLlmCalls } from './LlmCallDetail';

export function CopyJson({ text }: { text: string }) {
  const [note, setNote] = useState('');
  return <p><button type="button" onClick={() => {
    const write = navigator.clipboard?.writeText;
    if (!write) { setNote('复制失败'); return; }
    write.call(navigator.clipboard, text).then(() => setNote('已复制'), () => setNote('复制失败'));
  }}>复制 JSON</button>{note && <span className="muted"> {note}</span>}</p>;
}
export function JsonDisclosure({ title, value }: { title: string; value: unknown }) {
  if (value == null) return <p className="muted">没有已保存的 JSON。</p>;
  const text = jsonText(value);
  return <details><summary>{title}</summary><CopyJson text={text} /><pre className="wf-json" tabIndex={0}>{text}</pre></details>;
}
function stackText(node: TraceSpan, events: TraceEvent[]): string {
  const attrs = node.attributes || {};
  for (const key of ['error_stack', 'stack', 'traceback', 'stacktrace']) {
    if (typeof attrs[key] === 'string' && attrs[key]) return String(attrs[key]);
  }
  for (const event of events) {
    const payload = event.payload || {};
    for (const key of ['error_stack', 'stack', 'traceback', 'stacktrace']) {
      if (typeof payload[key] === 'string' && payload[key]) return String(payload[key]);
    }
  }
  return '';
}

export function NodeChrome({ node, trace, title, input, output }: { node: TraceSpan; trace: WorkflowObservation; title: string; input: ReactNode | ((state: { loaded: ReturnType<typeof useLlmCalls>['loaded']; settled: boolean }) => ReactNode); output: ReactNode | ((state: { loaded: ReturnType<typeof useLlmCalls>['loaded']; settled: boolean }) => ReactNode) }) {
  const attrs = node.attributes || {};
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const calls = trace.llm_calls.filter(call => call.span_id === node.span_id).sort((left, right) => left.call_sequence - right.call_sequence);
  const { loaded, settled } = useLlmCalls(calls);
  const [tab, setTab] = useState(failed ? 'input' : 'output');
  const tabs = [['input', 'Input'], ['output', 'Output'], ...(calls.length ? [['llm', 'LLM'] as const] : [])];
  const current = tabs.some(([id]) => id === tab) ? tab : 'output';
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const brief = node.error_message || (typeof attrs.error_message === 'string' ? attrs.error_message : '');
  const quality = typeof attrs.quality_issue_count === 'number' ? attrs.quality_issue_count : null;
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header className="wf-detail-head">
      <h2>{title}</h2>
      <StatusBadge status={node.status} />
      <span>{durationText(node.duration_ms)}</span>
      {quality != null && <span>质量信号 {quality} 条</span>}
    </header>
    <code className="wf-id">{node.span_id}</code>
    <p className="muted">{timeText(node.started_at)} – {timeText(node.finished_at)}{node.node_attempt ? ` · 第 ${node.node_attempt} 次` : ''}</p>
    {failed && <section className="wf-profiler-error">
      <p><code>{node.error_code || '未采集'}</code></p>
      <p>{brief || '没有已保存的错误说明。'}</p>
      <details><summary>错误详情</summary>{stackText(node, events) ? <pre className="wf-json" tabIndex={0}>{stackText(node, events)}</pre> : <p className="muted">没有更多已保存的错误详情。</p>}</details>
    </section>}
    <div className="trace-tabs" role="tablist" aria-label="节点内容">
      {tabs.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={current === id} className={`trace-tab ${current === id ? 'trace-tab-active' : ''}`} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    <div role="tabpanel">
      {current === 'input' && (typeof input === 'function' ? input({ loaded, settled }) : input)}
      {current === 'output' && (typeof output === 'function' ? output({ loaded, settled }) : output)}
      {current === 'llm' && <section><LlmCallSections calls={calls} loaded={loaded} attrs={attrs} /></section>}
    </div>
  </aside>;
}
