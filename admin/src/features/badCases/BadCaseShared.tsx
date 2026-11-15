import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Bug } from 'lucide-react';
import { badCaseApi, writeErrorText } from '../../api/badCases';
import { badCaseCategories, badCaseSeverities } from '../../types/badCases';
import type { BadCaseCategory, BadCaseSeverity, BadCaseStatus, BadCaseSummary } from '../../types/badCases';
import type { WorkflowView } from '../../types/workflows';
import { timeText } from '../traces/presentation';

export const categoryLabels: Record<BadCaseCategory,string> = { understanding:'需求理解偏差', planning:'规划不合理', calculation:'计算结果错误', insight:'结论与数据不符', report:'报告表达问题', failure:'运行失败', other:'其他' };
export const severityLabels: Record<BadCaseSeverity,string> = { high:'高', medium:'中', low:'低' };
export const statusLabels: Record<BadCaseStatus,string> = { open:'待处理', confirmed:'已确认', fixed:'已修复', wont_fix:'不处理', invalid:'误报',in_progress:'处理中',pending_verification:'待验证' };
export function BadCaseStatusBadge({ status }: { status: BadCaseStatus }) { return <span className={`bc-status bc-status-${status}`}>{statusLabels[status]}</span>; }
export function SeverityBadge({ severity }: { severity: BadCaseSeverity }) { return <span className={`bc-severity bc-severity-${severity}`}>{severityLabels[severity]}</span>; }

function BadCaseForm({ view, onCancel }: { view: WorkflowView; onCancel: () => void }) {
  const navigate = useNavigate();
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  const nodes = view.trace?.nodes || [];
  const defaultCategory: BadCaseCategory = view.failure ? 'failure' : 'insight';
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget), text = (k: string) => String(f.get(k) || '').trim();
    setSaving(true); setError('');
    try {
      const saved = await badCaseApi.create({ workflow_id: view.workflow_id, span_id: text('span_id') || null, category: text('category') as BadCaseCategory,
        severity: text('severity') as BadCaseSeverity, title: text('title'), observed: text('observed'), expected: text('expected'), annotator: text('annotator') }, text('token'));
      navigate('/bad-cases/' + encodeURIComponent(saved.case_id));
    } catch (e) { setError(writeErrorText(e)); setSaving(false); }
  }
  return <form className="bc-form" onSubmit={submit} aria-label="存为 Bad Case">
    <div className="bc-form-row">
      <label>问题类型<select name="category" defaultValue={defaultCategory}>{badCaseCategories.map(c => <option key={c} value={c}>{categoryLabels[c]}</option>)}</select></label>
      <label>严重程度<select name="severity" defaultValue="medium">{badCaseSeverities.map(s => <option key={s} value={s}>{severityLabels[s]}</option>)}</select></label>
      <label>问题节点<select name="span_id" defaultValue={view.failure?.span_id || ''}><option value="">整条 Workflow</option>{nodes.map(n => <option key={n.span_id} value={n.span_id}>{n.name} · {n.status}</option>)}</select></label>
    </div>
    <label>标题<input name="title" required maxLength={80} placeholder="一句话描述问题"/></label>
    <label>观察到的问题<textarea name="observed" required maxLength={2000} rows={3} placeholder="具体哪里不对；不要粘贴原始数据或敏感内容"/></label>
    <label>期望结果<textarea name="expected" maxLength={2000} rows={2} placeholder="正确的结果应该是什么（可选，后续用于回归判定）"/></label>
    <div className="bc-form-row">
      <label>标注人<input name="annotator" required maxLength={40}/></label>
      <label>标注凭证<input name="token" type="password" autoComplete="off" placeholder="本机测试模式可留空"/></label>
    </div>
    {error && <p className="bc-error" role="alert">{error}</p>}
    <p className="muted">保存时冻结当前的业务状态、节点元数据、失败定位、质量信号与模型调用引用；不复制原始数据、需求原文或模型文本。</p>
    <div className="bc-actions"><button className="primary-button" type="submit" disabled={saving}>{saving ? '正在保存…' : '保存 Bad Case'}</button><button className="secondary-button" type="button" onClick={onCancel}>取消</button></div>
  </form>;
}

export function WorkflowBadCases({ view }: { view: WorkflowView }) {
  const [items, setItems] = useState<BadCaseSummary[] | null>(null), [error, setError] = useState(false), [open, setOpen] = useState(false);
  useEffect(() => { const c = new AbortController(); setItems(null); setError(false);
    badCaseApi.list(new URLSearchParams({ workflow_id: view.workflow_id, limit: '100' }).toString(), c.signal).then(p => { if (!c.signal.aborted) setItems(p.items); }).catch(() => { if (!c.signal.aborted) setError(true); });
    return () => c.abort(); }, [view.workflow_id]);
  return <section className="bc-panel" aria-labelledby="bad-case-heading"><header><h2 id="bad-case-heading">人工标注</h2>
    {!open && <button className="secondary-button" onClick={() => setOpen(true)}><Bug size={15}/>存为 Bad Case</button>}</header>
    {error ? <p className="muted">暂时无法读取已有标注。</p> : items === null ? <p className="muted">正在读取已有标注…</p>
      : items.length ? <ul className="bc-mini-list">{items.map(i => <li key={i.case_id}><BadCaseStatusBadge status={i.status}/><SeverityBadge severity={i.severity}/><Link className="wf-link" to={'/bad-cases/' + encodeURIComponent(i.case_id)}>{i.title}</Link><span>{categoryLabels[i.category]}{i.node_name ? ' · ' + i.node_name : ''} · {i.created_by} · {timeText(i.created_at)}</span></li>)}</ul>
      : <p className="muted">这条 Workflow 还没有人工标注。</p>}
    {open && <BadCaseForm view={view} onCancel={() => setOpen(false)}/>}
  </section>;
}
