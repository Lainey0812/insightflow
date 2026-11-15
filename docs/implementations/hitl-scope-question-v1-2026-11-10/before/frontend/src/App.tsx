import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle, Menu, RefreshCw, X } from 'lucide-react';
import { api, ApiError } from './api/client';
import type { AnalysisMode, Session, SessionSummary } from './types/contracts';
import { SessionSidebar } from './components/SessionSidebar';
import { Welcome } from './components/Welcome';
import { MessageComposer } from './components/MessageComposer';
import { MessageList } from './components/MessageList';
import { PlanImport } from './components/PlanImport';
import { WorkflowProgress } from './components/WorkflowProgress';
import { activeStatuses, currentReportGeneration, isWorkflowRunning } from './workflow/presentation';
import './chat-workspace.css';

const STORAGE_KEY = 'insightflow.session';
export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [headerRow, setHeaderRow] = useState('1');
  const [mode, setMode] = useState<AnalysisMode>('goal_driven');
  const [busy, setBusy] = useState(false);
  const actionPending = useRef(false);
  const [initializing, setInitializing] = useState(true);
  const [pending, setPending] = useState('');
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking');
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const sidebarToggle = useRef<HTMLButtonElement>(null);
  const sidebarWasOpen = useRef(false);
  useEffect(() => {
    if (sidebarWasOpen.current && !sidebarOpen) sidebarToggle.current?.focus();
    sidebarWasOpen.current = sidebarOpen;
  }, [sidebarOpen]);
  useEffect(() => {
    const desktop = window.matchMedia?.('(min-width: 851px)');
    if (!desktop) return;
    const closeDrawer = () => { if (desktop.matches) setSidebarOpen(false); };
    desktop.addEventListener('change', closeDrawer);
    return () => desktop.removeEventListener('change', closeDrawer);
  }, []);

  async function checkHealth() {
    setHealth('checking');
    try { const result = await api.health(); setHealth(result.status === 'ok' ? 'online' : 'offline'); }
    catch { setHealth('offline'); }
  }
  async function refreshList() { setSessions(await api.list()); }
  function selectSession(next: Session | null) {
    setSession(current => current && next && current.id === next.id && current.revision > next.revision ? current : next);
    if (next) localStorage.setItem(STORAGE_KEY, next.id); else localStorage.removeItem(STORAGE_KEY);
  }
  useEffect(() => {
    let alive = true;
    async function initialize() {
      void checkHealth();
      try {
        const list = await api.list();
        if (!alive) return;
        setSessions(list);
        const id = localStorage.getItem(STORAGE_KEY);
        if (id && list.some(s => s.id === id)) {
          const current = await api.session(id);
          if (alive) setSession(current);
        } else localStorage.removeItem(STORAGE_KEY);
      } catch (err) { if (alive) setError(err instanceof Error ? err.message : '加载失败。'); }
      finally { if (alive) setInitializing(false); }
    }
    void initialize();
    return () => { alive = false; };
  }, []);

  const currentReport = currentReportGeneration(session);
  const reportPending = currentReport?.status === 'queued' || currentReport?.status === 'generating';
  const running = isWorkflowRunning(session);
  useEffect(() => {
    if (session?.workflow_kind !== 'real_v1' || (!activeStatuses.includes(session.status) && !reportPending)) return;
    let alive = true;
    let polling = false;
    const id = session.id;
    const previous = session.status;
    const timer = window.setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await api.session(id);
        if (alive) {
          setSession(current => current?.id === id && current.revision <= next.revision ? next : current);
          if (next.status !== previous) void refreshList().catch(() => {});
        }
      } catch (err) { if (alive) setError(err instanceof Error ? err.message : '读取流程状态失败，请刷新重试。'); }
      finally { polling = false; }
    }, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [session?.id, session?.status, session?.workflow_kind, reportPending]);

  async function perform(label: string, action: () => Promise<Session>, clearDraft = false) {
    if (actionPending.current) return;
    actionPending.current = true;
    setBusy(true); setPending(label); setError('');
    try {
      const next = await action(); selectSession(next);
      if (clearDraft) { setText(''); setFile(null); }
      try { await refreshList(); } catch { setError('会话已保存，但历史列表刷新失败，请稍后刷新页面。'); }
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请重试。');
      if (session && ((err instanceof ApiError && err.status === 409) || session.review_status)) {
        try { selectSession(await api.session(session.id)); } catch { /* Keep last visible state. */ }
      }
    } finally { actionPending.current = false; setBusy(false); setPending(''); }
  }
  function newSession() { if (actionPending.current || running) return; selectSession(null); setText(''); setFile(null); setHeaderRow('1'); setMode('goal_driven'); setError(''); setSidebarOpen(false); }
  function chooseFile(next: File | null) {
    if (actionPending.current || running) return;
    if (next && !/\.(csv|xlsx)$/i.test(next.name)) { setError('请选择 CSV 或 XLSX 文件。'); return; }
    if (next && (next.size === 0 || next.size > 10 * 1024 * 1024)) { setError('文件不能为空，且不能超过 10 MB。'); return; }
    setFile(next); setHeaderRow('1'); setError('');
  }
  function submit() {
    if (actionPending.current || initializing || running || locked || (!text.trim() && mode !== 'exploratory')) return;
    if (session?.status === 'WAITING_FOR_CLARIFICATION') void perform('正在结合补充信息理解分析需求…', () => api.clarify(session, text), true);
    else if (session) void perform('正在生成新的计划版本…', () => api.revise(session, text), true);
    else if (file && Number.isInteger(Number(headerRow)) && Number(headerRow) >= 1 && Number(headerRow) <= 100001)
      void perform('正在计算真实数据画像并理解分析需求…', () => api.create(file, text, mode, Number(headerRow)), true);
  }
  function confirm(warnings: string[] = []) {
    if (!session || running || actionPending.current) return;
    if (session.review_plan) {
      void perform('正在保存审批并执行真实数据…', async () => {
        const approved = session.review_status === 'approved' ? session : await api.approveReal(session, warnings);
        selectSession(approved);
        await api.executeReal(approved);
        return api.session(approved.id);
      });
      return;
    }
    void perform('计划已确认，正在执行示例计算并生成报告…', async () => {
      const approved = session.status === 'APPROVED' ? session : await api.approve(session);
      selectSession(approved);
      return api.execute(approved);
    });
  }
  const realWorkflow = !session || session.workflow_kind === 'real_v1';
  const locked = !!session && !(realWorkflow && session.status === 'WAITING_FOR_CLARIFICATION') && (!!session.review_status || !['WAITING_FOR_CLARIFICATION', 'AWAITING_APPROVAL', 'APPROVED'].includes(session.status));

  const lockReason = session?.status === 'AWAITING_APPROVAL' ? '请先确认对话中的分析方案。' : session?.status === 'APPROVED' ? '方案已确认，请在上方开始分析。' : '本次咨询已保存，可开始新的分析。';
  return <div className="app-shell chat-shell">
    <SessionSidebar sessions={sessions} selectedId={session?.id} busy={busy || initializing || running} running={running} open={sidebarOpen} onNew={newSession} onClose={() => setSidebarOpen(false)} onSelect={id => { if (actionPending.current || running) return; setSidebarOpen(false); setText(''); setFile(null); void perform('正在恢复会话…', () => api.session(id)); }} />
    <main className="workspace" inert={sidebarOpen ? true : undefined}>
      <header className="workspace-header"><div className="breadcrumbs"><button ref={sidebarToggle} className="icon-button sidebar-toggle" aria-label="打开会话列表" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Menu size={19} /></button><strong>{session?.title ?? '新的分析'}</strong><span className="workspace-purpose">数据分析助手</span></div><div className="header-tools"><button className={`health-indicator ${health}`} onClick={() => { void checkHealth(); void refreshList().catch(() => setError('会话列表加载失败，请检查后端服务。')); }} title="重新检查后端连接" aria-label={`后端${health === 'online' ? '已连接' : health === 'offline' ? '未连接' : '检查中'}，点击重试`}><i />{health === 'online' ? '服务已连接' : health === 'offline' ? '服务未连接' : '连接中'}{health === 'offline' && <RefreshCw size={12} />}</button></div></header>
      {session?.workflow_kind === 'real_v1' && <WorkflowProgress session={session} busy={busy} onRetry={() => void perform('正在按保存检查点重试…', () => api.retryPreparation(session))}/>}
      <div className={`conversation ${session ? 'has-session' : ''}`}>
        {initializing ? <div className="initial-loading"><LoaderCircle size={22} className="spin" />正在打开工作空间…</div> : session ? <><MessageList onBasisSaved={next => {selectSession(next); void refreshList().catch(() => setError('会话列表刷新失败。'));}} onReportChange={() => void api.session(session.id).then(next => setSession(current => current?.id === next.id && current.revision <= next.revision ? next : current)).catch(() => setError('报告状态刷新失败，请稍后刷新会话。'))} session={session} busy={busy || running} pending={pending} onRestart={newSession} onConfirm={confirm} onRemove={id => { if (!running) void perform('正在更新计划版本…', () => api.revise(session, '', [id])); }} />{session.workflow_kind !== 'real_v1' && session.review_status && !session.review_plan && <PlanImport key={session.id} session={session} busy={busy} onSave={action => void perform('正在保存并校验真实计划…', action)}/>}</> : <div className="welcome-wrap"><Welcome disabled={busy || initializing} onSuggestion={(value, exploratory) => { if (actionPending.current) return; setText(value); setMode(exploratory ? 'exploratory' : 'goal_driven'); }} />{busy && <div className="pending-message" role="status"><LoaderCircle size={17} className="spin" />{pending}</div>}</div>}
      </div>
      <div className="composer-container">{error && <div className="error-banner" role="alert"><AlertCircle size={17} /><span>{error}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setError('')}><X size={14} /></button></div>}<MessageComposer realWorkflow={realWorkflow} realReview={!session || !!session.review_status} running={running} lockReason={lockReason} text={text} file={file} headerRow={headerRow} onHeaderRow={setHeaderRow} mode={session?.analysis_mode ?? mode} busy={busy || initializing || running} hasSession={!!session} locked={locked} clarifying={session?.status === 'WAITING_FOR_CLARIFICATION'} legacyMockProfile={session?.profile?.provenance.source === 'mock'} onText={setText} onFile={chooseFile} onMode={setMode} onSubmit={submit} onNew={newSession} /></div>
    </main>
  </div>;
}
