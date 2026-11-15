import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { promptApi } from '../../api/prompts';
import { ApiError } from '../../api/client';
import { readAdminConfig } from '../../config/env';
import type { CallSummary } from '../../types/prompts';
import type { Metadata, TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowCall, WorkflowObservation } from '../../types/workflows';
import { versionPath } from '../prompts/PromptShared';
import { StatusBadge } from '../traces/TraceShared';
import { detailKind, detailKinds, durationText, timeText, traceStatus, traceStatusLabels, valueText, type DetailKind } from '../traces/presentation';
import { InputSummary } from './WorkflowShared';

const names: Record<string, string> = { data_profiler: '数据画像', intent_parser: '需求理解', analysis_planner: '分析规划', plan_validator: '计划校验', evidence_builder: '证据构建', insight_generator: '洞察生成', fact_validator: '事实校验', report_assembler: '报告组装', report_persistence: '报告保存', analysis_engine: '分析执行', hitl: '人工审核', chart_builder: '图表构建' };
const decisionKeys = ['condition_matched', 'branch', 'selected_branch', 'matched_branch', 'next_action', 'validation_role', 'coverage_status', 'outcome', 'command', 'execution_status', 'accepted_count', 'rejected_count', 'blocked_count', 'executable_count', 'f0_count', 'f1_count', 'f2_count', 'unmet_core_count'];
const outputKeys = ['result_ref', 'result_refs', 'report_id', 'approval_id', 'plan_version_id', 'dataset_id', 'dataset_version', 'operation_id', 'report_run_id', 'execution_id', 'row_count', 'column_count', 'evidence_count', 'chart_count', 'insight_count', 'candidate_count', 'report_status', 'goal_coverage'];

function pick(attrs: Metadata, keys: string[]): Metadata {
  return Object.fromEntries(keys.filter(key => attrs[key] != null && attrs[key] !== '').map(key => [key, attrs[key]]));
}
function jsonText(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? '';
  return text.length > 8000 ? text.slice(0, 8000) + '\n…' : text;
}
function JsonBlock({ value, empty }: { value: unknown; empty: string }) {
  if (value == null || (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value as object).length) || (Array.isArray(value) && !value.length)) return <p className="muted">{empty}</p>;
  return <pre className="wf-json" tabIndex={0}>{jsonText(value)}</pre>;
}
function Facts({ source }: { source: Metadata }) {
  const entries = Object.entries(source);
  if (!entries.length) return null;
  return <dl className="wf-refs">{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{typeof value === 'boolean' ? String(value) : valueText(value)}</code></dd></div>)}</dl>;
}
const hiddenAttribute = new Set(['workflow_id', 'root_run_id', 'node_name']);
function recorded(attrs: Metadata): Metadata {
  return Object.fromEntries(Object.entries(attrs).filter(([key, value]) => !hiddenAttribute.has(key) && value != null && value !== ''));
}
function inputObject(attrs: Metadata): Metadata {
  const collected = recorded(attrs);
  for (const key of ['state', 'variables', 'global_state', 'input']) if (attrs[key] != null) collected[key] = attrs[key];
  return collected;
}
function endpoint(attrs: Metadata): string {
  for (const key of ['endpoint', 'endpoint_url', 'url', 'request_url']) {
    const value = attrs[key];
    if (typeof value === 'string' && /^https?:\/\//.test(value)) return value;
  }
  return '';
}
function httpStatus(attrs: Metadata): string {
  for (const key of ['http_status', 'status_code', 'http_code']) {
    const value = attrs[key];
    if (typeof value === 'number' || (typeof value === 'string' && value.trim())) return String(value);
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
function usageOf(summary: CallSummary | null, attrs: Metadata): Metadata {
  const params = summary?.request_snapshot?.model_parameters;
  const usage = params && typeof params.usage === 'object' && params.usage ? params.usage as Metadata : {};
  const observed = summary?.provider_observation || {};
  return { ...attrs, ...observed, ...(params || {}), ...usage };
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
function chunksOf(attrs: Metadata): Metadata[] {
  const raw = attrs.retrieved_chunks ?? attrs.chunks;
  return Array.isArray(raw) ? raw.filter((item): item is Metadata => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

function PromptTab({ node, calls }: { node: TraceSpan; calls: WorkflowCall[] }) {
  const attrs = node.attributes || {};
  const [summaries, setSummaries] = useState<Record<string, CallSummary | null>>({});
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const callKey = calls.map(call => call.call_id).join(',');
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setSummaries({}); setVersions({}); setNote('');
    if (!calls.length) return () => controller.abort();
    (async () => {
      for (const call of calls) {
        try {
          const summary = await promptApi.call(call.call_id, controller.signal);
          if (!cancelled) setSummaries(prev => ({ ...prev, [call.call_id]: summary }));
        } catch (cause) {
          if (!cancelled && !(cause instanceof DOMException && cause.name === 'AbortError')) setNote('调用元信息未能读取。下面仍是 Workflow 里已保存的快照编号。');
        }
        try {
          const detail = await promptApi.detail(call.node_id, call.template_snapshot_id, controller.signal);
          if (!cancelled) setVersions(prev => ({ ...prev, [call.call_id]: detail.template.version }));
        } catch { /* 版本号留在未采集，不把模板正文放进面板。 */ }
      }
    })();
    return () => { cancelled = true; controller.abort(); };
    // callKey 变化才重新读取；摘要写回 state 时不重复请求。
  }, [callKey]);
  if (!calls.length) return <p className="muted">这条节点没有已采集的模型调用。Prompt、原文和 Token 不能从别的节点补。</p>;
  return <div>
    {note && <p className="muted">{note}</p>}
    {calls.map(call => {
      const summary = summaries[call.call_id] ?? null;
      const params = summary?.request_snapshot?.model_parameters || {};
      const config = summary?.request_snapshot?.client_config || {};
      const observed = summary?.provider_observation || {};
      const numbers = usageOf(summary, attrs);
      const fields: Metadata = {
        temperature: params.temperature ?? observed.temperature ?? attrs.temperature,
        max_tokens: params.max_tokens ?? observed.max_tokens ?? attrs.max_tokens,
        top_p: params.top_p ?? observed.top_p ?? attrs.top_p,
        enable_thinking: params.enable_thinking ?? observed.enable_thinking ?? attrs.enable_thinking,
        timeout_seconds: config.timeout_seconds ?? observed.timeout_seconds ?? attrs.timeout_seconds,
        stream: params.stream ?? observed.stream,
      };
      return <section key={call.call_id}>
        <h3>Prompt &amp; Meta</h3>
        <dl className="wf-refs">
          <div><dt>Prompt Version ID</dt><dd><code>{call.template_snapshot_id}</code></dd></div>
          <div><dt>登记版本号</dt><dd>{versions[call.call_id] || '未采集'}</dd></div>
          <div><dt>Model Name</dt><dd>{valueText(params.model ?? attrs.model)}</dd></div>
          <div><dt>HTTP 状态码</dt><dd>{httpStatus({ ...attrs, ...observed }) || '未采集'}</dd></div>
          <div><dt>Endpoint URL</dt><dd>{endpoint({ ...attrs, ...observed }) || '未采集'}</dd></div>
        </dl>
        <h3>Generation Parameters</h3>
        <Facts source={Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, value == null || value === '' ? '未采集' : value]))} />
        <p><Link className="wf-link" to={versionPath(call.node_id, call.template_snapshot_id)}>查看 Prompt 版本</Link></p>
        <p><Link className="wf-link" to={'/prompts/calls/' + encodeURIComponent(call.call_id)}>查看本次模型调用</Link></p>
        <p>{traceStatusLabels[traceStatus(call.status)]} · 请求 #{call.call_sequence} · {durationText(call.duration_ms)}</p>
        {call.retry_index > 0 && <p className="wf-warning">请求重试 #{call.retry_index}，前次：{call.retry_of_call_id || '引用未采集'}</p>}
        <h3>Input Payload</h3>
        <AuthorizedText callId={call.call_id} available={summary?.raw_availability} mode="request" />
        <h3>Raw Output</h3>
        <AuthorizedText callId={call.call_id} available={summary?.response_availability} mode="response" />
        <h3>Metrics</h3>
        <dl className="wf-refs">
          <div><dt>Input Token</dt><dd>{metric(numbers, ['input_tokens', 'prompt_tokens'])}</dd></div>
          <div><dt>Output Token</dt><dd>{metric(numbers, ['output_tokens', 'completion_tokens'])}</dd></div>
          <div><dt>Cached Token</dt><dd>{metric(numbers, ['cached_tokens', 'cache_read_tokens'])}</dd></div>
          <div><dt>预估成本（$）</dt><dd>{metric(numbers, ['estimated_cost', 'cost', 'cost_usd'])}</dd></div>
        </dl>
      </section>;
    })}
  </div>;
}
function snapshotError(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 403) return '快照读取授权失败，原文未展示。';
  if (cause instanceof ApiError && cause.status === 410) return '原文未保留或已过期。';
  return '读取失败，未把失败当成空原文。';
}
function requestText(payload: Record<string, unknown>): string {
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  if (!messages.length) return jsonText(payload);
  return messages.map(message => {
    if (!message || typeof message !== 'object') return jsonText(message);
    const item = message as Record<string, unknown>;
    const content = typeof item.content === 'string' ? item.content : jsonText(item.content);
    const clipped = content.length > 12000 ? content.slice(0, 12000) + '\n…' : content;
    return `[${String(item.role || 'message')}]\n${clipped}`;
  }).join('\n\n');
}
function AuthorizedText({ callId, available, mode }: { callId: string; available?: string; mode: 'request' | 'response' }) {
  const [token, setToken] = useState(''), [text, setText] = useState(''), [pending, setPending] = useState(false), [error, setError] = useState(''), [locked, setLocked] = useState(false);
  useEffect(() => {
    if (available !== 'retained') return;
    const controller = new AbortController();
    let cancelled = false;
    setPending(true); setError(''); setLocked(false); setText('');
    const job = mode === 'request'
      ? promptApi.raw(callId, '', controller.signal).then(response => { if (!cancelled) setText(requestText(response.payload)); })
      : promptApi.rawResponse(callId, '', controller.signal).then(response => { if (!cancelled) setText(response.content); });
    job.catch(cause => {
      if (cancelled || (cause instanceof DOMException && cause.name === 'AbortError')) return;
      if (cause instanceof ApiError && cause.status === 403) setLocked(true);
      else setError(snapshotError(cause));
    }).finally(() => { if (!cancelled) setPending(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [available, callId, mode]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const secret = token;
    setToken(''); setError(''); setPending(true);
    try {
      if (mode === 'request') setText(requestText((await promptApi.raw(callId, secret)).payload));
      else setText((await promptApi.rawResponse(callId, secret)).content);
      setLocked(false);
    } catch (cause) { setError(snapshotError(cause)); }
    finally { setPending(false); }
  }
  if (available && available !== 'retained') return <p className="muted">{mode === 'request' ? '完整拼装请求未保留，不重建 System Prompt、History 或 User Message。' : '模型原始返回未保留，不重建。'}</p>;
  if (text) return <pre className="wf-json" tabIndex={0}>{text.length > 64000 ? text.slice(0, 64000) + '\n…' : text}</pre>;
  if (pending && !locked) return <p className="muted">正在读取已保存原文…</p>;
  return <div>
    <p className="muted">{locked ? '当前环境要求快照凭证。凭证只用于这次请求，不写入 URL。' : '还不知道原文是否保留。可以提交凭证；没有凭证时这里留空。'}</p>
    <form onSubmit={submit}><label>{mode === 'request' ? '快照读取凭证' : '快照读取凭证（模型返回）'}<input type="password" autoComplete="off" required maxLength={2048} value={token} onChange={event => setToken(event.target.value)} /></label><button className="primary-button" disabled={pending} type="submit">{pending ? '授权读取中…' : mode === 'request' ? '授权查看完整请求' : '授权查看模型返回'}</button></form>
    {error && <p role="alert">{error}</p>}
  </div>;
}
function plain(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(plain);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Metadata).filter(([, item]) => item != null).map(([key, item]) => [key, plain(item)]));
}
function LinkedRecords({ attrs, trace }: { attrs: Metadata; trace: WorkflowObservation }) {
  const text = (key: string) => typeof attrs[key] === 'string' ? String(attrs[key]) : '';
  const rows = [
    trace.executions.find(item => item.execution_id === text('execution_id')),
    trace.plan_versions.find(item => item.plan_version_id === text('plan_version_id') || item.plan_id === text('plan_id')),
    trace.approvals.find(item => item.approval_id === text('approval_id')),
    trace.reports.find(item => item.report_id === text('report_id') || (text('execution_id') && item.execution_id === text('execution_id'))),
    trace.report_generations.find(item => item.execution_id === text('execution_id') || item.report_id === text('report_id')),
  ].filter((item): item is Metadata => !!item);
  if (!rows.length) return null;
  return <div><h3>已关联记录</h3>{rows.map((row, index) => <JsonBlock key={index} value={plain(row)} empty="关联记录没有可读字段。" />)}</div>;
}
function eventFacts(event: TraceEvent) {
  if (event.event_type === 'span.started' || event.event_type === 'span.finished' || !event.payload) return null;
  const source = Object.fromEntries(Object.entries(event.payload).filter(([key, value]) => !['workflow_id', 'root_run_id', 'node_name'].includes(key) && value != null && (typeof value !== 'object' || Array.isArray(value))));
  return Object.keys(source).length ? <Facts source={source} /> : null;
}
function DatasetProfileView({ datasetId, version }: { datasetId: string; version: string }) {
  const [fields, setFields] = useState<Metadata[]>([]);
  const [summary, setSummary] = useState<Metadata>({});
  const [note, setNote] = useState('正在读取数据集画像…');
  useEffect(() => {
    const controller = new AbortController();
    const base = readAdminConfig().apiBaseUrl.replace(/\/admin\/?$/, '').replace(/\/+$/, '');
    fetch(`${base}/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(version)}/profile`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => { if (!response.ok) throw new Error(String(response.status)); return response.json() as Promise<Metadata>; })
      .then(profile => {
        if (controller.signal.aborted) return;
        if (!profile || profile.dataset_id !== datasetId) { setNote('数据集画像结构不正确。'); return; }
        const options = profile.options && typeof profile.options === 'object' ? profile.options as Metadata : {};
        setSummary({ file_format: profile.file_format, row_count: profile.row_count, column_count: profile.column_count, ...options });
        setFields(Array.isArray(profile.fields) ? profile.fields.slice(0, 40).filter((item): item is Metadata => !!item && typeof item === 'object').map(field => ({ name: field.display_name, type: field.logical_type, missing: field.missing_count })) : []);
        setNote('');
      })
      .catch(() => { if (!controller.signal.aborted) setNote('数据集画像没有读到。节点上仍保留已保存的计数。'); });
    return () => controller.abort();
  }, [datasetId, version]);
  return <div><h3>数据集画像参数</h3>{note ? <p className="muted">{note}</p> : <><Facts source={summary} />{fields.length ? <ul>{fields.map((field, index) => <li key={index}>{valueText(field.name)} · {valueText(field.type)} · 缺失 {valueText(field.missing)}</li>)}</ul> : null}</>}</div>;
}

export function NodeKindDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const kind = detailKind(node.name, attrs);
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const calls = trace.llm_calls.filter(call => call.span_id === node.span_id);
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const tabs: { id: string; label: string; alert?: boolean }[] = [
    { id: 'input', label: 'Input' },
    { id: 'output', label: 'Output' },
  ];
  if (kind === 'llm') tabs.push({ id: 'prompt', label: 'Prompt & Model' });
  if (kind === 'tool') tabs.push({ id: 'api', label: 'API Request/Response' });
  if (kind === 'rag') tabs.push({ id: 'chunks', label: 'Knowledge Chunks' });
  if (failed) tabs.push({ id: 'error', label: 'Error Stack', alert: true });
  const [tab, setTab] = useState(tabs[0].id);
  const current = tabs.some(item => item.id === tab) ? tab : tabs[0].id;
  const decision = pick(attrs, decisionKeys);
  const output = pick(attrs, outputKeys);
  const request = { ...inputObject(attrs), ...pick(attrs, ['request', 'parameters', 'arguments', 'tool_input']) };
  const response = { ...output, ...pick(attrs, ['response', 'body', 'result']) };
  const stack = stackText(node, events);
  const chunks = chunksOf(attrs);
  const query = attrs.query_string ?? attrs.query ?? attrs.retrieval_query;
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header className="wf-detail-head">
      <h2>{names[node.name] || node.name}</h2>
      <span className={`wf-kind wf-kind-${kind || 'unknown'}`}>{kind ? detailKinds[kind as DetailKind] : '未归类'}</span>
      <StatusBadge status={node.status} />
      <span>{durationText(node.duration_ms)}</span>
    </header>
    <code className="wf-id">{node.span_id}</code>
    {node.error_code && <p><code>{node.error_code}</code></p>}
    <div className="trace-tabs" role="tablist" aria-label="节点内容">
      {tabs.map(item => <button key={item.id} type="button" role="tab" aria-selected={current === item.id} className={`trace-tab ${current === item.id ? 'trace-tab-active' : ''} ${item.alert ? 'wf-tab-alert' : ''}`} onClick={() => setTab(item.id)}>{item.label}</button>)}
    </div>
    <div role="tabpanel">
      {current === 'input' && <section><h3>Input Data</h3><InputSummary attrs={attrs} /><JsonBlock value={inputObject(attrs)} empty="未采集完整输入 JSON。" /></section>}
      {current === 'output' && <section>
        <h3>Output Data</h3>
        {kind === 'rule' && <><h3>Evaluation Result</h3>{Object.keys(decision).length ? <Facts source={decision} /> : <p className="muted">未采集判断结果。没有 condition_matched 或分支字段。</p>}</>}
        <Facts source={output} />
        {!Object.keys(output).length && !Object.keys(recorded(attrs)).length && <p className="muted">未采集独立输出变量。</p>}
        <LinkedRecords attrs={attrs} trace={trace} />
        <h3>事件</h3>
        {events.length ? <ol className="wf-event-list">{events.map(event => <li key={event.event_id}><time>{timeText(event.recorded_at)}</time><code>{event.event_type}</code>{eventFacts(event)}</li>)}</ol> : <p className="muted">没有已保存的事件。</p>}
      </section>}
      {current === 'prompt' && <PromptTab node={node} calls={calls} />}
      {current === 'api' && <section>
        <h3>Tool Identity</h3>
        <dl className="wf-refs">
          <div><dt>Tool / API Name</dt><dd>{valueText(attrs.tool_name ?? attrs.api_name ?? (names[node.name] || node.name))}</dd></div>
          <div><dt>Endpoint URL</dt><dd>{endpoint(attrs) || 'InsightFlow 进程内执行，没有对外地址。'}</dd></div>
        </dl>
        <h3>Request</h3><JsonBlock value={request} empty="未采集结构化入参。" />
        {node.name === 'data_profiler' && typeof attrs.dataset_id === 'string' && typeof attrs.dataset_version === 'string' && <DatasetProfileView datasetId={attrs.dataset_id} version={attrs.dataset_version} />}
        <h3>Response</h3><JsonBlock value={response} empty="未采集外部返回报文。" />
        <h3>Network Status</h3>
        <dl className="wf-refs"><div><dt>HTTP 状态码</dt><dd>{httpStatus(attrs) || '进程内执行，没有 HTTP 状态。'}</dd></div><div><dt>耗时</dt><dd>{durationText(node.duration_ms)}</dd></div></dl>
      </section>}
      {current === 'chunks' && <section>
        <h3>Retrieval Config</h3>
        <Facts source={pick(attrs, ['retrieval_strategy', 'strategy', 'top_k', 'embedding_model', 'rerank_model'])} />
        {!['retrieval_strategy', 'strategy', 'top_k', 'embedding_model', 'rerank_model'].some(key => attrs[key] != null) && <p className="muted">未采集检索策略或 Embedding 模型。</p>}
        <h3>Query String</h3><p>{typeof query === 'string' && query ? query : '未采集'}</p>
        <h3>Retrieved Chunks</h3>
        {chunks.length ? chunks.map((chunk, index) => <article key={index} className="wf-chunk"><strong>切片 {index + 1}</strong><p>{valueText(chunk.text ?? chunk.content ?? chunk.chunk)}</p><p>来源：{valueText(chunk.source_file_name ?? chunk.source_file ?? chunk.source ?? chunk.document)}</p><p>Score：{valueText(chunk.score ?? chunk.similarity ?? chunk.rerank_score)}</p></article>) : <p className="muted">未采集召回切片。</p>}
      </section>}
      {current === 'error' && <section>
        <h3>Error Stack</h3>
        <dl className="wf-refs"><div><dt>错误代码</dt><dd><code>{node.error_code || '未采集'}</code></dd></div><div><dt>错误说明</dt><dd>{node.error_message || valueText(attrs.error_message)}</dd></div></dl>
        {stack ? <pre className="wf-json" tabIndex={0}>{stack}</pre> : <p className="muted">未采集到后端异常栈原文。错误代码来自已保存的节点记录。</p>}
      </section>}
    </div>
  </aside>;
}
