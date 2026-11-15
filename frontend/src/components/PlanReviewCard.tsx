import { ArrowRight, Check, ClipboardList, LockKeyhole, Trash2 } from 'lucide-react';
import { BusinessPlanReview } from './BusinessPlanReview';
import type { Plan, Session, PlanVersion } from '../types/contracts';

interface Props { plan: Plan | PlanVersion; session: Session; busy: boolean; onRemove: (id: string) => void; onConfirm: (warnings?: string[]) => void; onBasisSaved?: (next: Session) => void; onRestart?: () => void }
export function PlanReviewCard({ plan, session, busy, onRemove, onConfirm, onBasisSaved, onRestart }: Props) {
  if ('validated_plan' in plan) return <BusinessPlanReview plan={plan} session={session} busy={busy} onRemove={onRemove} onConfirm={onConfirm} onBasisSaved={onBasisSaved} onRestart={onRestart}/>;
  const current = plan.version === session.current_plan_version;
  const editable = current && ['AWAITING_APPROVAL', 'APPROVED'].includes(session.status);
  const approved = session.approved_plan_version === plan.version;
  return <section className={`plan-card ${!current ? 'historical' : ''}`} aria-label={`分析计划 v${plan.version}`}>
    <div className="plan-heading"><span className="card-icon"><ClipboardList size={19} /></span><div><h3>分析计划 <span>v{plan.version}</span></h3><p>{plan.tasks.length} 个分析任务 · Mock 示例</p></div><span className={`plan-badge ${approved ? 'approved' : ''}`}>{!current ? '历史版本' : approved ? '已确认' : session.status === 'COMPLETED' ? '已执行' : '等待你的确认'}</span></div>
    <ol className="task-list">{plan.tasks.map((task, index) => <li key={task.id}><span className="task-number">{String(index + 1).padStart(2, '0')}</span><div><strong>{task.title}</strong><p>{task.description}</p></div>{editable && <button className="icon-button delete-task" onClick={() => onRemove(task.id)} disabled={busy || plan.tasks.length <= 1} aria-label={`删除${task.title}`} title={plan.tasks.length <= 1 ? '至少保留一个任务' : '删除任务并生成新版本'}><Trash2 size={15} /></button>}</li>)}</ol>
    {editable ? <div className="plan-footer"><span><LockKeyhole size={13} /> 确认前不会执行分析</span><button className="primary-button" disabled={busy} onClick={() => onConfirm()}>{approved ? '继续执行' : '确认并执行'}<ArrowRight size={15} /></button></div> : <div className="plan-readonly"><Check size={14} />{!current ? '已保留此版本，请在最新计划中操作' : '已确认的计划已保留，可追溯每个分析任务'}</div>}
  </section>;
}

