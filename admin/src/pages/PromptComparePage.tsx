import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { promptApi } from '../api/prompts';
import { nodeLabels, offsetValue, Pagination, RegistryError, usePromptData, VersionRows, versionPath } from '../features/prompts/PromptShared';
import type { PromptDiff } from '../types/prompts';

function DiffView({ left, right }: { left: string; right: string }) {
  const state = usePromptData(signal => promptApi.compare(left, right, signal), [left, right]);
  const [key, setKey] = useState('system'); const data = state.data;
  return state.loading ? <p className="trace-message" role="status">正在比较已保存的模板文本…</p> : state.error ? <RegistryError error={state.error} retry={state.reload} /> : data ? <DiffContent data={data} sectionKey={key} select={setKey} /> : null;
}
function DiffContent({ data, sectionKey, select }: { data: PromptDiff; sectionKey: string; select: (v: string) => void }) {
  const section = data.sections.find(s => s.key === sectionKey) || data.sections[0];
  return <section className="trace-card"><h2>文本 Diff</h2><p className="muted">{data.notice}</p>
    <div className="comparison-columns"><div><strong>左侧 · {data.left.version}</strong><code className="artifact-hash">{data.left.content_hash}</code><Link className="trace-link" to={versionPath(data.left.node_id, data.left.template_snapshot_id)}>左侧版本详情</Link><p className="muted">Commit：{data.left.source_commit ?? 'unknown'}<br />{data.left.change_summary}</p></div><div><strong>右侧 · {data.right.version}</strong><code className="artifact-hash">{data.right.content_hash}</code><Link className="trace-link" to={versionPath(data.right.node_id, data.right.template_snapshot_id)}>右侧版本详情</Link><p className="muted">Commit：{data.right.source_commit ?? 'unknown'}<br />{data.right.change_summary}</p></div></div>
    <p>内容哈希：{data.content_hash_equal ? '相同' : '不同'}</p><label className="prompt-section-select">比较片段<select aria-label="比较片段" value={section?.key || ''} onChange={e => select(e.target.value)}>{data.sections.map(s => <option key={s.key} value={s.key}>{s.label} · {s.availability !== 'available' ? 'unavailable' : s.changed ? '有变化' : '相同'}</option>)}</select></label>
    {section && (section.availability !== 'available' ? <p className="unavailable-note">一侧未登记该片段，内容 unavailable，不据此猜测原文。</p> : <><p className="muted">{section.changed ? '红色为左侧原文，绿色为右侧原文；保留行号与原始换行。' : '该片段文本完全相同。'}</p><div className="prompt-diff-wrap" tabIndex={0}><table className="prompt-diff" aria-label={section.label + '文本对比'}><thead><tr><th colSpan={2}>左侧原文</th><th colSpan={2}>右侧原文</th></tr></thead><tbody>{section.lines.map((line, i) => <tr key={i} className={'diff-' + line.kind}><td>{line.left_number}</td><td className={line.kind !== 'equal' && line.left !== null ? 'diff-removed' : ''}><pre>{line.left ?? ''}</pre></td><td>{line.right_number}</td><td className={line.kind !== 'equal' && line.right !== null ? 'diff-added' : ''}><pre>{line.right ?? ''}</pre></td></tr>)}</tbody></table></div></>)}
  </section>;
}
export function PromptComparePage() {
  const [params, setParams] = useSearchParams(); const node = params.get('node') || 'intent_parser', left = params.get('left') || '', right = params.get('right') || '', offset = offsetValue(params.get('offset'));
  const history = usePromptData(signal => promptApi.history(node, offset, signal), [node, offset]);
  return <><Link className="trace-link" to="/prompts">返回 Prompt 列表</Link><div className="trace-heading"><div><span className="eyebrow">PROMPT DIFF · SAVED CONTENT ONLY</span><h1>版本详情与 Diff</h1><p>选择同一节点两个已登记快照，左右选择与分页保存在 URL。</p></div></div>
    <section className="trace-card prompt-filter"><label>比较节点<select value={node} onChange={e => setParams({ node: e.target.value })}>{Object.entries(nodeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></section>
    {history.loading ? <p role="status">正在读取可比较版本…</p> : history.error ? <RegistryError error={history.error} retry={history.reload} /> : history.data && <>
      {history.data.total < 2 && <p className="trace-notice">{history.data.total ? '只有一个真实版本，暂无两个快照可比较。' : '尚无已登记版本，不生成虚假 Diff。'}</p>}
      <p className="muted">左侧：<code>{left || '未选择'}</code><br />右侧：<code>{right || '未选择'}</code></p>
      {history.data.items.length > 0 && <VersionRows rows={history.data.items} state={history.data} left={left} right={right} select={(side, id) => { const next = new URLSearchParams(params); next.set('node', node); next.set(side, id); setParams(next); }} />}
      <Pagination {...history.data} label="版本" change={next => { const query = new URLSearchParams(params); query.set('node', node); query.set('offset', String(next)); setParams(query); }} />
    </>}
    {left && right && (left === right ? <p className="trace-notice trace-warning">请选择两个不同快照。</p> : <DiffView key={left + ':' + right} left={left} right={right} />)}
  </>;
}
