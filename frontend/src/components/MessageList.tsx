import { useEffect, useRef } from 'react';
import { FileSpreadsheet, LoaderCircle } from 'lucide-react';
import type { Session } from '../types/contracts';
import { Brand } from './Brand';
import { PlanReviewCard } from './PlanReviewCard';
import { ReportLinkCard } from './ReportLinkCard';
import { ExecutionPreview } from './ExecutionPreview';
import { ReportGenerationCard } from './ReportGenerationCard';

interface Props { session: Session; busy: boolean; pending: string; questions?: string[]; onRemove: (id: string) => void; onConfirm: (warnings?: string[]) => void; onBasisSaved?: (next: Session) => void; onRestart?: () => void; onReportChange?: () => void }
export function MessageList({ session, busy, pending, questions = [], onRemove, onConfirm, onBasisSaved, onRestart, onReportChange }: Props) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'end' }); }, [session.id, session.messages.length, pending, questions.length]);
  return <div className="message-list" aria-label="当前对话记录">
    <div className="conversation-date">{new Date(session.created_at).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}<span>本次咨询</span></div>
    {session.messages.map((message, index) => <article key={message.id} className={`message ${message.role} ${message.kind}`}>
      <div className="message-avatar">{message.role === 'user' ? '你' : <Brand small />}</div>
      <div className="message-content"><div className="message-meta"><strong>{message.role === 'user' ? '你' : 'InsightFlow'}</strong>{message.role !== 'user' && <span className="ai-tag">AI</span>}<time>{new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time></div>
        {index === 0 && message.role === 'user' && <div className="file-message"><FileSpreadsheet size={20} /><span><strong>{session.file.name}</strong><small>{(session.file.size / 1024).toFixed(1)} KB · 已保存到本地</small></span></div>}
        <p className="message-text">{session.review_plan && message.kind === 'plan' ? '分析方案已准备好，请核对下方目标、条件与分析方向。' : session.review_plan && message.content.startsWith('删除任务：') ? '已移除分析方向，并重新核对方案。' : session.review_plan && message.content.includes('已重新校验，目标覆盖：') ? '新方案已保存，请审核当前版本。' : session.workflow_kind === 'real_v1' && message.content.includes('本阶段不自动生成报告') ? '计算已结束，真实结果已保存。报告生成状态见下方。' : message.content}</p>
        {!session.review_status && message.kind === 'plan' && (() => { const plan = session.plans.find(p => p.version === message.plan_version); return plan ? <PlanReviewCard plan={plan} session={session} busy={busy} onRemove={onRemove} onConfirm={onConfirm} /> : null; })()}
        {message.kind === 'report' && session.report && <ReportLinkCard sessionId={session.id} report={session.report} />}
      </div>
    </article>)}
    {questions.length > 0 && <article className="message assistant" aria-label="待确认问题"><div className="message-avatar"><Brand small /></div><div className="message-content"><div className="message-meta"><strong>InsightFlow</strong><span className="ai-tag">AI</span></div><p className="message-text">有问题需要你确认。直接在下方回复即可，不用重新上传文件，也不用把原来的问题再说一遍。</p><ol>{questions.map((question, index) => <li key={`${index}:${question}`}>{question}</li>)}</ol></div></article>}
    {session.review_plan && <PlanReviewCard key={`${session.id}:${session.review_plan.plan_version}`} plan={session.review_plan} session={session} busy={busy} onRemove={onRemove} onConfirm={onConfirm} onBasisSaved={onBasisSaved} onRestart={onRestart}/>}
    {session.engine_execution_ids?.map(id => <div key={`${id}:${session.status}`}>
      {session.workflow_kind === 'real_v1' ? <><ReportGenerationCard executionId={id} sessionId={session.id} record={session.report_generations?.find(r => r.execution_id === id)} onChange={onReportChange}/>
        <details className="plan-card"><summary>查看原始计算结果</summary><ExecutionPreview sessionId={session.id} executionId={id}/></details></> : <ExecutionPreview sessionId={session.id} executionId={id}/>}
    </div>)}
    {busy && pending && <div className="pending-message" role="status"><LoaderCircle className="spin" size={17} />{pending}</div>}
    <div ref={bottom} />
  </div>;
}
