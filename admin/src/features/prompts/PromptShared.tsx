import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { TraceError } from '../traces/AccessPanel';
import { timeText } from '../traces/presentation';
import type { RegistrationState, TemplateSummary } from '../../types/prompts';

export const nodeLabels: Record<string, string> = { intent_parser: 'Intent Parser', analysis_planner: 'Analysis Planner', insight_generator: 'Insight Generator' };
export const versionPath = (node: string, id: string) => `/prompts/${encodeURIComponent(node)}/versions/${encodeURIComponent(id)}`;
export const jsonText = (value: unknown) => JSON.stringify(value ?? null, null, 2);
export function offsetValue(value: string | null) { const n = Number(value || 0); return Number.isSafeInteger(n) && n >= 0 && n <= 1_000_000 ? n : 0; }

export function usePromptData<T>(read: (signal: AbortSignal) => Promise<T>, keys: unknown[]) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null); setLoading(true);
    read(controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Callers supply explicit route/filter keys. Request functions are intentionally not dependencies.
  }, [...keys, refresh]);
  return { data, error, loading, reload: () => setRefresh(v => v + 1) };
}

export function RegistryError({ error, retry }: { error: unknown; retry: () => void }) {
  return <TraceError error={error} retry={retry} resource="Prompt 数据" />;
}
export function CopyText({ text, label = '复制内容' }: { text: string; label?: string }) {
  const [state, setState] = useState('');
  return <span className="copy-text"><button className="secondary-button" onClick={async () => {
    try { await navigator.clipboard.writeText(text); setState('已复制'); } catch { setState('复制失败，请手动选择文本。'); }
  }}>{label}</button><span role="status">{state}</span></span>;
}
export function TextBlock({ title, text }: { title: string; text: string }) {
  return <section className="prompt-text-section"><div className="section-heading"><h3>{title}</h3><CopyText text={text} label={'复制' + title} /></div><pre className="prompt-code" tabIndex={0}>{text}</pre></section>;
}
export function RegistrationBadge({ row, state }: { row: TemplateSummary; state: RegistrationState }) {
  return <span className="prompt-version-tags">{state.runtime_registration === 'registered' && state.runtime_snapshot_id === row.template_snapshot_id && <span className="status-badge status-complete">运行时已绑定且登记</span>}
    <span className="status-badge">{state.latest_registered?.template_snapshot_id === row.template_snapshot_id ? '最新登记' : '历史快照'}</span></span>;
}
export function RegistrationNotice({ state }: { state: RegistrationState }) {
  return <p className="trace-notice">{state.runtime_registration === 'registered' ? '当前进程绑定的模板已有登记。' : state.runtime_registration === 'not_registered' ? '当前进程绑定模板尚未登记；不能把最新历史快照视为当前版本。' : '当前进程模板绑定 unknown；不使用最新历史记录代替。'} 最新登记不等于发布状态。</p>;
}
export function Pagination({ total, limit, offset, change, label = '版本' }: { total: number; limit: number; offset: number; change: (n: number) => void; label?: string }) {
  return <nav className="trace-pagination" aria-label={label + '分页'}><span>共 {total} 条{label} · {offset + 1 > total ? 0 : offset + 1}–{Math.min(total, offset + limit)}</span><button className="secondary-button" disabled={!offset} onClick={() => change(Math.max(0, offset - limit))}>上一页</button><button className="secondary-button" disabled={offset + limit >= total} onClick={() => change(offset + limit)}>下一页</button></nav>;
}
export function VersionRows({ rows, state, select, left, right }: { rows: TemplateSummary[]; state: RegistrationState; select?: (side: 'left' | 'right', id: string) => void; left?: string; right?: string }) {
  return <div className="trace-card trace-table-wrap"><table className="trace-table"><thead><tr>{select && <><th>左侧</th><th>右侧</th></>}<th>登记版本</th><th>内容哈希</th><th>登记时间 / 来源</th><th>操作</th></tr></thead><tbody>{rows.map(row => <tr key={row.template_snapshot_id}>
    {select && <><td><input type="radio" name="left-version" aria-label={'设为左侧 ' + row.version} checked={left === row.template_snapshot_id} onChange={() => select('left', row.template_snapshot_id)} /></td><td><input type="radio" name="right-version" aria-label={'设为右侧 ' + row.version} checked={right === row.template_snapshot_id} onChange={() => select('right', row.template_snapshot_id)} /></td></>}
    <td><strong>{row.version}</strong><RegistrationBadge row={row} state={state} /><small className="wrap-code">{row.template_snapshot_id}</small></td><td><code className="wrap-code">{row.content_hash}</code></td><td>{timeText(row.created_at)}<small>Commit：{row.source_commit ?? 'unknown'}</small></td><td><Link className="trace-link" to={versionPath(row.node_id, row.template_snapshot_id)}>查看版本</Link></td>
  </tr>)}</tbody></table></div>;
}
export function PromptRunLinks({ refs }: { refs?: Record<string, string> }) {
  const rows = Object.entries(refs || {}).filter(([node, id]) => nodeLabels[node] && typeof id === 'string' && id);
  return <div className="prompt-run-links"><h3>已记录的 Prompt 模板</h3>{rows.length ? rows.map(([node, id]) => <p key={node}><Link className="trace-link" to={versionPath(node, id)}>{nodeLabels[node]} · 查看本次模板快照</Link></p>) : <p className="muted">Prompt 模板快照 unavailable：历史 Run 未记录引用，不以当前版本补齐。</p>}</div>;
}
