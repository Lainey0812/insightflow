import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { promptApi } from '../../api/prompts';
import { ApiError } from '../../api/client';
import type { CallSummary } from '../../types/prompts';
import type { Metadata } from '../../types/traces';
import type { WorkflowCall } from '../../types/workflows';
import { versionPath } from '../prompts/PromptShared';
import { durationText, timeText, traceStatus, traceStatusLabels, valueText } from '../traces/presentation';

export type Hold = 'loading' | 'retained' | 'expired' | 'unavailable' | 'locked' | 'missing';
export interface LoadedCall {
  summary: CallSummary | null; version: string; request: Metadata | null; requestHold: Hold;
  responseText: string; responseHold: Hold; responseCode: string | null;
}

export function record(value: unknown): Metadata | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Metadata : null;
}
export function given(value: unknown): string {
  return value === null ? '未给出' : valueText(value);
}
export function jsonText(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? '';
  return text.length > 20000 ? text.slice(0, 20000) + '\n…' : text;
}
export function parseObject(text: string): Metadata | null {
  try { return record(JSON.parse(text)); } catch { return null; }
}
export function userPayload(payload: Metadata | null): Metadata | null {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const user = [...messages].reverse().find(item => record(item)?.role === 'user');
  const content = record(user)?.content;
  return typeof content === 'string' ? parseObject(content) : null;
}
function param(value: unknown, ready: boolean): unknown {
  if (value != null && value !== '') return value;
  return ready ? '未采集' : undefined;
}
function endpointOf(source: Metadata): string {
  for (const key of ['endpoint', 'endpoint_url', 'url', 'request_url']) {
    const value = source[key];
    if (typeof value === 'string' && /^https?:\/\//.test(value)) return value;
  }
  return '';
}
function metric(source: Metadata, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return '未采集';
}
export function requestText(payload: Metadata): string {
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  if (!messages.length) return jsonText(payload);
  return messages.map(message => {
    const item = record(message);
    if (!item) return jsonText(message);
    const content = typeof item.content === 'string' ? item.content : jsonText(item.content);
    return `[${String(item.role || 'message')}]\n${content.length > 12000 ? content.slice(0, 12000) + '\n…' : content}`;
  }).join('\n\n');
}
function holdCopy(hold: Hold, kind: 'request' | 'response'): string {
  if (hold === 'loading') return '正在读取已保存原文…';
  if (hold === 'expired' || hold === 'unavailable') return kind === 'request' ? '完整请求未保留或已过期，不重建。' : '模型原始返回未保留或已过期，不重建。';
  if (hold === 'missing') return '调用元信息未能读取。';
  return '原文未能读取，未把失败当成空原文。';
}
export function Facts({ rows }: { rows: [string, unknown][] }) {
  const visible = rows.filter(([, value]) => value !== undefined);
  if (!visible.length) return null;
  return <dl className="wf-refs">{visible.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{given(value)}</code></dd></div>)}</dl>;
}
function CredentialForm({ callId, mode }: { callId: string; mode: 'request' | 'response' }) {
  const [token, setToken] = useState('');
  const [text, setText] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    const secret = token;
    setToken(''); setError(''); setPending(true);
    try {
      if (mode === 'request') setText(requestText((await promptApi.raw(callId, secret)).payload));
      else setText((await promptApi.rawResponse(callId, secret)).content);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 410 ? holdCopy('expired', mode) : '快照读取授权失败，原文未展示。');
    } finally { setPending(false); }
  }
  if (text) return <pre className="wf-json" tabIndex={0}>{text}</pre>;
  return <form onSubmit={submit}><p className="muted">当前环境要求快照凭证。凭证只用于这次请求，不写入 URL。</p><label>{mode === 'request' ? '快照读取凭证' : '快照读取凭证（模型返回）'}<input type="password" autoComplete="off" required maxLength={2048} value={token} onChange={event => setToken(event.target.value)} /></label><button className="primary-button" disabled={pending} type="submit">{pending ? '授权读取中…' : mode === 'request' ? '授权查看完整请求' : '授权查看模型返回'}</button>{error && <p role="alert">{error}</p>}</form>;
}

export function useLlmCalls(calls: WorkflowCall[]) {
  const [loaded, setLoaded] = useState<Record<string, LoadedCall>>({});
  const [settled, setSettled] = useState(!calls.length);
  const callKey = calls.map(call => call.call_id).join(',');
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    if (!calls.length) { setSettled(true); return () => controller.abort(); }
    setSettled(false);
    (async () => {
      const next: Record<string, LoadedCall> = {};
      for (const call of calls) {
        const item: LoadedCall = { summary: null, version: '', request: null, requestHold: 'missing', responseText: '', responseHold: 'missing', responseCode: null };
        try { item.summary = await promptApi.call(call.call_id, controller.signal); } catch { /* 保留 Workflow 里的调用编号。 */ }
        try {
          const detail = await promptApi.detail(call.node_id, call.template_snapshot_id, controller.signal);
          item.version = detail.template.version;
        } catch { /* 版本号留在未采集。 */ }
        const requestHold = item.summary?.raw_availability;
        const responseHold = item.summary?.response_availability;
        if (requestHold === 'retained') {
          try { item.request = (await promptApi.raw(call.call_id, '', controller.signal)).payload; item.requestHold = 'retained'; }
          catch (cause) { item.requestHold = cause instanceof ApiError && cause.status === 403 ? 'locked' : cause instanceof ApiError && cause.status === 410 ? 'expired' : 'missing'; }
        } else item.requestHold = requestHold === 'expired' || requestHold === 'unavailable' ? requestHold : 'missing';
        if (responseHold === 'retained') {
          try {
            const body = await promptApi.rawResponse(call.call_id, '', controller.signal);
            item.responseText = body.content; item.responseCode = body.error_code; item.responseHold = 'retained';
          } catch (cause) { item.responseHold = cause instanceof ApiError && cause.status === 403 ? 'locked' : cause instanceof ApiError && cause.status === 410 ? 'expired' : 'missing'; }
        } else item.responseHold = responseHold === 'expired' || responseHold === 'unavailable' ? responseHold : 'missing';
        next[call.call_id] = item;
      }
      if (!cancelled) { setLoaded(next); setSettled(true); }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [callKey]);
  return { loaded, settled };
}

export function LlmCallSections({ calls, loaded, attrs }: { calls: WorkflowCall[]; loaded: Record<string, LoadedCall>; attrs: Metadata }) {
  if (!calls.length) return <p className="muted">这条节点没有已采集的模型调用。不从其他节点补。</p>;
  return <>{calls.map(call => {
    const item = loaded[call.call_id];
    const params = item?.summary?.request_snapshot?.model_parameters || {};
    const observed = item?.summary?.provider_observation || {};
    const numbers = { ...attrs, ...observed, ...params, ...(record(params.usage) || {}) };
    const status = item?.summary?.call.status || call.status;
    const errorCode = item?.responseCode || item?.summary?.call.error_code || null;
    return <section key={call.call_id}>
      <h3>LLM Call</h3>
      <dl className="wf-refs">
        <div><dt>Call ID</dt><dd><code>{call.call_id}</code></dd></div>
        <div><dt>模型名称</dt><dd>{valueText(params.model ?? observed.model ?? attrs.model)}</dd></div>
        <div><dt>Endpoint URL</dt><dd>{endpointOf({ ...attrs, ...observed }) || '未采集'}</dd></div>
        <div><dt>Prompt 模板</dt><dd><code>{call.template_snapshot_id}</code></dd></div>
        <div><dt>模板版本</dt><dd>{item?.version || '未采集'}</dd></div>
        <div><dt>调用状态</dt><dd>{traceStatusLabels[traceStatus(status)]}</dd></div>
        <div><dt>开始时间</dt><dd>{timeText(item?.summary?.call.started_at)}</dd></div>
        <div><dt>延迟</dt><dd>{durationText(item?.summary?.call.duration_ms ?? call.duration_ms)}</dd></div>
        <div><dt>Input Token</dt><dd>{item ? metric(numbers, ['input_tokens', 'prompt_tokens']) : '未采集'}</dd></div>
        <div><dt>Output Token</dt><dd>{item ? metric(numbers, ['output_tokens', 'completion_tokens']) : '未采集'}</dd></div>
        <div><dt>Cached Token</dt><dd>{item ? metric(numbers, ['cached_tokens', 'cache_read_tokens']) : '未采集'}</dd></div>
      </dl>
      <h3>模型参数</h3>
      <Facts rows={[['temperature', param(params.temperature ?? observed.temperature, !!item)], ['top_p', param(params.top_p ?? observed.top_p, !!item)], ['max_tokens', param(params.max_tokens ?? observed.max_tokens, !!item)], ['enable_thinking', param(params.enable_thinking ?? observed.enable_thinking, !!item)], ['stream', param(params.stream ?? observed.stream, !!item)]]} />
      <p><Link className="wf-link" to={versionPath(call.node_id, call.template_snapshot_id)}>查看 Prompt 版本</Link></p>
      <p><Link className="wf-link" to={'/prompts/calls/' + encodeURIComponent(call.call_id)}>查看本次模型调用</Link></p>
      {call.retry_index > 0 && <p className="wf-warning">请求重试 #{call.retry_index}，前次：{call.retry_of_call_id || '引用未采集'}</p>}
      {errorCode && <p><code>{errorCode}</code></p>}
      <h3>请求消息</h3>
      {item?.requestHold === 'retained' && item.request ? <pre className="wf-json" tabIndex={0}>{requestText(item.request)}</pre> : item?.requestHold === 'locked' ? <CredentialForm callId={call.call_id} mode="request" /> : <p className="muted">{holdCopy(item?.requestHold || 'loading', 'request')}</p>}
      <h3>原始响应</h3>
      {item?.responseHold === 'retained' ? <pre className="wf-json" tabIndex={0}>{item.responseText || '已保留的响应为空。'}</pre> : item?.responseHold === 'locked' ? <CredentialForm callId={call.call_id} mode="response" /> : <p className="muted">{holdCopy(item?.responseHold || 'loading', 'response')}</p>}
    </section>;
  })}</>;
}
