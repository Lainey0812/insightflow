import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { promptApi } from '../../api/prompts';
import { ApiError } from '../../api/client';
import type { CallSummary } from '../../types/prompts';
import type { Metadata, TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { versionPath } from '../prompts/PromptShared';
import { StatusBadge } from '../traces/TraceShared';
import { durationText, timeText, traceStatus, traceStatusLabels, valueText } from '../traces/presentation';

const modes: Record<string, string> = { goal_driven: '目标驱动', exploratory: '探索', undetermined: '尚未确定' };
const actions: Record<string, string> = { proceed: '继续规划', clarify: '需要澄清' };
const constraintLabels: Record<string, string> = { time_range: '时间范围', filters: '筛选条件', metric_requirements: '指标要求', analysis_limits: '其他限制' };
type Hold = 'loading' | 'retained' | 'expired' | 'unavailable' | 'locked' | 'missing';
interface LoadedCall {
  summary: CallSummary | null; version: string; request: Metadata | null; requestHold: Hold;
  responseText: string; responseHold: Hold; responseCode: string | null;
}

function record(value: unknown): Metadata | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Metadata : null;
}
function given(value: unknown): string {
  return value === null ? '未给出' : valueText(value);
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
function jsonText(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? '';
  return text.length > 20000 ? text.slice(0, 20000) + '\n…' : text;
}
function parseObject(text: string): Metadata | null {
  try {
    return record(JSON.parse(text));
  } catch {
    return null;
  }
}
function instructionOf(payload: Metadata | null): Metadata | null {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const user = [...messages].reverse().find(item => record(item)?.role === 'user');
  const content = record(user)?.content;
  const parsed = typeof content === 'string' ? parseObject(content) : null;
  return typeof parsed?.user_query === 'string' ? parsed : null;
}
function outputOf(text: string): Metadata | null {
  const parsed = parseObject(text);
  return record(parsed?.analysis_goal) ? parsed : null;
}
function metric(source: Metadata, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return '未采集';
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
function requestText(payload: Metadata): string {
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
function Facts({ rows }: { rows: [string, unknown][] }) {
  const visible = rows.filter(([, value]) => value !== undefined);
  if (!visible.length) return null;
  return <dl className="wf-refs">{visible.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{given(value)}</code></dd></div>)}</dl>;
}
function ConstraintList({ value }: { value: unknown }) {
  const items = Array.isArray(value) ? value : value == null ? [] : [value];
  if (!items.length) return <p className="muted">没有此类约束。</p>;
  return <ul className="wf-issues">{items.map((item, index) => {
    const row = record(item);
    if (!row) return <li key={index}>{given(item)}</li>;
    const extra = Object.entries(row).filter(([key]) => key !== 'raw_text' && key !== 'validation_status');
    return <li key={index}><p>{given(row.raw_text)}</p><p>validation_status {given(row.validation_status)}</p>{extra.map(([key, itemValue]) => <p key={key}>{key} {given(itemValue)}</p>)}</li>;
  })}</ul>;
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

export function IntentNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const calls = trace.llm_calls.filter(call => call.span_id === node.span_id).sort((left, right) => left.call_sequence - right.call_sequence);
  const saved = !failed ? record(node.intent_result) : null;
  const [loaded, setLoaded] = useState<Record<string, LoadedCall>>({});
  const [settled, setSettled] = useState(!calls.length);
  const [tab, setTab] = useState(failed ? 'input' : 'output');
  const picked = useRef(false);
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
  const instructions = calls.map(call => instructionOf(loaded[call.call_id]?.request || null)).filter((item): item is Metadata => !!item);
  const instruction = instructions[0] || null;
  const responses = calls.map(call => outputOf(loaded[call.call_id]?.responseText || '')).filter((item): item is Metadata => !!item);
  const parsed = responses.at(-1) || null;
  const output = parsed || saved;
  const usingSavedOutput = !parsed && !!saved;
  const context = record(instruction?.dataset_context);
  const columns = Array.isArray(context?.columns) ? context.columns.filter((item): item is Metadata => !!record(item)) : [];
  const query = typeof instruction?.user_query === 'string' ? instruction.user_query : typeof saved?.user_query === 'string' ? saved.user_query : '';
  const answers = Array.isArray(instruction?.clarification_answers) ? instruction.clarification_answers : Array.isArray(saved?.clarification_answers) ? saved.clarification_answers : null;
  const feedback = instructions.map(item => record(item.validation_feedback)).filter((item): item is Metadata => !!item);
  const datasetRef = record(saved?.dataset_ref);
  const goal = record(output?.analysis_goal);
  const constraints = record(output?.constraints);
  const uncertainties = Array.isArray(output?.uncertainties) ? output.uncertainties.filter((item): item is Metadata => !!record(item)) : null;
  const questions = Array.isArray(output?.clarification_questions) ? output.clarification_questions.filter((item): item is string => typeof item === 'string') : null;
  const hasInput = Boolean(query || answers || context || attrs.input_dataset_id || attrs.input_query_chars != null);
  useEffect(() => {
    if (!settled || picked.current || !failed || output) return;
    setTab(hasInput ? 'input' : 'llm');
  }, [settled, failed, output, hasInput]);
  function select(id: string) { picked.current = true; setTab(id); }
  const brief = node.error_message || (typeof attrs.error_message === 'string' ? attrs.error_message : '');
  const stack = stackText(node, events);
  const inputJson = instruction || (saved ? { user_query: saved.user_query, clarification_answers: saved.clarification_answers, dataset_ref: saved.dataset_ref } : null);
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header className="wf-detail-head">
      <h2>需求理解</h2>
      <StatusBadge status={node.status} />
      <span>{durationText(node.duration_ms)}</span>
    </header>
    <code className="wf-id">{node.span_id}</code>
    {failed && <section className="wf-profiler-error">
      <p><code>{node.error_code || '未采集'}</code></p>
      <p>{brief || '没有已保存的错误说明。'}</p>
      <details><summary>错误详情</summary>{stack ? <pre className="wf-json" tabIndex={0}>{stack}</pre> : <p className="muted">没有更多已保存的错误详情。</p>}</details>
    </section>}
    <div className="trace-tabs" role="tablist" aria-label="节点内容">
      {[['input', 'Input'], ['output', 'Output'], ['llm', 'LLM']].map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={`trace-tab ${tab === id ? 'trace-tab-active' : ''}`} onClick={() => select(id)}>{label}</button>)}
    </div>
    <div role="tabpanel">
      {tab === 'input' && <section>
        <h3>用户原始需求</h3>
        {query ? <p className="wf-intent-query">{query}</p> : <p className="muted">{attrs.input_query_chars != null ? `需求原文未保留。节点只记录了字数 ${String(attrs.input_query_chars)}。` : '需求原文未采集。'}</p>}
        <h3>补充说明</h3>
        {answers ? answers.length ? <ol>{answers.map((item, index) => <li key={index}>{typeof item === 'string' ? item : given(item)}</li>)}</ol> : <p className="muted">没有补充说明。</p> : <p className="muted">补充说明未采集。</p>}
        {feedback.length ? <><h3>重试时附加的校验反馈</h3>{feedback.map((item, index) => <Facts key={index} rows={Object.entries(item)} />)}</> : null}
        <h3>数据集标识</h3>
        <Facts rows={[['数据集', attrs.input_dataset_id ?? datasetRef?.dataset_id], ['数据集版本', attrs.input_dataset_version ?? datasetRef?.dataset_version]]} />
        {!attrs.input_dataset_id && !datasetRef?.dataset_id && <p className="muted">未采集数据集标识。</p>}
        <h3>数据画像摘要</h3>
        {context ? <>
          <Facts rows={[['数据集名称', context.dataset_name], ['行数', context.row_count], ['字段数', columns.length], ['样例行', Array.isArray(context.sample_rows) ? context.sample_rows.length : undefined]]} />
          <p className="muted">未传入质量信号。</p>
          {columns.length ? <ul>{columns.map((column, index) => <li key={index}>{valueText(column.name)} · {valueText(column.logical_type)} · {valueText(column.physical_type)}</li>)}</ul> : <p className="muted">没有传入字段。</p>}
        </> : <p className="muted">数据画像摘要未保留在请求快照中，不按当前画像重建。</p>}
        <details><summary>结构化 Input JSON</summary>{inputJson ? <pre className="wf-json" tabIndex={0}>{jsonText(inputJson)}</pre> : <p className="muted">没有已保存的结构化输入。</p>}</details>
      </section>}
      {tab === 'output' && <section>
        {!settled && !output && <p className="muted">正在读取已保存的模型调用…</p>}
        {settled && !output && <p className="muted">没有已保留的结构化输出。</p>}
        {settled && usingSavedOutput && <p className="muted">原始响应未保留或不是意图结构。以下是节点已保存的结构化结果。</p>}
        {output && <>
          <h3>分析目标</h3>
          <Facts rows={[['分析模式', modes[String(output.analysis_mode)] || output.analysis_mode], ['下一步', actions[String(output.next_action)] || output.next_action], ['分析对象', goal ? goal.analysis_object : undefined], ['业务目标', goal ? goal.business_goal : undefined], ['决策目标', goal ? goal.decision_goal : undefined]]} />
          {!goal && <p className="muted">分析目标未采集。</p>}
          <h3>约束条件</h3>
          <p className="muted">现有约束只有原文和 validation_status，没有操作符、取值或来源标记。</p>
          {constraints ? Object.entries(constraintLabels).map(([key, label]) => <div key={key}><h3>{label}</h3><ConstraintList value={constraints[key]} /></div>) : <p className="muted">约束未采集。</p>}
          <h3>澄清信息</h3>
          <Facts rows={[['是否需要澄清', output.next_action === 'clarify' ? '是' : output.next_action === 'proceed' ? '否' : output.next_action]]} />
          {uncertainties ? uncertainties.length ? <ul className="wf-issues">{uncertainties.map((item, index) => <li key={index}><code>{valueText(item.id)}</code><p>{given(item.issue ?? item.description)}</p><p>{given(item.reason ?? item.impact)}</p><p>{valueText(item.action)} · {valueText(item.resolve_at)}</p></li>)}</ul> : <p className="muted">没有不确定性记录。</p> : <p className="muted">不确定性未采集。</p>}
          {questions ? questions.length ? <ol>{questions.map(item => <li key={item}>{item}</li>)}</ol> : <p className="muted">没有澄清问题。</p> : <p className="muted">澄清问题未采集。</p>}
          <details><summary>结构化输出 JSON</summary><pre className="wf-json" tabIndex={0}>{jsonText(output)}</pre></details>
        </>}
      </section>}
      {tab === 'llm' && <section>
        {!calls.length && <p className="muted">这条节点没有已采集的模型调用。不从其他节点补。</p>}
        {calls.map(call => {
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
              <div><dt>Endpoint URL</dt><dd>{endpointOf({ ...attrs, ...observed }) || (item ? '未采集' : '未采集')}</dd></div>
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
        })}
      </section>}
    </div>
  </aside>;
}
