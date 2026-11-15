import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { badCaseApi, writeErrorText } from '../api/badCases';
import { badCaseStatuses } from '../types/badCases';
import type { BadCase, BadCaseStatus } from '../types/badCases';
import { BadCaseStatusBadge, SeverityBadge, categoryLabels, statusLabels } from '../features/badCases/BadCaseShared';
import { BusinessBadge, FailureCard, QualityCard } from '../features/workflows/WorkflowShared';
import { TraceError } from '../features/traces/AccessPanel';
import { StatusBadge } from '../features/traces/TraceShared';
import { durationText, timeText, valueText } from '../features/traces/presentation';

const refLabels: Record<string,string> = { session_id:'会话', dataset_id:'数据集', dataset_version:'数据集版本', plan_id:'计划', plan_version:'计划版本', validation_version:'校验版本', approval_id:'审批', execution_id:'执行', report_attempt:'报告尝试' };

function StatusForm({ item, onSaved }: { item: BadCase; onSaved: (value: BadCase) => void }) {
  const [saving, setSaving] = useState(false), [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget, f = new FormData(form), text = (k: string) => String(f.get(k) || '').trim();
    setSaving(true); setError('');
    try { onSaved(await badCaseApi.transition(item.case_id, { status: text('status') as BadCaseStatus, note: text('note'), annotator: text('annotator'), expected_sequence: item.sequence }, text('token'))); form.reset(); }
    catch (e) { setError(writeErrorText(e)); }
    finally { setSaving(false); }
  }
  return <form className="bc-form" onSubmit={submit} aria-label="更新处理状态" key={item.sequence}>
    <div className="bc-form-row">
      <label>新状态<select name="status" defaultValue={item.status}>{badCaseStatuses.map(s => <option key={s} value={s}>{statusLabels[s]}</option>)}</select></label>
      <label>操作人<input name="annotator" required maxLength={40}/></label>
      <label>标注凭证<input name="token" type="password" autoComplete="off" placeholder="本机测试模式可留空"/></label>
    </div>
    <label>备注<textarea name="note" maxLength={2000} rows={2} placeholder="复核结论、修复版本等；状态不变时必填"/></label>
    {error && <p className="bc-error" role="alert">{error}</p>}
    <div className="bc-actions"><button className="primary-button" type="submit" disabled={saving}>{saving ? '正在提交…' : '追加记录'}</button></div>
  </form>;
}

export function BadCaseDetailPage() {
  const { caseId = '' } = useParams();
  const [item, setItem] = useState<BadCase | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => { const c = new AbortController(); setItem(null); setError(null); setLoading(true);
    badCaseApi.get(caseId, c.signal).then(v => { if (!c.signal.aborted) setItem(v); }).catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort(); }, [caseId, refresh]);
  const evidence = item?.evidence;
  return <div className="wf-page"><Link className="wf-back" to="/bad-cases"><ChevronLeft size={15}/>Bad Case 列表</Link>
    <header className="wf-heading"><div><h1>{item?.title || 'Bad Case 详情'}</h1><p className="wf-id">{caseId}</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15}/>手动刷新</button></header>
    {loading && <p role="status">正在读取 Bad Case…</p>}{error != null && <TraceError error={error} resource="Bad Case" retry={() => setRefresh(v => v + 1)}/>}
    {item && evidence && <>
      {!item.evidence_intact && <p className="bc-error" role="alert">冻结证据与保存时的哈希不一致，证据可能被改动，请勿据此判断。</p>}
      <section className="bc-summary"><div className="bc-tags"><BadCaseStatusBadge status={item.status}/><SeverityBadge severity={item.severity}/><span>{categoryLabels[item.category]}</span></div>
        <dl className="wf-node-facts">
          <div><dt>Workflow</dt><dd><Link className="wf-link wf-id" to={'/traces/workflows/' + encodeURIComponent(item.workflow_id)}>{item.workflow_id}</Link></dd></div>
          <div><dt>问题节点</dt><dd>{item.node_name ? <>{item.node_name} <code className="wf-subid">{item.span_id}</code></> : '整条 Workflow'}</dd></div>
          <div><dt>标注人</dt><dd>{item.created_by}</dd></div><div><dt>保存时间</dt><dd>{timeText(item.created_at)}</dd></div>
        </dl>
        <h3>观察到的问题</h3><p className="bc-text">{item.observed}</p>
        <h3>期望结果</h3><p className="bc-text">{item.expected || <span className="muted">未填写</span>}</p></section>
      <section className="bc-panel" aria-labelledby="history-heading"><header><h2 id="history-heading">处理记录</h2></header>
        <ol className="bc-history">{item.events.map(e => <li key={e.event_id}><time>{timeText(e.created_at)}</time><BadCaseStatusBadge status={e.status}/><strong>{e.annotator}</strong><span>{e.kind === 'created' ? '创建' : e.kind === 'status_changed' ? '更新状态' : '补充备注'}</span>{e.note && <p>{e.note}</p>}</li>)}</ol>
        <StatusForm item={item} onSaved={setItem}/><p className="muted">记录只追加，不修改或删除已有记录。</p></section>
      <section className="bc-panel" aria-labelledby="evidence-heading"><header><h2 id="evidence-heading">冻结证据（保存时）</h2><BusinessBadge status={evidence.business_lifecycle.status}/></header>
        <p className="muted">{item.evidence_notice}</p>
        <dl className="wf-refs">{Object.entries(evidence.replay_refs).filter(([k]) => k !== 'llm_call_ids').map(([k, v]) => <div key={k}><dt>{refLabels[k] || k}</dt><dd><code>{v == null ? '未关联' : valueText(v)}</code></dd></div>)}</dl>
        <p className="muted">证据 SHA-256：<code>{item.evidence_sha256}</code></p></section>
      {evidence.failure && <FailureCard failure={evidence.failure}/>}
      {evidence.quality && <QualityCard quality={evidence.quality}/>}
      <section className="bc-panel" aria-labelledby="evidence-nodes-heading"><header><h2 id="evidence-nodes-heading">节点（保存时 {evidence.nodes.length} 个）</h2></header>
        <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>节点</th><th>状态</th><th>错误代码</th><th>耗时</th><th>模型调用</th></tr></thead><tbody>
          {evidence.nodes.map(n => <tr key={n.span_id} className={n.span_id === item.span_id ? 'bc-marked' : undefined}><td>{n.name}<code className="wf-subid">{n.span_id}</code></td><td><StatusBadge status={n.status as never}/></td><td>{n.error_code ? <code>{n.error_code}</code> : '—'}</td><td>{durationText(n.duration_ms)}</td>
            <td>{evidence.llm_calls.filter(c => c.span_id === n.span_id).map(c => <Link key={c.call_id} className="wf-link wf-id" to={'/prompts/calls/' + encodeURIComponent(c.call_id)}>{c.status}{c.retry_index > 0 ? ` · 重试 #${c.retry_index}` : ''}</Link>)}</td></tr>)}
        </tbody></table></div></section>
    </>}
  </div>;
}
