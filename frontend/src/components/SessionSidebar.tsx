import { ChevronLeft, MessageSquare, Plus, ShieldCheck } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { SessionSummary } from '../types/contracts';
import { statusLabels } from '../types/contracts';
import { Brand } from './Brand';

interface Props {
  sessions: SessionSummary[]; selectedId?: string; busy: boolean; open: boolean;
  running?: boolean;
  onSelect: (id: string) => void; onNew: () => void; onClose: () => void;
}
export function SessionSidebar({ sessions, selectedId, busy, running = false, open, onSelect, onNew, onClose }: Props) {
  const aside = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (open) close.current?.focus(); }, [open]);
  return <>
    {open && <button className="sidebar-scrim" aria-label="关闭会话列表" onClick={onClose} />}
    <aside ref={aside} className={`sidebar ${open ? 'is-open' : ''}`} aria-label="咨询记录侧栏" onKeyDown={event => {
      if (!open) return;
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key === 'Tab') {
        const targets = Array.from(aside.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
        const first = targets[0], last = targets.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <div className="brand"><Brand /><span>InsightFlow</span><button ref={close} className="icon-button mobile-close" aria-label="收起会话列表" onClick={onClose}><ChevronLeft size={18} /></button></div>
      <button className="new-session" onClick={onNew} disabled={busy} aria-describedby={running ? 'sidebar-running' : undefined}><Plus size={17} />新建分析</button>
      {running && <p id="sidebar-running" className="sidebar-running">当前分析正在运行，完成后可开始新的咨询。</p>}
      <div className="nav-heading"><span>咨询记录</span><span>{sessions.length}</span></div>
      <nav className="session-list" aria-label="历史会话">
        {sessions.length === 0 ? <div className="no-history"><MessageSquare size={20} /><p>还没有咨询记录</p><span>开始一次分析，记录会保存在这里。</span></div> : sessions.map(session =>
          <button key={session.id} title={session.title} className={`session-item ${session.id === selectedId ? 'active' : ''}`} onClick={() => onSelect(session.id)} disabled={busy} aria-current={session.id === selectedId ? 'page' : undefined}>
            <MessageSquare size={15} /><span><strong>{session.title}</strong><small><i className={`status-dot ${session.status.toLowerCase()}`} />{session.status === 'COMPLETED' ? '计算已完成' : statusLabels[session.status]}</small></span>
          </button>)}
      </nav>
      <div className="sidebar-bottom"><div className="local-workspace"><span className="workspace-avatar">IF</span><span><strong>我的工作空间</strong><small><ShieldCheck size={12} /> 文件与记录保存在本机</small></span></div></div>
    </aside>
  </>;
}
