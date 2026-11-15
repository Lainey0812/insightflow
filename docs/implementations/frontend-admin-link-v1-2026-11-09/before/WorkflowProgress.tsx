import { CircleDot, LoaderCircle } from 'lucide-react';
import { statusLabels, type Session } from '../types/contracts';
import { workflowStep } from '../workflow/presentation';

export function WorkflowProgress({session, busy, onRetry}: {session: Session; busy: boolean; onRetry: () => void}) {
  const step = workflowStep(session);
  const profile = session.profile && 'row_count' in session.profile ? session.profile : null;
  return <section className={`workflow-progress ${step.running ? 'is-running' : ''} ${session.status === 'FAILED' ? 'is-failed' : ''}`} aria-label="真实流程状态">
    <div className="workflow-step-main" role="status" aria-live="polite">
      <span className="step-indicator">{step.running ? <LoaderCircle size={17} className="spin"/> : <CircleDot size={17}/>}</span>
      <div><span className="step-caption">当前步骤</span><h3>{step.title}</h3><p>{step.description}</p></div>
    </div>
    <details className="workflow-step-details"><summary>查看过程</summary>
      <div className="workflow-step-popover"><p>以下为已保存的业务状态，刷新后可恢复；未采集的节点不补造进度。</p>
        {profile && <p>已读取 {profile.row_count} 行、{profile.column_count} 列；{profile.quality_issues.length} 项质量提示。</p>}
        {session.intent && 'analysis_goal' in session.intent && <p>分析目标：{session.intent.analysis_goal.business_goal ?? '等待补充'}</p>}
        {!!session.workflow_events?.length && <ol>{session.workflow_events.map((event, index) => <li key={index}>{statusLabels[event.status]}<time>{new Date(event.recorded_at).toLocaleString('zh-CN')}</time></li>)}</ol>}
      </div>
    </details>
    {session.status === 'FAILED' && session.error && <div className="workflow-failure"><p role="alert">{session.error.message}</p><details><summary>错误详情</summary><code>{session.error.code}</code></details>
      {session.error.retryable && !session.review_plan && !session.engine_execution_ids?.length && <button className="secondary-button" onClick={onRetry} disabled={busy}>重试准备</button>}
    </div>}
  </section>;
}
