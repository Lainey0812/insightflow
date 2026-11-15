import type { LucideIcon } from 'lucide-react';

export function EmptyState({ icon: Icon, title, description, note, statusLabel = '数据接口尚未接入' }: {
  icon: LucideIcon; title: string; description: string; note: string; statusLabel?: string;
}) {
  return <section className="empty-card" aria-label={title}>
    <div className="empty-illustration" aria-hidden="true"><div className="illustration-square"><Icon size={32} strokeWidth={1.4} /></div><span /><span /></div>
    <span className="status-label"><span className="neutral-dot" />{statusLabel}</span>
    <h2>{title}</h2><p className="empty-description">{description}</p>
    <div className="scope-note">{note}</div>
  </section>;
}
