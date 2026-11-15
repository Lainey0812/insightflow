import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { promptApi } from '../api/prompts';
import { ApiError } from '../api/client';
import type { CallResponseContent } from '../types/prompts';
import { jsonText, nodeLabels, RegistryError, usePromptData, versionPath } from '../features/prompts/PromptShared';
import { KeyValues } from '../features/traces/TraceShared';
import { durationText, timeText } from '../features/traces/presentation';

function RawRequest({ id, requestId, available }: { id: string; requestId: string; available: string }) {
  const [token, setToken] = useState(''), [raw, setRaw] = useState<Record<string, unknown> | null>(null), [pending, setPending] = useState(false), [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault(); const secret = token; setToken(''); setRaw(null); setError(''); setPending(true);
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    try {
      const response = await promptApi.raw(id, secret, controller.signal);
      if (response.request_snapshot_id !== requestId) throw new ApiError('INVALID_RESPONSE', '快照关联不一致。');
      if (!controller.signal.aborted) setRaw(response.payload);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof ApiError && cause.status === 403 ? '快照读取授权失败，完整请求未展示。' : cause instanceof ApiError && cause.status === 410 ? '原始请求已过期或未保留。' : '读取失败，未将失败当作空请求。');
    } finally { if (!controller.signal.aborted) { setPending(false); setToken(''); } }
  }
  return <section className="trace-card"><h2>受控原始请求</h2><p className="muted">默认仅显示脱敏摘要。完整请求可能包含用户目标、字段与业务结果，仅在额外授权后读取；凭证不写入 URL 或本地存储。</p>
    {available === 'retained' ? <form className="access-form" onSubmit={submit}><label>快照读取凭证<input type="password" autoComplete="off" required maxLength={2048} value={token} onChange={e => setToken(e.target.value)} /></label><button className="primary-button" disabled={pending}>{pending ? '授权读取中…' : '授权查看完整请求'}</button></form> : <p className="unavailable-note">原始请求 {available === 'expired' ? '已过期' : 'unavailable'}，不重建历史内容。</p>}
    {error && <p role="alert" className="trace-danger">{error}</p>}
    {raw && <><p className="trace-warning trace-notice">以下为已授权读取的实际出站 JSON。</p><button className="secondary-button" onClick={() => setRaw(null)}>隐藏原始请求</button><pre className="prompt-code" tabIndex={0}>{jsonText(raw)}</pre></>}
  </section>;
}
function readable(content: string) {
  try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; }
}
function RawResponse({ id, available, kind }: { id: string; available: string; kind?: string | null }) {
  const [token, setToken] = useState(''), [raw, setRaw] = useState<CallResponseContent | null>(null), [pending, setPending] = useState(false), [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault(); const secret = token; setToken(''); setRaw(null); setError(''); setPending(true);
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    try {
      const response = await promptApi.rawResponse(id, secret, controller.signal);
      if (!controller.signal.aborted) setRaw(response);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof ApiError && cause.status === 403 ? '快照读取授权失败，模型返回未展示。' : cause instanceof ApiError && cause.status === 410 ? '模型返回未保留或已过期。' : cause instanceof ApiError && cause.status === 503 ? '存档返回完整性校验失败，未展示内容。' : '读取失败，未将失败当作空返回。');
    } finally { if (!controller.signal.aborted) { setPending(false); setToken(''); } }
  }
  const unavailable = available === 'expired' ? '模型返回已过期。' : '模型返回未保留：早于本功能的调用、无响应（如超时）或保存失败。不重建历史内容。';
  return <section className="trace-card"><h2>受控模型返回</h2><p className="muted">模型原始返回可能包含业务结果与被拒候选，与完整请求使用同一快照读取凭证；凭证不写入 URL 或本地存储。</p>
    {available === 'retained' ? <>{kind === 'raw_body' && <p className="trace-warning trace-notice">本次调用未成功解析，保留的是 Provider 原始响应体。</p>}
      <form className="access-form" onSubmit={submit}><label>快照读取凭证（模型返回）<input type="password" autoComplete="off" required maxLength={2048} value={token} onChange={e => setToken(e.target.value)} /></label><button className="primary-button" disabled={pending}>{pending ? '授权读取中…' : '授权查看模型返回'}</button></form></>
      : <p className="unavailable-note">{unavailable}</p>}
    {error && <p role="alert" className="trace-danger">{error}</p>}
    {raw && <><p className="trace-warning trace-notice">{raw.kind === 'content' ? '以下为模型返回的消息内容（业务校验前）。' : '以下为调用失败时的 Provider 原始响应体。'}{raw.truncated ? '内容超过 64KB，已截断。' : ''}</p>
      <button className="secondary-button" onClick={() => setRaw(null)}>隐藏模型返回</button><pre className="prompt-code" tabIndex={0} data-testid="raw-response">{readable(raw.content)}</pre></>}
  </section>;
}
export function PromptCallPage() {
  const { callId = '' } = useParams(); const state = usePromptData(signal => promptApi.call(callId, signal), [callId]);
  const data = state.data, call = data?.call, snapshot = data?.request_snapshot;
  return <><Link className="trace-link" to="/prompts">返回 Prompt 列表</Link><div className="trace-heading"><div><span className="eyebrow">LLM CALL · CONTROLLED ACCESS</span><h1>模型调用详情</h1><p className="wrap-code">{callId}</p></div><button className="secondary-button" onClick={state.reload} disabled={state.loading}>刷新调用</button></div>
    {state.loading ? <p className="trace-message" role="status">正在读取调用元信息…</p> : state.error ? <RegistryError error={state.error} retry={state.reload} /> : call && data && <>
      <section className="trace-card"><h2>{nodeLabels[call.node_id] || call.node_id}</h2><p className="trace-notice">调用状态仅描述 Provider 响应协议，不能代替业务校验结果。</p>
        <KeyValues source={{ ...call, started_at: timeText(call.started_at), finished_at: timeText(call.finished_at), duration: durationText(call.duration_ms), model: snapshot?.model_parameters.model ?? 'unknown' }} fields={{ status: '调用状态', model: '请求模型', started_at: '开始时间', finished_at: '结束时间', duration: '耗时', call_sequence: '调用序号', retry_index: '重试序号（从 0 开始）', retry_reason: '重试原因', operation_id: '操作关联 ID', error_code: '错误代码', outcome_scope: '状态范围' }} />
        <p><Link className="trace-link" to={versionPath(call.node_id, call.template_snapshot_id)}>查看关联 Prompt 版本</Link></p>
        {call.retry_of_call_id && <p><Link className="trace-link" to={'/prompts/calls/' + encodeURIComponent(call.retry_of_call_id)}>查看上一次模型调用</Link></p>}
        {data.trace_available && call.run_id ? <p><Link className="trace-link" to={'/traces/' + encodeURIComponent(call.run_id) + (call.span_id ? '?' + new URLSearchParams({ span: call.span_id }) : '')}>打开关联 Run / Span</Link></p> : <p className="unavailable-note">{call.run_id ? '关联 Trace unavailable。' : '此调用尚无持久 Trace Run，不生成虚构关联。'}</p>}
      </section>
      <section className="trace-card"><h2>请求脱敏摘要</h2><p>消息与输出 Schema 正文默认隐藏。</p>{snapshot ? <KeyValues source={{ ...snapshot, expires_at: snapshot.expires_at ?? '未设置自动到期', raw_availability: data.raw_availability }} fields={{ request_snapshot_id: '请求快照', messages_hash: '消息哈希', schema_hash: '输出 Schema 哈希', request_hash: '最终请求哈希', expires_at: '原文保留期限', raw_availability: '原文保留状态' }} /> : <p>请求元信息 unavailable。</p>}</section>
      {snapshot && <RawRequest key={callId} id={callId} requestId={snapshot.request_snapshot_id} available={data.raw_availability} />}
      <RawResponse key={'response-' + callId} id={callId} available={data.response_availability ?? 'unavailable'} kind={data.response_kind} />
    </>}
  </>;
}
