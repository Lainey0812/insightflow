import { Link, useParams, useSearchParams } from 'react-router-dom';
import { promptApi } from '../api/prompts';
import { nodeLabels, offsetValue, Pagination, RegistrationNotice, RegistryError, usePromptData, VersionRows } from '../features/prompts/PromptShared';

export function PromptHistoryPage() {
  const { promptId = '' } = useParams(); const [params, setParams] = useSearchParams(); const offset = offsetValue(params.get('offset'));
  const state = usePromptData(signal => promptApi.history(promptId, offset, signal), [promptId, offset]);
  return <><Link className="trace-link" to="/prompts">返回 Prompt 列表</Link><div className="trace-heading"><div><span className="eyebrow">TEMPLATE HISTORY</span><h1>{nodeLabels[promptId] || 'Prompt'} · 版本历史</h1><p>按真实登记时间排列，保留旧快照。</p></div><button className="secondary-button" disabled={state.loading} onClick={state.reload}>刷新历史</button></div>
    {state.loading ? <p className="trace-message" role="status">正在读取模板历史…</p> : state.error ? <RegistryError error={state.error} retry={state.reload} /> : state.data && <>
      <RegistrationNotice state={state.data} />
      {state.data.total === 1 && <p className="trace-notice">当前仅有一个已登记版本，暂无另一个真实快照可用于 Diff。</p>}
      <Link className="trace-link" to={'/prompts/versions?' + new URLSearchParams({ node: promptId })}>选择两个历史快照比较</Link>
      {state.data.items.length ? <VersionRows rows={state.data.items} state={state.data} /> : <section className="trace-message"><h2>{state.data.total ? '当前页没有版本' : '尚无已登记版本'}</h2><p>历史内容 unavailable，不根据当前 Prompt 重建历史。</p></section>}
      <Pagination {...state.data} label="版本" change={next => setParams({ offset: String(next) })} />
    </>}
  </>;
}
