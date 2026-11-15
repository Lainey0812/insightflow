import { Link, useSearchParams } from 'react-router-dom';
import { promptApi } from '../api/prompts';
import { nodeLabels, RegistrationNotice, RegistryError, usePromptData, versionPath } from '../features/prompts/PromptShared';
import { timeText } from '../features/traces/presentation';

export function PromptsPage() {
  const [params, setParams] = useSearchParams(); const node = params.get('node') || '';
  const state = usePromptData(signal => promptApi.catalog(node, signal), [node]);
  return <>
    <div className="trace-heading"><div><span className="eyebrow">PROMPT REGISTRY · READ ONLY</span><h1>Prompt 模板</h1><p>查看三个节点实际登记的固定指令与组合版本。</p></div><button className="secondary-button" onClick={state.reload} disabled={state.loading}>刷新模板</button></div>
    <section className="trace-card prompt-filter"><label>LLM 节点<select value={node} onChange={e => setParams(e.target.value ? { node: e.target.value } : {})}><option value="">全部节点</option>{Object.entries(nodeLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><Link className="trace-link" to="/prompts/versions">选择版本进行 Diff</Link></section>
    {state.loading ? <p className="trace-message" role="status">正在读取已登记模板…</p> : state.error ? <RegistryError error={state.error} retry={state.reload} /> : state.data && <>
      <p className="muted">{state.data.notice} 动态用户请求和 Evidence ID 不作为模板版本。</p>
      <div className="prompt-catalog">{state.data.items.map(item => <article className="trace-card prompt-node-card" key={item.prompt_id}>
        <span className="eyebrow">{item.node_id}</span><h2>{item.label}</h2><p className="prompt-count">{item.version_count} <span>个真实登记快照</span></p>
        {item.latest_registered ? <><strong>{item.latest_registered.version}</strong><p><code className="wrap-code">{item.latest_registered.content_hash}</code></p><p className="muted">登记于 {timeText(item.latest_registered.created_at)}<br />Commit：{item.latest_registered.source_commit ?? 'unknown'}</p><RegistrationNotice state={item} />
          <Link className="trace-link" to={versionPath(item.node_id, item.latest_registered.template_snapshot_id)}>查看最新登记</Link></> : <div className="unavailable-note"><strong>尚无已登记快照</strong><p>没有可展示的历史内容，不从当前代码或旧版本号补造。</p></div>}
        <p><Link className="trace-link" to={'/prompts/' + encodeURIComponent(item.prompt_id)}>查看版本历史</Link></p>
      </article>)}</div>
      {!state.data.items.length && <section className="trace-message"><h2>没有匹配的 Prompt 节点</h2><p>请调整节点筛选。</p></section>}
    </>}
  </>;
}
