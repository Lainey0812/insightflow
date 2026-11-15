import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, FlaskConical } from 'lucide-react';
import { EmptyState } from '../components/EmptyState';

export function EvaluationCasePlaceholderPage() {
  const { runId = '', caseId = '' } = useParams();
  const runPath = '/evaluations/runs/' + encodeURIComponent(runId);
  return <div className="wf-page"><Link className="wf-back" to={runPath}><ChevronLeft size={15} />返回运行详情</Link>
    <header className="wf-heading"><div><h1>Case 详情</h1><p className="wf-id">{runId} · {caseId}</p></div></header>
    <EmptyState icon={FlaskConical} statusLabel="下一阶段开放" title="Case 详情将在下一阶段开放"
      description="逐个 Evaluator 的结果、执行记录与证据将在 Phase 2-C2 提供。当前页面不请求 Case 接口，也不展示推测内容。"
      note="Case 的执行状态、E2E 结果与完整性可在运行详情的 Case Results 中查看。" />
    <p><Link className="primary-button" to={runPath}>返回运行详情</Link></p>
  </div>;
}
