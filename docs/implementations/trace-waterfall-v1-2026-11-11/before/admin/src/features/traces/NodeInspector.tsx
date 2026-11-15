import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PromptRunLinks } from '../prompts/PromptShared';
import { traceApi } from '../../api/traces';
import type { RunManifest, TraceEvent, TraceSpan } from '../../types/traces';
import { TraceError } from './AccessPanel';
import { KeyValues, StatusBadge } from './TraceShared';
import { durationText, metadata, nodeLabels, ruleLabels, timeText, valueText } from './presentation';

const attributeFields = { evidence_count: '生成证据数', selected_evidence_count: '传入模型的证据数', input_bytes: '请求字节数', output_bytes: '返回字节数', candidate_count: '候选数', accepted_count: '合法候选数', rejected_count: '拒绝候选数', evidence_refs: '证据引用', provider: 'Provider 返回标识', model: 'Provider 模型标识', is_mock: 'Mock 标记', purpose: '调用目的', skip_reason: '跳过原因', report_status: '报告内容状态', goal_coverage: '目标覆盖', insight_count: '保存洞察数', chart_count: '图表数' };
const eventFields = { candidate_index: '候选序号（从 0 开始）', candidate_status: '校验结果', primary_evidence_id: '主证据', evidence_refs: '证据引用', error_code: '错误代码', role: '触发字段', rule: '规则', rule_ids: '规则 ID', candidate_count: '候选数', accepted_count: '合法数', rejected_count: '拒绝数', input_bytes: '输入字节', output_bytes: '输出字节', provider: 'Provider', model: '模型', is_mock: 'Mock 标记', observation_gap: '追踪缺口', dropped_events: '未写入次数' };
const eventNames: Record<string, string> = { 'span.started': '阶段开始', 'span.finished': '阶段结束', 'span.skipped': '跳过阶段', 'llm.started': '模型调用开始', 'llm.returned': '模型已返回', 'candidate.validated': '候选校验', 'candidates.summarized': '候选汇总' };
export function NodeInspector({ span, manifest }: { span: TraceSpan; manifest?: RunManifest }) {
  const [events, setEvents] = useState<TraceEvent[]>([]), [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<'input' | 'output' | 'metrics' | 'error'>('input');
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0), [offset, setOffset] = useState(0), [more, setMore] = useState(false);
  const reload = () => { setOffset(0); setRefresh(value => value + 1); };
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null);
    if (!offset) setEvents([]);
    traceApi.events(span.span_id, offset, controller.signal).then(page => {
      if (controller.signal.aborted) return;
      setEvents(previous => offset ? [...previous, ...page.items.filter(e => !previous.some(old => old.event_id === e.event_id))] : page.items);
      setMore(page.items.length === 100);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [span.span_id, offset, refresh]);
  const eventAttributes = Object.assign({}, ...events.filter(event => ['llm.returned', 'candidates.summarized', 'span.finished'].includes(event.event_type)).map(event => metadata(event.payload)));
  const attributes = { ...eventAttributes, ...metadata(span.attributes) }, versions = metadata(manifest?.versions);
  const groups: Record<string, string[]> = {
    evidence_builder: ['evidence_count'],
    insight_generator: ['selected_evidence_count', 'input_bytes', 'output_bytes', 'candidate_count', 'evidence_refs'],
    fact_validator: ['candidate_count', 'accepted_count', 'rejected_count'],
    report_assembler: ['report_status', 'goal_coverage', 'insight_count', 'chart_count'],
    report_persistence: [],
  };
  const relevantFields = Object.fromEntries((groups[span.name] || Object.keys(attributeFields).filter(key => attributes[key] !== undefined)).map(key => [key, attributeFields[key as keyof typeof attributeFields]]));
  const candidates = events.filter(event => ['accepted', 'rejected'].includes(String(metadata(event.payload).candidate_status)));
  const eventErrors = [...new Set(events.map(event => metadata(event.payload).error_code).filter((code): code is string => typeof code === 'string' && code.length > 0))];
  return <aside className="node-inspector trace-card" aria-label="节点 Inspector">
    <div className="inspector-heading"><div><span className="eyebrow">NODE INSPECTOR</span><h2>{nodeLabels[span.name] || span.name}</h2></div><StatusBadge status={span.status} /></div>
    <code className="wrap-code">{span.span_id}</code>
    <div className="trace-tabs" role="tablist" aria-label="节点内容">
      {([['input', 'Input / Prompt'], ['output', 'Raw Output'], ['metrics', 'Metrics & Token'], ['error', 'Error Stack']] as const).map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'trace-tab trace-tab-active' : 'trace-tab'} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    <div role="tabpanel" hidden={tab !== 'input'}>
    <h3>Input / Prompt</h3>{Object.keys(relevantFields).length ? <KeyValues source={attributes} fields={relevantFields} /> : <p className="muted">此节点未采集独立输入输出摘要。</p>}
    <div className="unavailable-note">Trace 中完整原始输入、输出、候选文本：未保留。已捕获的模型请求可从关联调用申请额外授权；历史缺失内容 unavailable，不补造原文。</div>
    {span.name === 'insight_generator' && <><PromptRunLinks refs={typeof attributes.template_snapshot_id === 'string' ? { insight_generator: attributes.template_snapshot_id } : manifest?.prompt_template_snapshots} />
      {typeof attributes.call_id === 'string' && <p><Link className="trace-link" to={'/prompts/calls/' + encodeURIComponent(attributes.call_id)}>查看本次模型调用</Link></p>}
      <p className="muted">Manifest 的模板引用不代表节点一定调用了模型；跳过状态以 Span 为准。</p></>}
    </div>
    <div role="tabpanel" hidden={tab !== 'output'}>
    <h3>Raw Output</h3>{span.name === 'insight_generator' ? <KeyValues source={{ ...metadata(manifest?.model_config_snapshot), ...attributes, prompt_version: versions.prompt_version, schema_version: versions.schema_version }} fields={{ provider: 'Provider', model: '模型', prompt_version: 'Prompt 版本', schema_version: '输出 Schema', timeout_seconds: '超时（秒）', enable_thinking: '思考配置', usage: 'Token 用量' }} /> : <p className="muted">此视图未展示该节点的独立模型调用，不能据此认定没有调用。已保存版本可查看下方 Manifest 与 Prompt 管理。</p>}
    <h3>候选与拒绝诊断</h3><p className="muted">规则说明解释命中类别，不代表已经人工确认该候选有错。合法/拒绝总数来自后端汇总，不根据当前事件页推算。</p>
    {candidates.length ? <div className="candidate-list">{candidates.map(event => {
      const payload = metadata(event.payload), rules = Array.isArray(payload.rule_ids) ? payload.rule_ids.filter(rule => typeof rule === 'string') as string[] : [];
      return <article key={event.event_id} className={payload.candidate_status === 'rejected' ? 'candidate rejected' : 'candidate'}><strong>候选序号 {valueText(payload.candidate_index)} · {payload.candidate_status === 'rejected' ? '被拒绝' : '已接受'}</strong><KeyValues source={payload} fields={{ primary_evidence_id: '主证据', evidence_refs: '引用证据', role: '触发字段', error_code: '错误代码' }} />{rules.map(rule => <p key={rule}><code>{rule}</code> · {ruleLabels[rule] || '该规则的解释未配置；请按原始规则 ID 核查。'}</p>)}</article>;
    })}</div> : <p className="muted">当前已加载事件中没有候选逐条诊断。其他节点的诊断不会混入；如有更多事件可继续加载。</p>}
    <div className="section-heading"><h3>Event 时间线</h3><button className="secondary-button" disabled={loading} onClick={reload}>刷新事件</button></div>
    <p className="muted">已加载 {events.length} 条事件 · 按后端 sequence 排序</p>
    <ol className="event-timeline">{events.map(event => <li key={event.event_id}><div><strong>#{event.sequence} {eventNames[event.event_type] || event.event_type}</strong><time>{timeText(event.recorded_at)}</time></div><details><summary>事件元信息 · {event.event_type}</summary><KeyValues source={metadata(event.payload)} fields={eventFields} /></details></li>)}</ol>
    {loading && <p role="status">正在读取节点事件…</p>}
    {Boolean(error) && <TraceError error={error} retry={reload} />}
    {!loading && !error && !events.length && <p>此节点没有已保存的事件。</p>}
    {more && !error && <button className="secondary-button" disabled={loading} onClick={() => setOffset(offset + 100)}>加载更多事件</button>}
    </div>
    <div role="tabpanel" hidden={tab !== 'metrics'}>
    <h3>Metrics & Token</h3>
    <KeyValues source={{ start: timeText(span.started_at), finish: timeText(span.finished_at), duration: durationText(span.duration_ms), model: attributes.model ?? metadata(manifest?.model_config_snapshot).model, temperature: metadata(manifest?.model_config_snapshot).temperature, tokens: '未采集' }} fields={{ start: '开始', finish: '结束', duration: '耗时', model: '模型', temperature: 'temperature', tokens: 'Input / Output Token' }} />
    </div>
    <div role="tabpanel" hidden={tab !== 'error'}>
    <h3>Error Stack</h3>
    {span.error_code ? <div className="trace-danger"><strong>{span.error_code}</strong><p>未采集到后端异常栈原文。错误代码来自已保存的节点记录。</p></div> : eventErrors.length ? <div className="trace-danger">{eventErrors.map(code => <strong key={code}>{code}</strong>)}<p>未采集到后端异常栈原文。错误代码来自已保存的节点事件。</p></div> : loading ? <p role="status">正在读取节点事件…</p> : <p className="muted">这个节点没有错误代码。</p>}
    </div>
    <p className="muted">关联 RunManifest：使用本页下方的“本次运行的版本与关联”，不生成另一份版本记录。</p>
  </aside>;
}
