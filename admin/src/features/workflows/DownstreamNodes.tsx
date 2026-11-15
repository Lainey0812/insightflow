import { useState } from 'react';
import type { Metadata, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { durationText, traceStatus, valueText } from '../traces/presentation';
import { Facts, given, record, userPayload, type LoadedCall } from './LlmCallDetail';
import { JsonDisclosure, NodeChrome } from './NodeChrome';

const titles: Record<string, string> = { plan_validator: '计划校验', hitl: '人工审核', analysis_engine: '分析执行', evidence_builder: '证据构建', chart_builder: '图表构建', insight_generator: '洞察生成', fact_validator: '事实校验', report_assembler: '报告组装', report_persistence: '报告保存' };
const sources: Record<string, string> = { planner_output: '规划返回时的技术校验。不是用户批准，也不是保存计划时的再次校验。', initial_plan_save: '保存计划时的再次校验。校验完成不等于用户已批准。', hitl_approve: '批准前的再次校验。计划正文来自该次审批记录上的计划版本。', hitl_revise: '修改计划时的再次校验。计划正文来自该次修改记录上的计划版本。' };
const constraintLabels: Record<string, string> = { time_range: '时间范围', filters: '筛选条件', metric_requirements: '指标要求', analysis_limits: '其他限制' };
const executionStatus: Record<string, string> = { success: '成功', partial_success: '部分成功', failed: '失败', skipped: '跳过' };
const reportStatus: Record<string, string> = { complete: '完整', partial: '部分', unavailable: '不可用', blocked: '阻断' };

function rows(value: unknown): Metadata[] {
  return Array.isArray(value) ? value.filter((item): item is Metadata => !!record(item)) : [];
}
function same(left: unknown, right: unknown): string {
  if (left == null || right == null || left === '' || right === '') return '未采集';
  return String(left) === String(right) ? '一致' : '不一致';
}
function flat(value: unknown): string {
  if (Array.isArray(value)) return value.map(item => flat(item)).join('、') || '未采集';
  const row = record(value);
  if (!row) return given(value);
  return Object.entries(row).map(([key, item]) => `${key} ${given(item)}`).join('；') || '未采集';
}
function VersionLine({ line }: { line: Metadata | null }) {
  if (!line) return <p className="muted">版本对照未采集。</p>;
  return <Facts rows={[['校验的计划', line.validated_plan_id], ['校验的版本', line.validated_plan_version], ['用户批准的版本', line.approved_plan_version], ['执行的版本', line.executed_ambiguous ? '不止一个执行版本' : line.executed_plan_version], ['批准与校验', same(line.validated_plan_version, line.approved_plan_version)], ['执行与批准', same(line.approved_plan_version, line.executed_plan_version)]]} />;
}
function RuleFacts({ rule }: { rule: Metadata | null }) {
  if (!rule) return <p className="muted">批准计划里没有这个任务的计算规则。</p>;
  const filters = rows(rule.filters);
  const metrics = rows(rule.metrics);
  const fields = Array.isArray(rule.fields) ? rule.fields.filter((item): item is string => typeof item === 'string') : [];
  const dimensions = Array.isArray(rule.dimensions) ? rule.dimensions.filter((item): item is string => typeof item === 'string') : [];
  return <Facts rows={[['字段', fields.length ? fields.join('、') : '没有字段引用'], ['过滤', filters.length ? filters.map(item => `${valueText(item.field)} ${valueText(item.operator)} ${flat(item.value)}`).join('；') : '没有过滤条件'], ['分组', dimensions.length ? dimensions.join('、') : '没有分组'], ['聚合', metrics.length ? metrics.map(item => `${valueText(item.function)}(${item.field == null ? '行' : valueText(item.field)})`).join('；') : '没有聚合']]} />;
}
function PlanTasks({ plan }: { plan: Metadata | null }) {
  const tasks = rows(plan?.tasks);
  if (!plan) return <p className="muted">这次没有绑定到已保存的计划正文。</p>;
  if (!tasks.length) return <p className="muted">这份计划没有任务。</p>;
  return <>{tasks.map(task => <details key={String(task.task_id)} className="wf-task"><summary>{valueText(task.task_id)} · {valueText(task.title)} · {valueText(task.priority)}</summary><p>{given(task.business_question)}</p><RuleFacts rule={record(task.rule)} /></details>)}</>;
}
function ResultPreview({ task }: { task: Metadata }) {
  const preview = rows(task.result_preview);
  const columns = rows(task.result_columns);
  if (!preview.length) return <p className="muted">没有已保存的结果行。</p>;
  const keys = columns.length ? columns.map(column => String(column.field || '')) : Object.keys(preview[0]);
  return <>
    <p className="muted">下面是当时保存的计算结果，不是重新计算。{task.preview_limited ? '只显示前 20 行。' : ''}</p>
    <div className="wf-field-scroll"><table className="wf-fields"><thead><tr>{keys.map(key => <th key={key}>{columns.find(column => column.field === key)?.label as string || key}</th>)}</tr></thead><tbody>
      {preview.map((row, index) => <tr key={index}>{keys.map(key => <td key={key}>{given(row[key])}</td>)}</tr>)}
    </tbody></table></div>
  </>;
}
function insightPayload(request: Metadata | null): Metadata | null {
  const parsed = userPayload(request);
  if (parsed && (parsed.analysis_goal || parsed.evidence || parsed.constraints)) return parsed;
  if (request && (request.analysis_goal || request.evidence || request.constraints)) return request;
  return null;
}

export function ValidatorNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const view = record(node.validator_view);
  const plan = record(view?.plan);
  const tasks = rows(plan?.tasks);
  const results = rows(view?.validation_results);
  const [taskFilter, setTaskFilter] = useState('');
  const [codeFilter, setCodeFilter] = useState('');
  const listed = results.flatMap(result => {
    const items = rows(result.validation_issues);
    const base = { task_id: result.task_id, feasibility: result.feasibility, executable: result.executable, reason_code: result.reason_code };
    return items.length ? items.map(item => ({ ...base, ...item })) : [base];
  }) as Metadata[];
  const issues = listed.filter(item => (!taskFilter || String(item.task_id) === taskFilter) && (!codeFilter || String(item.code || item.reason_code) === codeFilter));
  const codes = [...new Set(results.flatMap(result => [result.reason_code, ...rows(result.validation_issues).map(item => item.code)]).filter((item): item is string => typeof item === 'string'))];
  const operations = [...new Set(tasks.flatMap(task => rows(task.steps).map(step => String(step.operation || ''))).filter(Boolean))];
  const blocked = results.filter(result => result.executable === false).length;
  const input = <section>
    <h3>待校验计划</h3>
    <p className="muted">{sources[String(view?.source || attrs.validation_role)] || '这次校验没有单独绑定计划版本。下面只显示 span 上已有的计数。'}</p>
    <Facts rows={[['计划', view?.plan_id ?? attrs.plan_id], ['计划版本', view?.plan_version ?? attrs.plan_version], ['数据集', view?.dataset_id], ['数据集版本', view?.dataset_version], ['校验版本', view?.validation_version ?? attrs.validation_version], ['能力登记版本', view?.registry_version]]} />
    {!view && <p className="muted">完整计划未采集。</p>}
    <h3>版本对照</h3>
    <VersionLine line={record(view?.version_line)} />
    <h3>计划正文</h3>
    <PlanTasks plan={record(view?.plan_brief) || plan} />
    <h3>计划中的操作</h3>
    {operations.length ? <ul>{operations.map(name => <li key={name}>{name}</li>)}</ul> : <p className="muted">允许的操作表未随这次校验记录保存。</p>}
    <p className="muted">数据集字段画像未随校验 span 保存，不读取当前画像代替。</p>
    <JsonDisclosure title="被校验计划 JSON" value={plan || null} />
  </section>;
  const output = <section>
    <h3>校验结果</h3>
    <Facts rows={[['覆盖', view?.coverage_status ?? attrs.coverage_status], ['任务结果', results.length || '未采集'], ['可执行', view ? (view.executable_task_ids as unknown[] | undefined)?.length : attrs.executable_count], ['阻断', view ? (view.blocked_task_ids as unknown[] | undefined)?.length : attrs.blocked_count], ['失败项', view ? blocked : undefined], ['F0', attrs.f0_count], ['F1', attrs.f1_count], ['F2', attrs.f2_count]]} />
    <p className="muted">现有问题只有规则代码、说明、步骤和字段。没有严重程度、期望值、实际值或修复建议。</p>
    <div className="wf-filters">
      <label>任务 ID<select value={taskFilter} onChange={event => setTaskFilter(event.target.value)}><option value="">全部</option>{[...new Set(results.map(item => String(item.task_id || '')))].filter(Boolean).map(id => <option key={id} value={id}>{id}</option>)}</select></label>
      <label>规则代码<select value={codeFilter} onChange={event => setCodeFilter(event.target.value)}><option value="">全部</option>{codes.map(code => <option key={code} value={code}>{code}</option>)}</select></label>
    </div>
    {view ? issues.length ? <ul className="wf-issues">{issues.map((item, index) => <li key={index}><code>{valueText(item.code || item.reason_code)}</code> · {valueText(item.task_id)} · {item.executable === false ? '阻断' : '未阻断'}<p>{given(item.message)}</p><p>{valueText(item.step_id)} · {valueText(item.field)} · {valueText(item.feasibility)}</p></li>)}</ul> : <p className="muted">没有符合筛选条件的校验问题。</p> : <p className="muted">校验问题明细未采集。</p>}
    <h3>校验后的计划</h3>
    {view ? <p className="muted">校验器没有返回修正后的计划。上面的计划就是被检查的那一版。</p> : <p className="muted">这次没有绑定已保存的计划，不显示修正结果。</p>}
    <JsonDisclosure title="校验结果 JSON" value={view || attrs} />
  </section>;
  return <NodeChrome node={node} trace={trace} title={titles.plan_validator} input={input} output={output} />;
}

export function HitlNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const view = record(node.approval_view);
  const decision = record(view?.decision);
  const history = rows(view?.history);
  const executed = rows(view?.executed);
  const input = <section>
    <h3>提交审批的计划</h3>
    <Facts rows={[['命令', view?.command], ['计划', view?.span_plan_id], ['计划版本', view?.span_plan_version], ['当前审阅状态', view?.review_status]]} />
    {!view && <p className="muted">审批上下文未采集。</p>}
    <h3>版本对照</h3>
    <VersionLine line={record(view?.version_line)} />
    <h3>提交审批的计划正文</h3>
    <PlanTasks plan={record(view?.submitted_plan)} />
    <h3>计划版本记录</h3>
    {history.length ? <ol>{history.map(item => <li key={String(item.plan_version)}><code>{valueText(item.plan_id)}</code> · v{valueText(item.plan_version)} · {valueText(item.change_type)} · {valueText(item.created_at)}<p>{given(item.change_summary)}</p></li>)}</ol> : <p className="muted">没有已保存的计划版本。</p>}
    <p className="muted">版本记录不是完整的点击时间线。没有单独保存的拒绝或重新提交事件不会被补写。</p>
    <JsonDisclosure title="审批输入 JSON" value={view || node.attributes || null} />
  </section>;
  const output = <section>
    <h3>审批状态</h3>
    {decision ? <Facts rows={[['决策', decision.status === 'approved' ? '已批准' : decision.status], ['批准时间', decision.approved_at], ['批准的计划', decision.plan_id], ['批准的版本', decision.plan_version], ['审批编号', decision.approval_id], ['快照哈希', decision.snapshot_hash], ['计划版本归属', decision.plan_version_id], ['约束已确认', decision.constraints_confirmed]]} /> : <p className="muted">{view?.matched_approval === false ? '这次节点记录没有对应的批准快照。' : '批准结果未采集。'}</p>}
    <h3>批准的计划正文</h3>
    <PlanTasks plan={record(view?.approved_plan)} />
    <h3>后续执行引用</h3>
    {executed.length ? executed.map(item => <div key={String(item.execution_id)}><Facts rows={[['执行', item.execution_id], ['执行计划', item.plan_id], ['执行版本', item.plan_version], ['执行记录中的批准版本', item.approved_plan_version], ['执行状态', executionStatus[String(item.execution_status)] || item.execution_status], ['与批准版本', same(decision?.plan_version, item.approved_plan_version)], ['与批准计划', same(decision?.plan_id, item.plan_id)]]} /></div>) : <p className="muted">没有找到使用这次批准的执行记录。</p>}
    <p className="muted">这里只读。不能代替用户批准、拒绝或修改计划。</p>
    <JsonDisclosure title="审批结果 JSON" value={view || null} />
  </section>;
  return <NodeChrome node={node} trace={trace} title={titles.hitl} input={input} output={output} />;
}

export function EngineNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const view = record(node.execution_view);
  const tasks = rows(view?.tasks);
  const succeeded = tasks.filter(task => task.status === 'success').length;
  const failed = tasks.filter(task => task.status === 'failed').length;
  const input = <section>
    <h3>执行规格</h3>
    <Facts rows={[['数据集', view?.dataset_id], ['数据集版本', view?.dataset_version], ['计划', view?.plan_id], ['计划版本', view?.plan_version], ['批准版本', view?.approved_plan_version], ['版本对照', same(view?.plan_version, view?.approved_plan_version)], ['审批', view?.approval_id ?? attrs.approval_id], ['执行', view?.execution_id ?? attrs.execution_id], ['来源', view?.source]]} />
    {!view && <p className="muted">执行规格明细未采集。span 只有执行引用。</p>}
    {tasks.map(task => <details key={String(task.task_id)} className="wf-task"><summary>{valueText(task.task_id)} · {executionStatus[String(task.status)] || valueText(task.status)}</summary>
      <RuleFacts rule={record(task.rule)} />
      <Facts rows={[['计算说明', task.calculation], ['范围', task.scope], ['样本定义', task.sample_definition]]} />
      {rows(task.steps).length ? <ul>{rows(task.steps).map(step => <li key={String(step.step_id)}>{valueText(step.operation)} · 输入 {valueText(step.input_row_count)} · 输出 {valueText(step.output_row_count)}</li>)}</ul> : <p className="muted">没有已保存的步骤日志。</p>}
      {record(task.sample_statistics) && <p>聚合输入 {valueText(record(task.sample_statistics)?.input_row_count)} 行。</p>}
    </details>)}
    <JsonDisclosure title="执行输入 JSON" value={view || attrs} />
  </section>;
  const output = <section>
    <h3>执行概览</h3>
    {attrs.execution_status === 'error' || (node.status === 'error' && view?.execution_status === 'partial_success') ? <p className="muted">观测状态按失败记录，因为执行结果不是全部成功。各任务状态以已保存结果为准。</p> : null}
    <Facts rows={[['执行状态', executionStatus[String(view?.execution_status || attrs.execution_status)] || view?.execution_status || attrs.execution_status], ['执行', view?.execution_id ?? attrs.execution_id], ['任务数', view ? tasks.length : '未采集'], ['成功', view ? succeeded : undefined], ['失败', view ? failed : undefined], ['耗时', view?.duration_ms == null ? undefined : durationText(Number(view.duration_ms))]]} />
    {tasks.map(task => <details key={String(task.task_id)} className="wf-task"><summary>{valueText(task.task_id)} · {executionStatus[String(task.status)] || valueText(task.status)} · {durationText(typeof task.duration_ms === 'number' ? task.duration_ms : null)}</summary>
      <Facts rows={[['输入行', task.input_row_count], ['有效行', task.effective_row_count], ['有效样本', task.valid_sample_count], ['输出行', task.output_row_count], ['结果引用', task.result_id || task.result_ref], ['截断', task.truncated], ['失败说明', task.failure_reason]]} />
      <ResultPreview task={task} />
      {record(task.error) && <p><code>{valueText(record(task.error)?.code)}</code> {given(record(task.error)?.message)}</p>}
    </details>)}
    {view?.rows_omitted === true && <p className="muted">明细行未放入此视图，避免把结果表当成可重新计算的依据。</p>}
    {!view && <p className="muted">任务结果未采集。</p>}
    <JsonDisclosure title="执行结果 JSON" value={view || attrs} />
  </section>;
  return <NodeChrome node={node} trace={trace} title={titles.analysis_engine} input={input} output={output} />;
}

export function ReportNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const view = record(node.report_view);
  const summary = record(view?.summary);
  const insights = rows(view?.insights);
  const evidence = rows(view?.evidence);
  const charts = rows(view?.charts);
  const name = node.name;
  const batch = typeof attrs.batch_count === 'number' && attrs.batch_count > 1;
  const insightInput = ({ loaded, settled }: { loaded: Record<string, LoadedCall>; settled: boolean }) => {
    const calls = trace.llm_calls.filter(call => call.span_id === node.span_id).sort((left, right) => left.call_sequence - right.call_sequence);
    const packets = calls.map(call => ({ call, payload: insightPayload(loaded[call.call_id]?.request || null), hold: loaded[call.call_id]?.requestHold || (settled ? 'missing' : 'loading') }));
    return <section>
      <h3>本批引用</h3>
      <Facts rows={[['批次', attrs.batch_index], ['批次数', attrs.batch_count], ['证据条数', attrs.selected_evidence_count], ['证据引用', attrs.evidence_refs], ['用途', attrs.purpose]]} />
      <p className="muted">下面的目标、约束和证据值只来自这次已保存的模型请求。请求里没有的数字不能当成模型输入。</p>
      {!calls.length && <p className="muted">这次节点没有已采集的模型调用，不能展示请求正文。</p>}
      {calls.length > 0 && !settled && <p className="muted">正在读取已保存的模型请求…</p>}
      {packets.map(({ call, payload, hold }) => {
        const goal = record(payload?.analysis_goal);
        const constraints = record(payload?.constraints);
        const evidence = rows(payload?.evidence).map(item => { const next = { ...item }; delete next.source_row_indices; return next; });
        const samples = rows(payload?.task_sample_context);
        return <div key={call.call_id}>
          <h3>请求 {call.call_id}</h3>
          {payload ? <>
            <Facts rows={[['分析对象', goal?.analysis_object], ['业务目标', goal?.business_goal], ['决策目标', goal?.decision_goal]]} />
            <h3>用户约束</h3>
            {constraints ? Object.entries(constraintLabels).map(([key, label]) => {
              const items = Array.isArray(constraints[key]) ? constraints[key] : constraints[key] == null ? [] : [constraints[key]];
              return <div key={key}><h3>{label}</h3>{items.length ? <ul className="wf-issues">{items.map((item, index) => { const row = record(item); return <li key={index}>{row ? given(row.raw_text) : given(item)}</li>; })}</ul> : <p className="muted">没有此类约束。</p>}</div>;
            }) : <p className="muted">约束未出现在这次请求里。</p>}
            <h3>计算结果与证据</h3>
            {samples.length ? <ul>{samples.map(item => <li key={String(item.task_id)}>{valueText(item.task_id)} · {valueText(item.status)} · 有效样本 {given(item.valid_sample_count)}</li>)}</ul> : <p className="muted">请求里没有样本量。</p>}
            {evidence.length ? evidence.map(item => <details key={String(item.evidence_id)} className="wf-task"><summary>{valueText(item.evidence_id)} · {valueText(item.task_id)} · {valueText(item.evidence_type)} · {flat(item.value)}</summary><p>{given(item.statement)}</p><Facts rows={[['计算', item.calculation], ['结果字段', item.result_field], ['结果值', flat(item.value)], ['结果引用', item.data_ref]]} /></details>) : <p className="muted">请求里没有证据。</p>}
          </> : <p className="muted">{hold === 'expired' || hold === 'unavailable' ? '完整请求未保留或已过期，不重建。' : settled ? '已保存请求未能读出分析输入。' : '正在读取已保存的模型请求…'}</p>}
        </div>;
      })}
      <JsonDisclosure title="节点输入 JSON" value={{ batch_index: attrs.batch_index, batch_count: attrs.batch_count, evidence_refs: attrs.evidence_refs, selected_evidence_count: attrs.selected_evidence_count }} />
    </section>;
  };
  const input = name === 'insight_generator' ? insightInput : <section>
    {name === 'evidence_builder' && <Facts rows={[['证据条数', attrs.evidence_count ?? evidence.length]]} />}
    {name === 'chart_builder' && <Facts rows={[['图表数', attrs.chart_count ?? charts.length]]} />}
    {name === 'fact_validator' && <Facts rows={[['批次', attrs.batch_index], ['候选', attrs.candidate_count], ['接受', attrs.accepted_count], ['拒绝', attrs.rejected_count]]} />}
    {(name === 'report_assembler' || name === 'report_persistence') && <Facts rows={[['报告', view?.report_id ?? attrs.report_id], ['执行', view?.execution_id], ['计划版本', view?.plan_version], ['数据集', view?.dataset_id], ['数据集版本', view?.dataset_version]]} />}
    {!view && name !== 'fact_validator' && <p className="muted">已保存报告未挂到这次节点。不从当前报告重建。</p>}
    <JsonDisclosure title="节点输入 JSON" value={name === 'insight_generator' ? { batch_index: attrs.batch_index, batch_count: attrs.batch_count, evidence_refs: attrs.evidence_refs, selected_evidence_count: attrs.selected_evidence_count } : (view || attrs)} />
  </section>;
  const output = <section>
    {traceStatus(node.status) === 'skipped' && <p className="muted">这次执行被跳过。{attrs.skip_reason ? `原因 ${valueText(attrs.skip_reason)}。` : ''}</p>}
    {name === 'fact_validator' && <>
      <Facts rows={[['接受', attrs.accepted_count], ['拒绝', attrs.rejected_count], ['候选', attrs.candidate_count]]} />
      <p className="muted">{node.fact_note === 'structured_facts_verified_interpretations_unverified' ? '结构化事实已核对。解释性陈述未验证。' : '结论级核对结论未采集。'}</p>
      <p className="muted">单条候选的失败原因没有按问题列表保存。</p>
    </>}
    {view && name !== 'fact_validator' && <>
      {batch && <p className="muted">下面是整份已保存报告，不是仅本批模型的原文。本批原文在 LLM。</p>}
      <h3>报告概览</h3>
      <Facts rows={[['报告', view.report_id], ['状态', reportStatus[String(view.report_status)] || view.report_status], ['覆盖', reportStatus[String(view.goal_coverage)] || view.goal_coverage], ['生成时间', view.generated_at], ['计划版本', view.plan_version], ['标题', summary?.headline]]} />
      {summary?.overview ? <p>{String(summary.overview)}</p> : null}
      {(name === 'insight_generator' || name === 'report_assembler') && <>
        <h3>洞察</h3>
        {insights.length ? insights.map(item => <details key={String(item.insight_id)} className="wf-task"><summary>{valueText(item.task_id)} · {valueText(item.insight_id)}</summary><p>{given(item.finding)}</p><Facts rows={[['事实', item.fact], ['解释', item.implication], ['建议', item.recommendation], ['证据', item.evidence_refs], ['限制', item.limitations]]} /></details>) : <p className="muted">没有已保存的洞察。</p>}
        <p className="muted">证据引用存在时，只表示报告保存了这些引用。对照 Input 里同一证据编号看模型当时拿到的结果值。不能据此说每条解释都已完成溯源。</p>
      </>}
      {name === 'evidence_builder' && <>
        <h3>证据</h3>
        {evidence.length ? evidence.map(item => <details key={String(item.evidence_id)} className="wf-task"><summary>{valueText(item.evidence_id)} · {valueText(item.task_id)} · {valueText(item.evidence_type)}</summary><p>{given(item.statement)}</p><Facts rows={[['计算', item.calculation], ['范围', item.scope], ['结果引用', item.related_result_refs]]} /></details>) : <p className="muted">没有已保存的证据。</p>}
      </>}
      {name === 'chart_builder' && <>
        <h3>图表</h3>
        {charts.length ? <ul>{charts.map(item => <li key={String(item.chart_id)}>{valueText(item.title)} · {valueText(item.chart_type)} · {valueText(item.task_id)}</li>)}</ul> : <p className="muted">没有已保存的图表。</p>}
      </>}
      {name === 'report_persistence' && <Facts rows={[['写入状态', reportStatus[String(view.report_status)] || view.report_status], ['报告', view.report_id], ['执行', view.execution_id]]} />}
      {(name === 'report_assembler' || name === 'insight_generator') && <>
        <h3>限制</h3>
        {Array.isArray(view.limitations) && view.limitations.length ? <ul>{view.limitations.filter((item): item is string => typeof item === 'string').map(item => <li key={item}>{item}</li>)}</ul> : <p className="muted">没有已保存的限制说明。</p>}
      </>}
      <p className="muted">{view.fact_validation === 'structured_facts_verified_interpretations_unverified' ? '报告生成成功不等于内容质量已验证。解释性陈述未验证。' : '质量结论未采集。'}</p>
      {view.result_rows_omitted === true && <p className="muted">结果明细未放入此视图。</p>}
    </>}
    <JsonDisclosure title="节点输出 JSON" value={view || attrs} />
  </section>;
  return <NodeChrome node={node} trace={trace} title={titles[name] || name} input={input} output={output} />;
}
