import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { traceApi } from '../api/traces';
import type { CompareCheck, Metadata, RunComparison, SavedArtifact, TraceSpan } from '../types/traces';
import { TraceError } from '../features/traces/AccessPanel';
import { ManifestView, StatusBadge } from '../features/traces/TraceShared';
import { durationText, nodeLabels, valueText } from '../features/traces/presentation';

const checkLabels: Record<string, string> = { dataset: '数据集与解析选项', profile: '数据画像', user_goal: '用户分析目标', intent: '结构化意图', approved_plan: '已批准计划快照', execution: '执行结果', comparison_scope: '比较范围' };
const verdicts = { comparable: '可比较 · 关键输入已验证相同', partially_comparable: '部分可比较 · 存在差异或缺口', unknown: '无法判断可比性 · 快照不足' };
const states = { same: '已验证相同', different: '已知不同', unknown: 'unknown · 信息不足' };
function text(value: unknown) { return value === null || value === undefined ? 'unknown' : valueText(value); }
function Checks({ items }: { items: CompareCheck[] }) {
  return <div className="trace-table-wrap"><table className="trace-table comparison-table"><thead><tr><th>条件</th><th>左侧 Run</th><th>右侧 Run</th><th>核验</th></tr></thead><tbody>{items.map(item => <tr key={item.key}><th>{checkLabels[item.key] || item.key}{item.basis && <small>{item.basis}</small>}</th><td><code>{text(item.left)}</code></td><td><code>{text(item.right)}</code></td><td className={'comparison-' + item.status}>{states[item.status]}</td></tr>)}</tbody></table></div>;
}
function SpanCell({ span }: { span?: TraceSpan | null }) {
  return span ? <><StatusBadge status={span.status} /><p>{durationText(span.duration_ms)}</p><code>{span.error_code || '无已记录错误'}</code><p><Link className="trace-link" to={'/traces/' + encodeURIComponent(span.run_id) + '?span=' + encodeURIComponent(span.span_id)}>打开原始节点</Link></p></> : <span className="muted">本侧没有匹配节点</span>;
}
function Artifact({ value }: { value?: SavedArtifact }) {
  if (!value || value.availability !== 'available') return <p className="muted">unknown · 未采集或不可读取；不使用另一次尝试补齐。</p>;
  return <><p>{value.source === 'runtime_controlled_snapshot' ? '运行时保存的受控投影' : '已保存不可变报告的受控投影（非运行时快照）'}</p><code className="artifact-hash">SHA256 {value.content_sha256 || 'unknown'}</code>
    <pre className="controlled-projection">{JSON.stringify(value.projection, null, 2)}</pre></>;
}
function Diagnostics({ items }: { items: RunComparison['diagnostics']['left'] }) {
  return items.length ? <ul className="diagnostic-list">{items.map(item => <li key={item.sequence}><strong>#{item.sequence} {item.event_type}</strong><dl>{Object.entries(item.payload).filter(([k]) => ['rule_ids', 'error_code', 'candidate_index', 'candidate_status', 'accepted_count', 'rejected_count', 'evidence_refs', 'provider', 'model', 'inputs_match'].includes(k)).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{text(v)}</dd></div>)}</dl></li>)}</ul> : <p>unknown · 未采集诊断事件</p>;
}
export function TraceComparisonPage() {
  const [params, setParams] = useSearchParams(); const left = params.get('left') || '', right = params.get('right') || '';
  const [data, setData] = useState<RunComparison | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false), [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh(v => v + 1);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null); setLoading(false);
    if (!left || !right || left === right) return;
    setLoading(true);
    traceApi.comparison(left, right, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [left, right, refresh]);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    setParams({ left: String(form.get('left') || '').trim(), right: String(form.get('right') || '').trim() });
  }
  return <>
    <Link className="trace-link" to="/traces">返回运行列表</Link>
    <div className="trace-heading"><div><span className="eyebrow">RUN COMPARISON</span><h1>两次运行对比</h1><p>核对已保存的输入、版本、节点和结果；差异不代表因果关系。</p></div><button className="secondary-button" onClick={reload} disabled={loading}>手动刷新</button></div>
    <form className="trace-card comparison-form" key={left + ':' + right} onSubmit={submit} aria-label="选择运行对比">
      <label>左侧 Run ID<input name="left" required maxLength={160} defaultValue={left} /></label><label>右侧 Run ID<input name="right" required maxLength={160} defaultValue={right} /></label><button className="primary-button">开始对比</button>
    </form>
    {left && right && left === right && <p role="alert">请选择两次不同运行。</p>}
    {loading && <p role="status">正在核对两次历史运行…</p>}{error ? <TraceError error={error} retry={reload} /> : null}
    {!left || !right ? <p className="trace-message">从运行列表勾选两条记录，或输入两个历史 Run ID。</p> : null}
    {data && <>
      <section className="trace-card"><h2>{verdicts[data.comparability.status]}</h2><p className="trace-notice trace-warning">{data.comparability.notice}</p>{data.live && <p>至少一次运行仍在进行中，此页仅展示本次读取时已保存的观察。请完成后手动刷新。</p>}
        <Checks items={data.comparability.checks} /><details><summary>关联引用（相同引用不等于已验证相同输入）</summary><Checks items={data.comparability.bindings} /></details>
      </section>
      <section className="trace-card"><h2>整体状态</h2><div className="comparison-columns">{(['left', 'right'] as const).map(side => <div key={side}><h3>{side === 'left' ? '左侧' : '右侧'} Run</h3><Link className="trace-link wrap-code" to={'/traces/' + encodeURIComponent(data[side].run_id)}>{data[side].run_id}</Link><p><StatusBadge status={data[side].status} /></p><p>整体耗时：{durationText(data[side].duration_ms)} · Run 尝试：{text(data[side].attempt)}</p><code>{data[side].error_code || '无已记录错误'}</code>{data[side].integrity === 'incomplete' && <p className="trace-danger">存在追踪缺口</p>}</div>)}</div></section>
      <section className="trace-card"><h2>版本与模型</h2><Checks items={[...data.comparability.versions, ...data.comparability.models, data.comparability.git]} /><details><summary>运行时源码文件差异</summary><Checks items={data.source_files || []} /></details><p className="muted">模型字段为 Provider 提供的标识；当前兼容适配器使用请求模型名，供应商实际模型版本未采集。版本或配置变化不能单独解释结果变化。历史 unknown 不用当前值补齐。</p></section>
      <section className="trace-card"><h2>节点对齐</h2><p className="muted">按稳定节点身份与节点内重试序号对齐。legacy_unique_path 为旧记录唯一祖先路径匹配；歧义节点保留未匹配。</p><div className="trace-table-wrap"><table className="trace-table"><thead><tr><th>节点 / 匹配依据</th><th>左侧</th><th>右侧</th></tr></thead><tbody>{data.spans.map((row, i) => <tr key={`${row.left?.span_id}:${row.right?.span_id}:${i}`}><th>{nodeLabels[row.node_key] || row.node_key}<small>{row.node_key} · 节点尝试 {text(row.node_attempt)}</small><small>{row.match_basis}</small></th><td><SpanCell span={row.left} /></td><td><SpanCell span={row.right} /></td></tr>)}</tbody></table></div></section>
      <section className="trace-card"><h2>证据、模型输出与报告</h2><p className="muted">数值及引用来自保存内容；类别和自由文本仅显示哈希，不恢复原文。完整 LLM 文本未保留。哈希不同只表示保存内容不同。</p>{(['evidence', 'llm_output', 'report'] as const).map(kind => <details key={kind} className="artifact-section"><summary>{({ evidence: 'Evidence', llm_output: 'LLM 输出（受控候选及原文哈希）', report: 'AnalysisReport' } as Metadata)[kind] as string}</summary><div className="comparison-columns">{(['left', 'right'] as const).map(side => <div key={side}><h3>{side === 'left' ? '左侧' : '右侧'}</h3><Artifact value={data.artifacts[side][kind]} /></div>)}</div></details>)}</section>
      <section className="trace-card"><h2>拒绝规则与诊断</h2><div className="comparison-columns"><div><h3>左侧</h3><Diagnostics items={data.diagnostics.left} /></div><div><h3>右侧</h3><Diagnostics items={data.diagnostics.right} /></div></div></section>
      <div className="comparison-columns"><ManifestView manifest={data.left.manifest} /><ManifestView manifest={data.right.manifest} /></div>
    </>}
  </>;
}
