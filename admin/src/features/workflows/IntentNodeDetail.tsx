import { useEffect, useRef, useState } from 'react';
import type { Metadata, TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { durationText, timeText, traceStatus, valueText } from '../traces/presentation';
import { StatusBadge } from '../traces/TraceShared';
import { Facts, given, LlmCallSections, parseObject, record, useLlmCalls, userPayload } from './LlmCallDetail';
import { JsonDisclosure } from './NodeChrome';

const modes: Record<string, string> = { goal_driven: '目标驱动', exploratory: '探索', undetermined: '尚未确定' };
const actions: Record<string, string> = { proceed: '继续规划', clarify: '需要澄清' };
const constraintLabels: Record<string, string> = { time_range: '时间范围', filters: '筛选条件', metric_requirements: '指标要求', analysis_limits: '其他限制' };

function instructionOf(payload: Metadata | null): Metadata | null {
  const parsed = userPayload(payload);
  return typeof parsed?.user_query === 'string' ? parsed : null;
}
function outputOf(text: string): Metadata | null {
  const parsed = parseObject(text);
  return record(parsed?.analysis_goal) ? parsed : null;
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

export function IntentNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const calls = trace.llm_calls.filter(call => call.span_id === node.span_id).sort((left, right) => left.call_sequence - right.call_sequence);
  const saved = !failed ? record(node.intent_result) : null;
  const { loaded, settled } = useLlmCalls(calls);
  const [tab, setTab] = useState(failed ? 'input' : 'output');
  const picked = useRef(false);
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
    <p className="muted">{timeText(node.started_at)} – {timeText(node.finished_at)}{node.node_attempt ? ` · 第 ${node.node_attempt} 次` : ''}</p>
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
        {inputJson ? <JsonDisclosure title="结构化 Input JSON" value={inputJson} /> : <p className="muted">没有已保存的结构化输入。</p>}
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
          <JsonDisclosure title="结构化输出 JSON" value={output} />
        </>}
      </section>}
      {tab === 'llm' && <section><LlmCallSections calls={calls} loaded={loaded} attrs={attrs} /></section>}
    </div>
  </aside>;
}
