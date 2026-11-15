import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Info, RefreshCw } from 'lucide-react';
import { ApiError } from '../../api/client';
import { lifecycleApi } from '../../api/lifecycle';
import type { LifecycleActivity, LifecycleReadModel, LifecycleReason, LifecycleStatus } from '../../types/lifecycle';
import type { TraceRun } from '../../types/traces';
import { KeyValues } from './TraceShared';
import { TraceError } from './AccessPanel';

const statuses: Record<LifecycleStatus, string> = {
  created: '已创建', running: '处理中', waiting_input: '等待补充信息', waiting_approval: '等待确认方案',
  succeeded: '分析与报告已完成', partially_succeeded: '部分完成', failed: '分析失败', interrupted: '流程中断', unknown: '状态待核查',
};
const activities: Record<LifecycleActivity, string> = {
  not_started: '尚未启动分析', preparing: '准备数据与需求', profiling: '生成数据画像', parsing_intent: '理解分析需求',
  planning: '生成分析方案', validating: '校验分析方案', clarification: '等待用户补充需求', review: '等待审核分析方案',
  approved_not_started: '方案已批准，计算尚未启动', executing: '执行计算', report_not_started: '计算已保存，报告尚未启动',
  report_queued: '报告已排队', reporting: '生成报告', finished: '本分支活动已结束', unknown: '当前活动无法可靠确认',
};
const reasons: Record<LifecycleReason, string> = {
  clarification_required: '需要用户补充分析需求，之后才能继续规划。', approval_required: '分析方案等待用户审核确认。',
  approved_not_started: '服务端已保存有效审批，尚无当前分支的计算执行。', core_requirements_unmet: '仍有核心分析要求未被完整覆盖，请核对方案与缺失条件。',
  uncertainties_unresolved: '存在尚未解决的统计口径或分析范围问题。', execution_partial: '部分计算任务失败或跳过，成功结果仍然保留。',
  execution_failed: '本次计算没有成功任务，请查看执行错误。', report_failed: '报告生成失败，已保存的计算结果仍然保留。',
  report_not_delivered: '当前分支尚未交付可用报告。', report_unavailable: '没有生成可用报告，不能视为目标已完成。',
  report_partial: '报告只包含部分有效成果。', goal_not_fully_covered: '已生成报告仍未完整回答核心目标。', report_not_started: '计算结果已保存，报告生成尚未登记。',
  report_retry: '当前报告是新的重试尝试，以当前尝试的保存状态为准。', process_interrupted: '已保存记录表明流程发生中断。',
  trace_not_collected: '相关过程追踪未采集，不能据此判断业务没有执行。', trace_unavailable: '追踪存储暂不可读，业务结果与追踪采集分别展示。',
  trace_incomplete: '追踪仅覆盖部分节点，不补造未采集的节点状态。', trace_stale: '追踪检查点落后于业务记录，不用旧检查点覆盖当前结果。',
  trace_binding_mismatch: '追踪记录与当前分支关联冲突，需要核查来源记录。', trace_state_conflict: '追踪记录与业务记录的状态冲突，暂不确认最终状态。',
  unsupported_workflow: '旧 Mock、人工导入或非真实主流程记录不推断为真实业务成功。', record_missing: '缺少确认当前分支所必需的保存记录。',
  record_invalid: '保存记录未通过结构核对，不能可靠聚合状态。', branch_mismatch: '数据、方案、审批或结果版本不一致。',
  historical_branch_ignored: '旧版本的执行和报告已保留，但未用于判断当前计划是否完成。', execution_ambiguous: '存在多个当前执行候选，无法可靠选定。',
  session_changed: '查询期间业务记录发生变化，请刷新后核对。', business_store_unavailable: '业务存储暂不可读，无法确认当前生命周期。',
  business_state_conflict: '已保存业务记录相互矛盾，需要核查对应版本。',
};
const executionLabels = { running: '计算执行中', success: '计算成功', partial_success: '计算部分成功', failed: '计算失败' };
const generationLabels = { queued: '报告已排队', generating: '报告生成中', completed: '报告生成已结束', failed: '报告生成失败', unavailable: '无可用报告' };
const reportLabels = { complete: '完整报告', partial: '部分报告', unavailable: '报告不可用' };
const deliveryLabels = { delivered: '报告已交付', not_delivered: '报告未交付', unknown: '报告交付尚未确认' };
const coverageLabels = { complete: '完整覆盖目标', partial: '部分覆盖目标', blocked: '核心目标未被回答' };
const collectionLabels = { available: '已采集部分过程', not_collected: '相关追踪未采集', unavailable: '追踪暂不可用', unknown: '采集情况尚未确认' };
const scopeLabels: Record<string, string> = { workflow_preparation: 'Workflow 准备阶段', report_generation: '报告生成阶段' };

export function LifecyclePanel({ run, refresh }: { run: TraceRun; refresh: number }) {
  const [value, setValue] = useState<LifecycleReadModel | null>(null);
  const [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setValue(null); setError(null); setLoading(true);
    if (!run.session_id) { setLoading(false); return () => controller.abort(); }
    lifecycleApi.get(run.session_id, controller.signal).then(result => { if (!controller.signal.aborted) setValue(result); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [run.session_id, run.run_id, refresh, retry]);
  const reload = () => setRetry(current => current + 1);
  if (!run.session_id) return <section className="trace-card lifecycle-panel" aria-label="当前分析任务"><h2>当前分析任务</h2><p className="unavailable-note">历史 Trace 未保存会话关联，生命周期不可用。下方仍展示原有追踪记录。</p></section>;
  if (loading) return <section className="trace-card lifecycle-panel" aria-label="当前分析任务"><h2>当前分析任务</h2><p role="status">正在核对当前分支的生命周期…</p></section>;
  if (error || !value) return <section className="trace-card lifecycle-panel" aria-label="当前分析任务"><h2>当前分析任务</h2><p className="muted">生命周期查询未完成；下方 Trace 仍可独立查看，不将接口错误当作业务失败。</p>
    {error instanceof ApiError && (error.status === 503 || error.status === 404) ? <div role="alert"><p>{error.status === 404 ? '关联会话或生命周期查询接口不存在，请核对记录与后端版本。' : '生命周期服务暂不可用，请检查后端是否已加载新接口及存储连接。'}</p><button className="secondary-button" onClick={reload}>重新加载生命周期</button></div> : <TraceError resource="生命周期信息" error={error} retry={reload} />}</section>;
  const b = value.business_lifecycle, refs = value.source_refs, collection = value.collection;
  const historical = run.kind !== 'workflow' && ((!!run.execution_id && run.execution_id !== refs.execution_id) ||
    (typeof run.attempt === 'number' && refs.report_attempt !== null && run.attempt !== refs.report_attempt));
  const conflicting = value.consistency.status !== 'consistent';
  const Icon = b.status === 'succeeded' ? CheckCircle2 : ['failed', 'interrupted', 'unknown', 'partially_succeeded'].includes(b.status) ? AlertCircle : Info;
  const businessReasons = value.reason_codes.filter(code => !['trace_not_collected', 'trace_unavailable', 'trace_incomplete', 'trace_stale'].includes(code));
  const collectionReasons = value.reason_codes.filter(code => ['trace_not_collected', 'trace_unavailable', 'trace_incomplete', 'trace_stale'].includes(code));
  return <section className={`trace-card lifecycle-panel lifecycle-${b.status}`} aria-label="当前分析任务">
    <div className="section-heading"><h2>当前分析任务</h2><button className="secondary-button" onClick={reload}><RefreshCw size={13} />刷新任务状态</button></div>
    <div className="lifecycle-lead"><Icon size={23} aria-hidden="true" /><div><strong>{statuses[b.status]}</strong><p>{activities[value.activity]}</p></div></div>
    <p className="muted">依据当前数据集、方案、有效审批与执行记录核对。显示最后保存的活动，不代表进程此刻仍在线。</p>
    {historical && <p className="trace-notice trace-warning" role="note">当前查看的是历史报告 Trace。上方是任务当前分支状态，下方保留本次历史尝试，不混用两者的结果。</p>}
    {conflicting && <p className="lifecycle-consistency-warning" role="alert">{value.consistency.status === 'inconsistent' ? '记录存在关联冲突，当前生命周期待核查。' : '记录不足以可靠确认当前生命周期。'} 请查看下方原因和关联依据。</p>}
    <dl className="lifecycle-outcomes">
      <div><dt>计算结果</dt><dd>{b.execution_status ? executionLabels[b.execution_status] : '暂无已关联的计算记录'}</dd></div>
      <div><dt>报告交付</dt><dd>{deliveryLabels[b.report_delivery]}</dd><small>{b.report_generation_status ? generationLabels[b.report_generation_status] : '暂无已关联的报告生成记录'}{refs.report_attempt !== null ? `，第 ${refs.report_attempt} 次尝试` : ''}</small>
        {b.report_status && <small>{reportLabels[b.report_status]}{b.goal_coverage ? `，${coverageLabels[b.goal_coverage]}` : ''}</small>}</div>
      <div><dt>过程采集</dt><dd>{collectionLabels[collection.availability]}</dd><small>{scopeLabels[collection.capture_scope || ''] || '采集范围未记录'}；完整性{collection.integrity === 'incomplete' ? '不足' : '未知'}</small></div>
    </dl>
    {!!businessReasons.length && <div className="lifecycle-reasons"><h3>当前需要了解的情况</h3><ul>{businessReasons.map(code => <li key={code}>{reasons[code]}</li>)}</ul></div>}
    {!!collectionReasons.length && <div className="lifecycle-collection"><h3>追踪采集说明</h3><ul>{collectionReasons.map(code => <li key={code}>{reasons[code]}</li>)}</ul></div>}
    <details className="lifecycle-sources"><summary>查看当前分支、版本与记录依据</summary>
      <p className="muted">{value.consistency.status === 'consistent' ? '当前已保存记录的关联已核对。' : '当前关联未确认。'}跨库查询不是原子快照；Session {value.consistency.revision_rechecked ? '已复查' : '未完成复查'}。报告历史尝试尚不保证完整。</p>
      <KeyValues source={Object.fromEntries(Object.entries(refs).map(([key, item]) => [key, item ?? '未关联或不可用']))} fields={{ session_id: '会话', session_revision: '会话版本', dataset_id: '当前数据集', dataset_version: '数据集版本', plan_id: '当前方案', plan_version: '方案版本', validation_version: '校验版本', approval_id: '审批记录', execution_id: '当前执行', report_attempt: '报告尝试', report_id: '报告记录' }} />
      <p className="muted">原始追踪：{refs.workflow_run_id ? <Link className="trace-link" to={'/traces/' + encodeURIComponent(refs.workflow_run_id)}>Workflow Trace</Link> : 'Workflow Trace 未采集'}{' / '}{refs.report_run_id ? <Link className="trace-link" to={'/traces/' + encodeURIComponent(refs.report_run_id)}>当前报告 Trace</Link> : '当前报告 Trace 未采集'}</p>
      <p className="muted">此聚合仅引用实际保存的 {collection.observed_spans.length} 条 Span、{collection.event_count} 条 Event，不补造过程记录。</p>
      <details><summary>诊断原因代码</summary><p className="wrap-code">{value.reason_codes.join(' / ') || '无额外原因代码'}</p></details>
    </details>
  </section>;
}
