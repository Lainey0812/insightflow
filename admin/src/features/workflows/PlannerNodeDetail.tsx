import { useEffect, useRef, useState } from 'react';
import type { Metadata, TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { durationText, timeText, traceStatus, valueText } from '../traces/presentation';
import { StatusBadge } from '../traces/TraceShared';
import { Facts, given, jsonText, LlmCallSections, record, useLlmCalls, userPayload } from './LlmCallDetail';
import { JsonDisclosure } from './NodeChrome';

const modes: Record<string, string> = { goal_driven: '目标驱动', exploratory: '探索', undetermined: '尚未确定' };
const coverageLabels: Record<string, string> = { complete: '完整', partial: '部分', blocked: '阻断' };
const priorityLabels: Record<string, string> = { P0: '核心', P1: '重要补充', P2: '补充' };
const feasibilityLabels: Record<string, string> = { F0: '不能直接执行', F1: '需要数据转换', F2: '可以分析' };
const constraintLabels: Record<string, string> = { time_range: '时间范围', filters: '筛选条件', metric_requirements: '指标要求', analysis_limits: '其他限制' };

function rows(value: unknown): Metadata[] {
  return Array.isArray(value) ? value.filter((item): item is Metadata => !!record(item)) : [];
}
function plannerInput(payload: Metadata | null): Metadata | null {
  const parsed = userPayload(payload);
  return parsed && (record(parsed.intent) || record(parsed.profile)) ? parsed : null;
}
function draftOf(text: string): Metadata | null {
  try {
    const parsed = record(JSON.parse(text));
    return Array.isArray(parsed?.tasks) ? parsed : null;
  } catch { return null; }
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
function fieldRefs(steps: Metadata[]): string[] {
  const found: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === 'string' && /^field_\d{4}$/.test(value) && !found.includes(value)) found.push(value);
  };
  const walk = (value: unknown, key = '') => {
    if (key === 'field' || key === 'dimensions') Array.isArray(value) ? value.forEach(add) : add(value);
    if (key === 'conditions') rows(value).forEach(item => add(item.field));
    const row = record(value);
    if (row) Object.entries(row).forEach(([childKey, child]) => walk(child, childKey));
    else if (Array.isArray(value)) value.forEach(item => walk(item, key));
  };
  steps.forEach(step => walk(step.params));
  return found;
}
function ConstraintList({ value }: { value: unknown }) {
  const items = Array.isArray(value) ? value : value == null ? [] : [value];
  if (!items.length) return <p className="muted">没有此类约束。</p>;
  return <ul className="wf-issues">{items.map((item, index) => {
    const row = record(item);
    if (!row) return <li key={index}>{given(item)}</li>;
    return <li key={index}><p>{given(row.raw_text)}</p><p>validation_status {given(row.validation_status)}</p></li>;
  })}</ul>;
}

export function PlannerNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const calls = trace.llm_calls.filter(call => call.span_id === node.span_id).sort((left, right) => left.call_sequence - right.call_sequence);
  const saved = record(node.planner_result);
  const { loaded, settled } = useLlmCalls(calls);
  const [tab, setTab] = useState(failed ? 'input' : 'output');
  const picked = useRef(false);
  const inputs = calls.map(call => plannerInput(loaded[call.call_id]?.request || null)).filter((item): item is Metadata => !!item);
  const input = inputs[0] || null;
  const drafts = calls.map(call => draftOf(loaded[call.call_id]?.responseText || '')).filter((item): item is Metadata => !!item);
  const draft = drafts.at(-1) || null;
  const intent = record(input?.intent) || record(saved?.intent_snapshot);
  const goal = record(intent?.analysis_goal);
  const constraints = record(intent?.constraints);
  const profile = record(input?.profile);
  const fields = rows(profile?.fields);
  const quality = Array.isArray(profile?.quality_issues) ? profile.quality_issues : null;
  const capabilities = record(input?.capabilities);
  const operations = record(capabilities?.operations);
  const requirements = rows(input?.core_requirements);
  const plan = record(saved?.plan);
  const tasks = rows(plan?.tasks || draft?.tasks);
  const checks = rows(saved?.validation_results);
  const unmet = Array.isArray(saved?.unmet_core_requirements) ? saved.unmet_core_requirements : null;
  const hasInput = Boolean(input || intent || attrs.input_dataset_id);
  const hasPlan = Boolean(plan || draft);
  useEffect(() => {
    if (!settled || picked.current || !failed || hasPlan) return;
    setTab(hasInput ? 'input' : 'llm');
  }, [settled, failed, hasPlan, hasInput]);
  function select(id: string) { picked.current = true; setTab(id); }
  const brief = node.error_message || (typeof attrs.error_message === 'string' ? attrs.error_message : '');
  const stack = stackText(node, events);
  const usingDraft = !plan && !!draft;
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header className="wf-detail-head">
      <h2>分析规划</h2>
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
        {!settled && !input && !intent && <p className="muted">正在读取已保存的模型调用…</p>}
        {settled && !input && !intent && <p className="muted">没有已保留的规划输入。</p>}
        {(input || intent) && <>
          <h3>需求理解结果</h3>
          <Facts rows={[['分析模式', modes[String(intent?.analysis_mode)] || intent?.analysis_mode], ['下一步', intent?.next_action], ['分析对象', goal ? goal.analysis_object : undefined], ['业务目标', goal ? goal.business_goal : undefined], ['决策目标', goal ? goal.decision_goal : undefined]]} />
          {!intent && <p className="muted">需求理解结果未采集。</p>}
          <h3>显式约束</h3>
          <h3>尚未解决的澄清</h3>
          {Array.isArray(intent?.uncertainties) ? intent.uncertainties.length ? <ul className="wf-issues">{rows(intent.uncertainties).map((item, index) => <li key={index}>{given(item.issue ?? item.description)}</li>)}</ul> : <p className="muted">没有尚未解决的澄清。</p> : <p className="muted">澄清事项未采集。</p>}
          {constraints ? Object.entries(constraintLabels).map(([key, label]) => <div key={key}><h3>{label}</h3><ConstraintList value={constraints[key]} /></div>) : <p className="muted">约束未采集。</p>}
          <h3>核心需求</h3>
          {input ? requirements.length ? <ul className="wf-issues">{requirements.map(item => <li key={String(item.requirement_id)}><code>{valueText(item.requirement_id)}</code><p>{given(item.description)}</p></li>)}</ul> : <p className="muted">没有核心需求。</p> : <p className="muted">核心需求未保留在请求快照中。</p>}
          <h3>数据集 Schema</h3>
          {profile ? <>
            <Facts rows={[['数据集', profile.dataset_id], ['数据集版本', profile.dataset_version], ['文件', profile.file_name], ['行数', profile.row_count], ['字段数', fields.length]]} />
            {fields.length ? <ul>{fields.map(field => <li key={String(field.field_id)}>{valueText(field.name)} · {valueText(field.logical_type)} · {valueText(field.physical_type)} · 缺失率 {given(field.missing_rate)}</li>)}</ul> : <p className="muted">没有传入字段。</p>}
          </> : <p className="muted">{attrs.input_field_count != null ? `字段画像未保留。节点只记录了字段数 ${String(attrs.input_field_count)}。` : '字段画像未采集。'}</p>}
          <h3>数据质量</h3>
          {quality ? quality.length ? <ul className="wf-issues">{quality.map((item, index) => { const row = record(item); return <li key={index}>{row ? `${valueText(row.code)} · ${valueText(row.field_ids)}` : given(item)}</li>; })}</ul> : <p className="muted">本次传入的质量信号为 0 条。</p> : <p className="muted">质量信号未采集。</p>}
          <h3>规划配置</h3>
          {capabilities ? <>
            <Facts rows={[['能力版本', capabilities.version], ['聚合函数', capabilities.aggregate_functions], ['派生函数', capabilities.derive_functions], ['执行范围', capabilities.execution_scope]]} />
            {operations && Object.keys(operations).length ? <ul>{Object.keys(operations).map(name => <li key={name}>{name}</li>)}</ul> : <p className="muted">没有已登记的操作。</p>}
          </> : <p className="muted">规划配置未保留在请求快照中。</p>}
          {input ? <JsonDisclosure title="结构化 Input JSON" value={input} /> : <p className="muted">请求快照未保留，不按当前数据重建。</p>}
        </>}
      </section>}
      {tab === 'output' && <section>
        {!settled && !hasPlan && <p className="muted">正在读取已保存的模型调用…</p>}
        {settled && !hasPlan && <p className="muted">没有已保留的结构化计划。</p>}
        {hasPlan && <>
          <h3>计划概览</h3>
          <p className="muted">{plan ? '可行性来自本节点返回里的技术校验，不是用户审批，也不代替后续计划校验节点。' : '下面是模型草案。草案没有可行性标记，这里不补校验结论。'}</p>
          <Facts rows={[['分析目标', goal?.business_goal], ['计划编号', plan?.plan_id ?? attrs.plan_id], ['计划版本', plan?.plan_version ?? attrs.plan_version], ['覆盖', coverageLabels[String(saved?.coverage_status ?? attrs.coverage_status)] || saved?.coverage_status || attrs.coverage_status], ['任务数', tasks.length || attrs.task_count], ['核心任务', tasks.length ? tasks.filter(task => task.priority === 'P0').length : undefined], ['补充任务', tasks.length ? tasks.filter(task => task.priority === 'P1' || task.priority === 'P2').length : undefined], ['可执行', saved ? (saved.executable_task_ids as unknown[] | undefined)?.length : attrs.executable_count], ['受阻', saved ? (saved.blocked_task_ids as unknown[] | undefined)?.length : attrs.blocked_count], ['需要用户审批', plan ? '是，本节点没有审批结果' : undefined]]} />
          <h3>分析任务</h3>
          {tasks.map(task => {
            const steps = rows(task.steps);
            const check = checks.find(item => item.task_id === task.task_id);
            const priority = String(task.priority || '');
            return <details key={String(task.task_id)} className="wf-task">
              <summary>{valueText(task.title)} · {priority || '优先级未采集'} {priorityLabels[priority] || ''}{check ? ` · ${String(check.feasibility)} ${feasibilityLabels[String(check.feasibility)] || ''} · ${valueText(check.reason_code)}` : ' · 可行性未采集'}</summary>
              <p>{given(task.business_question)}</p>
              <Facts rows={[['优先级原因', task.priority_reason], ['需求', task.requirement_ids], ['依赖', Array.isArray(task.depends_on) && task.depends_on.length ? task.depends_on : '没有依赖'], ['待确认', Array.isArray(task.missing_inputs) && task.missing_inputs.length ? task.missing_inputs : '没有待确认输入'], ['所需字段', fieldRefs(steps).join('、') || '步骤参数里没有字段引用'], ['分析方法', steps.map(step => String(step.operation || '')).filter(Boolean).join('、') || '未采集']]} />
              {check && rows(check.validation_issues).length ? <ul className="wf-issues">{rows(check.validation_issues).map((item, index) => <li key={index}><code>{valueText(item.code)}</code><p>{given(item.message)}</p><p>{valueText(item.step_id)} · {valueText(item.field)}</p></li>)}</ul> : null}
              {steps.map(step => <pre key={String(step.step_id)} className="wf-json" tabIndex={0}>{valueText(step.operation)} {jsonText(step.params)}</pre>)}
            </details>;
          })}
          <h3>待确认事项</h3>
          {(() => {
            const pending = tasks.flatMap(task => Array.isArray(task.missing_inputs) ? task.missing_inputs.filter((item): item is string => typeof item === 'string') : []);
            const uncertainties = rows(intent?.uncertainties);
            if (!pending.length && !uncertainties.length) return <p className="muted">没有待确认事项。</p>;
            return <ul className="wf-issues">{pending.map((item, index) => <li key={'m' + index}>{item}</li>)}{uncertainties.map((item, index) => <li key={'u' + index}>{given(item.issue ?? item.description)}</li>)}</ul>;
          })()}
          <h3>规划风险</h3>
          {saved ? <>
            <Facts rows={[['未满足核心需求', unmet?.length ?? 0], ['受阻任务', (saved.blocked_task_ids as unknown[] | undefined)?.length ?? 0]]} />
            {unmet?.length ? <ul className="wf-issues">{unmet.map((item, index) => { const row = record(item); return <li key={index}>{row ? `${valueText(row.requirement_id)} · ${given(row.description)} · ${valueText(row.reason_codes)}` : given(item)}</li>; })}</ul> : <p className="muted">没有未满足的核心需求。</p>}
          </> : <p className="muted">规划风险未采集。草案里的缺失输入已经写在对应任务上。</p>}
          <JsonDisclosure title="结构化 Plan JSON" value={usingDraft ? draft : saved} />
        </>}
      </section>}
      {tab === 'llm' && <section><LlmCallSections calls={calls} loaded={loaded} attrs={attrs} /></section>}
    </div>
  </aside>;
}
