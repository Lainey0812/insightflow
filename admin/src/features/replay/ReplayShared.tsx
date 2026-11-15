import type { ReplayOutcome } from '../../types/replay';

export const outcomeLabels: Record<ReplayOutcome, string> = {
  cleared: '未再出现', recurred: '仍在', changed: '有变化', unchanged: '信号未变',
  blocked: '受阻', source_missing: '不能回放', not_run: '未回放',
};

export function OutcomeBadge({ outcome }: { outcome: ReplayOutcome }) {
  return <span className={'rg-status rg-' + outcome}>{outcomeLabels[outcome]}</span>;
}
