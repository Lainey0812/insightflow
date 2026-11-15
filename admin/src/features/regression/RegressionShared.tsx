import type { CaseStatus, RegressionChange } from '../../types/regression';

export const caseStatusLabels: Record<CaseStatus, string> = { passed: '通过', failed: '未通过', blocked: '受阻', needs_review: '待人工', not_run: '未自动运行' };
export const changeLabels: Record<RegressionChange, string> = { improved: '变好', regressed: '变差', unchanged: '不变', changed: '有变化', not_compared: '不比较', only_one: '只在一侧' };
export function CaseStatusBadge({ status }: { status: CaseStatus | null }) {
  if (!status) return <span className="muted">—</span>;
  return <span className={`rg-status rg-${status}`}>{caseStatusLabels[status]}</span>;
}
export function ChangeBadge({ change }: { change: RegressionChange }) {
  return <span className={`rg-change rg-change-${change}`}>{changeLabels[change]}</span>;
}
