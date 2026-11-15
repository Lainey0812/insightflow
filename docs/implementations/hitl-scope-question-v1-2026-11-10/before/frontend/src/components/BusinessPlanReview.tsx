import { useEffect, useState } from 'react';
import { ArrowRight, ClipboardList, LoaderCircle, ShieldCheck, Trash2 } from 'lucide-react';
import { ScopeConfirmation } from './ScopeConfirmation';
import { directionScope } from './reviewScope';
import { DirectionEditor } from './DirectionEditor';
import { api } from '../api/client';
import type { AnalysisBasis, PlanVersion, ReviewPresentation, Session } from '../types/contracts';

const basisFunctions: Record<string,string> = {count:'计数',distinct_count:'去重计数',sum:'合计',avg:'均值',median:'中位数',min:'最小值',max:'最大值'};

interface Props {
  plan: PlanVersion; session: Session; busy: boolean;
  onRemove: (id: string) => void; onConfirm: (warnings?: string[]) => void; onBasisSaved?: (next: Session) => void; onRestart?: () => void;
}

export function BusinessPlanReview({plan, session, busy, onRemove, onConfirm, onBasisSaved, onRestart}: Props) {
  const [view, setView] = useState<ReviewPresentation | null>(null);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [grain, setGrain] = useState<AnalysisBasis['row_grain']>('unknown');
  const [entityField, setEntityField] = useState('');
  const [basisSaving, setBasisSaving] = useState(false);
  const [basisError, setBasisError] = useState('');
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [history, setHistory] = useState<unknown>(null);
  const [historyError, setHistoryError] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  useEffect(() => {
    let alive = true;
    setView(null); setError(''); setHistory(null); setAcknowledged([]); setEditing(null); setRemoving(null); setBasisError('');
    api.review(session.id).then(next => {
      if (!alive) return;
      if (next.session_id !== session.id || next.plan_id !== plan.plan_id || next.plan_version !== plan.plan_version || next.revision !== session.revision)
        setError('方案已更新，请刷新会话后审核最新内容。');
      else {setView(next);setGrain(next.analysis_basis?.row_grain ?? 'unknown');setEntityField(next.analysis_basis?.entity_field_id ?? '');}
    }).catch(() => {if (alive) setError('暂时无法核对当前方案的审批资格。请重新加载；在核对完成前不会开始分析。');});
    return () => {alive = false;};
  }, [session.id, session.revision, plan.plan_id, plan.plan_version, reload]);
  const current = plan.plan_version === session.current_plan_version;
  const basisEditable = current && ['AWAITING_APPROVAL','APPROVED'].includes(session.status);
  const eligible = !!view && current && (view.can_approve || view.can_execute);
  const ready = eligible && view!.warnings.every(w => acknowledged.includes(w.id) || view!.can_execute);
  const completed = session.review_status === 'completed';
  const profileFields = session.profile && 'fields' in session.profile ? session.profile.fields : [];
  // Preserve explicit requests; omit only plan-derived repetitions and the empty-request placeholder.
  const requestedConditions = view?.conditions.filter(c => !c.source.startsWith('plan.') && c.source !== 'intent.constraints') ?? [];
  const scopeChoices = view && basisEditable ? plan.validated_plan.intent_snapshot.constraints.filters.flatMap((constraint,filter_index)=>{
    const source=`intent.constraints.filters[${filter_index}]`;
    if (!view.audit.items.some(item=>item.source===source && item.status==='unmapped')) return [];
    const fields=new Set<string>();let valid=true;
    for (const task of plan.validated_plan.plan.tasks) {
      const conditions=task.steps.filter(step=>step.operation==='filter').flatMap(step=>(step.params.conditions ?? []) as {field:string;operator:string;value:unknown}[]);
      const match=conditions.filter(c=>(c.operator==='eq'&&c.value===constraint.raw_text)||(c.operator==='in'&&Array.isArray(c.value)&&c.value.length===1&&c.value[0]===constraint.raw_text));
      if(match.length!==1)valid=false;else fields.add(match[0].field);
    }
    const field=profileFields.find(f=>fields.has(f.field_id) && f.logical_type==='text');
    return valid&&fields.size===1&&field ? [{field_id:field.field_id,filter_index,keyword:constraint.raw_text,fieldName:field.display_name}] : [];
  }) : [];
  const buttonLabel = completed ? '分析已完成' : session.review_status === 'execution_failed' ? '分析未完成，请查看结果' : view?.can_execute ? '开始已确认的分析' : '确认并开始分析';
  return <section className="plan-card business-review" aria-label={`分析方案 第${plan.plan_version}版`}>
    <header className="review-heading"><span className="review-symbol"><ClipboardList size={21}/></span><div><h3>这些分析方向符合你的需求吗？</h3><p>第 {plan.plan_version} 版 · 可以修改或移除方向，确认前不会计算</p></div><span className="review-state">{completed ? '已完成' : eligible ? '等待你的确认' : '核对分析条件'}</span></header>
    {error && <div className="review-load-error" role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setReload(n => n + 1)}>重新加载方案</button></div>}
    {!view && !error && <p className="review-loading" role="status"><LoaderCircle size={17} className="spin"/>正在核对分析方案与可用条件…</p>}
    {view && <>
      <section className="review-section review-goal"><p className="review-eyebrow">01 · 核心分析目标</p><h4>{view.goal}</h4><p className="review-coverage">{view.coverage}</p>
        {plan.plan_version > 1 && <p className="review-version-change"><strong>本版变更：</strong>{plan.change_summary.replace(/\bA\d+\b/g,'对应方向')} 当前版本需重新确认，历史方案和审批保留。</p>}
      </section>
      <section className="review-section" aria-label="本次使用的数据"><h4>02 · 本次使用的数据</h4>
        {view.data_overview ? <>
          <p className="review-explanation">{view.data_overview.file_name}{view.data_overview.sheet_name && ` / ${view.data_overview.sheet_name}`} · 上传数据概况</p>
          <div className="review-data-cards">
            <div><span>上传记录</span><strong>{view.data_overview.row_count.toLocaleString()}<small> 条</small></strong></div>
            <div><span>数据字段</span><strong>{view.data_overview.column_count.toLocaleString()}<small> 个</small></strong></div>
            <div><span>缺失单元格</span><strong>{view.data_overview.missing_cell_count.toLocaleString()}<small> 个</small></strong></div>
            <div><span>疑似重复记录</span><strong>{view.data_overview.duplicate_row_count.toLocaleString()}<small> 条</small></strong></div>
          </div>
          <div className="review-data-notice"><strong>已检查，未自动清洗</strong><p>{view.data_overview.cleaning_notice}</p><p>{view.data_overview.sample_notice}</p></div>
          {(view.data_overview.fields_with_missing.length > 0 || view.data_overview.quality_notes.length > 0) && <details className="review-quality-details"><summary>查看缺失字段与数据质量提示</summary>
            <ul>{view.data_overview.fields_with_missing.map(f=><li key={f.name}>{f.name}：缺失 {f.missing_count} 个单元格</li>)}{view.data_overview.quality_notes.map((note,i)=><li key={i}>{note}</li>)}</ul>
          </details>}
          <p className="review-explanation">以上为上传数据总量；各方向的筛选条件见下方，实际参与计算的数量在执行后展示。</p>
        </> : <p className="review-explanation">此版本没有可核验的数据概况，不能据此判断有效样本量或已完成清洗。</p>}
        {requestedConditions.length > 0 && <div className="review-requested-conditions"><strong>你指定的范围与要求</strong><ul>{requestedConditions.map((condition,i)=><li key={i}><span>{condition.label}：{condition.text}</span><small>{condition.verification}</small></li>)}</ul></div>}
        {view.analysis_basis && <>
        <details className="basis-editor" aria-label="数据记录含义"><summary>需要说明一行代表什么？（可选）</summary>
          <label>记录粒度 <select aria-label="记录粒度" value={grain} disabled={busy || basisSaving || !!editing || !!removing || !basisEditable} onChange={event=>{setGrain(event.target.value as AnalysisBasis['row_grain']);setEntityField('');}}>
            <option value="unknown">暂未确认业务含义</option><option value="record">每行一条记录</option><option value="detail">每行一条明细，同一实体可能多行</option><option value="entity">每行一个实体，需唯一标识核验</option>
          </select></label>
          {grain === 'entity' && <label>实体标识 <select aria-label="实体标识" value={entityField} disabled={busy || basisSaving || !!editing || !!removing || !basisEditable} onChange={event=>setEntityField(event.target.value)}><option value="">请选择非空且唯一的标识</option>{view.analysis_basis.entity_field_options.map(field=><option key={field.field_id} value={field.field_id} disabled={!field.unique_non_null}>{field.label}{!field.unique_non_null && '（含缺失或重复）'}</option>)}</select></label>}
          <p>声明只描述上传数据，不改变中间分组结果的含义。保存会生成新计划版本并要求重新审批。此次声明不会改变计算字段或函数；调整已有计算请使用对应方向的修改表单。</p>
          {basisError && <p role="alert">{basisError}</p>}
          <button className="secondary-button" disabled={busy || basisSaving || !basisEditable || !onBasisSaved || !!editing || !!removing || (grain === 'entity' && !entityField)} onClick={async()=>{
            setBasisSaving(true);setBasisError('');try {const next=await api.saveAnalysisBasis(session,grain,grain === 'entity' ? entityField : null);onBasisSaved?.(next);} catch(error) {setBasisError(error instanceof Error ? error.message : '口径保存失败，请刷新当前方案。');} finally {setBasisSaving(false);}
          }}>{basisSaving ? '正在保存口径…' : '保存粒度声明并重新审核'}</button>
        </details>
        </>}
      </section>
      <section className="review-section"><h4>03 · 请确认分析方向</h4><p className="review-explanation">重点看看这些问题是否是你想分析的。可以修改或移除方向，计算方法按需展开。</p><ol className="review-directions">{view.directions.map((direction, i) => <li key={direction.task_id}>
        <div className="direction-top"><span className="direction-index">{String(i + 1).padStart(2, '0')}</span><span className={`direction-importance ${direction.importance === '核心分析' ? 'core' : ''}`}>{direction.importance}</span><span className={`direction-ready ${direction.executable ? '' : 'blocked'}`}>{direction.readiness}</span></div>
        <h5>{direction.title}</h5><p className="direction-question">{direction.question}</p><p className="direction-reason">为什么分析：{direction.reason}</p>
        <div className="direction-scope" aria-label={`${direction.title}的数据范围`}>{directionScope(plan.validated_plan.plan.tasks.find(t=>t.task_id===direction.task_id),profileFields).map((line,j)=><p key={j}>{line}</p>)}</div>
        <details className="direction-calculation" aria-label={`${direction.title}的计算说明`}><summary>查看计算说明</summary>
          <ul className="direction-method">{direction.details.map((line, j) => <li key={j}>{line}</li>)}</ul>
          {view.analysis_basis && <ul className="direction-metric-basis">{view.analysis_basis.metrics.filter(metric=>metric.task_id===direction.task_id).map(metric=><li key={`${metric.step_id}:${metric.alias}`}>
            <strong>{metric.label}（{basisFunctions[metric.function] ?? '待核对计算'}）</strong>：{metric.basis}{metric.unit_status === 'not_declared' && '；单位未登记，不自动进行单位换算'}</li>)}</ul>}
        </details>
        {direction.gaps.map((gap, j) => <p className="direction-gap" key={j}>{gap}</p>)}
        {current && <div className="direction-controls"><button className="secondary-button" disabled={busy || basisSaving || !!editing || !!removing || !direction.can_remove || !onBasisSaved} aria-label={`修改此方向：${direction.title}`} onClick={()=>setEditing(direction.task_id)}>修改此方向</button>
          <button className="direction-remove" onClick={() => setRemoving(direction.task_id)} disabled={busy || basisSaving || !!editing || !!removing || !direction.can_remove} aria-label={`删除${direction.title}`}><Trash2 size={13}/>移除此方向{direction.importance === '核心分析' && <span>（会重新检查核心目标）</span>}</button></div>}
        {editing === direction.task_id && <DirectionEditor key={`${plan.plan_version}:${direction.task_id}`} task={plan.validated_plan.plan.tasks.find(t=>t.task_id===direction.task_id)!} session={session}
          onPending={setEditSaving} onCancel={()=>setEditing(null)} onSaved={next=>{setEditing(null);setAcknowledged([]);onBasisSaved?.(next);}}/>}
        {removing === direction.task_id && <div className="direction-delete-check" role="group" aria-label="确认移除方向"><strong>移除“{direction.title}”？</strong><p>{direction.importance === '核心分析' ? '这是核心分析，移除后可能无法回答原问题。' : '此方向将不参与计算。'}保存新版本后会重新校验目标覆盖，原审批失效，需要再次确认。</p><div className="editor-actions"><button className="secondary-button" disabled={busy} onClick={()=>setRemoving(null)}>保留此方向</button><button className="secondary-button" disabled={busy} onClick={()=>{onRemove(direction.task_id);setRemoving(null);}}>确认移除并重新审核</button></div></div>}
      </li>)}</ol>{!view.directions.length && <p className="review-issue">当前没有分析方向，请重新提出需求。</p>}</section>
      {view.report_capacity && !view.report_capacity.supported && <section className="review-section" aria-label="报告生成容量"><p role="alert">{view.report_capacity.message}</p></section>}
      <section className="review-section"><h4>04 · 需要你确认的问题</h4>
        {onBasisSaved && scopeChoices.map(choice=><ScopeConfirmation key={`${plan.plan_version}:${choice.filter_index}`} session={session} target={{field_id:choice.field_id,filter_index:choice.filter_index,keyword:choice.keyword}} fieldName={choice.fieldName} busy={busy||basisSaving||!!editing||!!removing} onSaved={onBasisSaved} onPending={setBasisSaving}/>)}{view.issues.length ? <ul className="review-issues">{view.issues.map((issue, i) => <li key={i}><strong>{issue.message}</strong><p>{issue.next_step}</p></li>)}</ul> : <p className="review-no-issues"><ShieldCheck size={17}/>当前没有阻止审批的待解决事项。</p>}
        {view.warnings.map(warning => <label className="review-warning" key={warning.id}><input type="checkbox" checked={view.can_execute || acknowledged.includes(warning.id)} disabled={busy || view.can_execute || completed} onChange={event => setAcknowledged(values => event.target.checked ? [...values, warning.id] : values.filter(id => id !== warning.id))}/><span>{warning.label}</span></label>)}
      </section>
    </>}
    <footer className="review-actions"><div><h4>05 · 确认与操作</h4><p><ShieldCheck size={14}/>按当前方案和文件版本开始</p><small>分析后可查看真实计算结果与报告</small></div><button className="primary-button" disabled={busy || basisSaving || editSaving || !!editing || !!removing || !ready} onClick={() => {if (ready && !editing && !removing && !editSaving) onConfirm(acknowledged);}}>{buttonLabel}<ArrowRight size={15}/></button></footer>
    <div className="review-restart"><p>修改已有方向请使用方向内的表单；如需更换分析目标、增加新方法或补充未确认口径，请重新提出需求。当前方案和历史版本会保留。</p>{onRestart && <button className="secondary-button" disabled={busy || editSaving || basisSaving} onClick={onRestart}>重新提出需求</button>}</div>
    <details className="review-technical"><summary>技术详情</summary><p>此处保留原始计划、字段引用、约束来源与逐步核验结果。</p>
      {view?.report_capacity?.supported && <section aria-label="报告生成容量"><h4>报告生成安排</h4><p>{view.report_capacity.message}</p></section>}<pre>{JSON.stringify(view?.technical_details ?? {record: plan}, null, 2)}</pre>
      <button className="secondary-button" disabled={busy} onClick={async () => {setHistoryError('');try {const versions = await api.versions(session.id);const approvals = await api.approvals(session.id);const proofs = await api.constraintAudits(session.id);setHistory({versions, approvals, constraint_audits: proofs});} catch {setHistoryError('版本记录暂时无法加载，请稍后重试。');}}}>版本与审批记录</button>
      {historyError && <p role="alert">{historyError}</p>}{history !== null && <pre>{JSON.stringify(history, null, 2)}</pre>}
    </details>
  </section>;
}
