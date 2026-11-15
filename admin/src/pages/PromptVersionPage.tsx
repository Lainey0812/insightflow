import { Link, useParams, useSearchParams } from 'react-router-dom';
import { promptApi } from '../api/prompts';
import { jsonText, nodeLabels, offsetValue, Pagination, RegistrationBadge, RegistryError, TextBlock, usePromptData } from '../features/prompts/PromptShared';
import { KeyValues } from '../features/traces/TraceShared';
import { durationText, timeText } from '../features/traces/presentation';

const callLabels: Record<string, string> = { running: '调用中', succeeded: '模型响应协议正常', failed: '调用失败', cancelled: '调用已取消', interrupted: '调用中断' };
export function PromptVersionPage() {
  const { promptId = '', snapshotId = '' } = useParams(); const [params, setParams] = useSearchParams(); const offset = offsetValue(params.get('offset'));
  const state = usePromptData(signal => promptApi.detail(promptId, snapshotId, signal), [promptId, snapshotId]);
  const calls = usePromptData(signal => promptApi.calls(promptId, snapshotId, offset, signal), [promptId, snapshotId, offset]);
  const row = state.data?.template;
  return <><Link className="trace-link" to={'/prompts/' + encodeURIComponent(promptId)}>返回版本历史</Link><div className="trace-heading"><div><span className="eyebrow">IMMUTABLE SNAPSHOT</span><h1>Prompt 版本详情</h1><p>{nodeLabels[promptId] || promptId}</p></div><button className="secondary-button" onClick={() => { state.reload(); calls.reload(); }} disabled={state.loading}>刷新详情</button></div>
    {state.loading ? <p className="trace-message" role="status">正在读取固定模板…</p> : state.error ? <RegistryError error={state.error} retry={state.reload} /> : row && state.data && <>
      <section className="trace-card"><div className="section-heading"><h2>{row.version}</h2><RegistrationBadge row={row} state={state.data} /></div>
        <KeyValues source={{ ...row, source_commit: row.source_commit ?? 'unknown', created_at: timeText(row.created_at) }} fields={{ template_snapshot_id: '快照 ID', content_hash: '内容哈希', created_at: '登记时间', source_commit: '来源 Commit', provenance: '来源性质', change_summary: '登记说明' }} />
        <Link className="trace-link" to={'/prompts/versions?' + new URLSearchParams({ node: promptId, left: snapshotId })}>以此快照作为左侧比较</Link><p className="muted">固定版本内容来自登记记录，不从当前代码补齐，不包含用户实际请求。</p>
      </section>
      <section className="trace-card"><TextBlock title="System" text={row.system_template} />
        <details><summary>固定 User 组合与变量</summary><p className="muted">{state.data.variables_notice} 该版本的 User 由 JSON 组合器生成，没有独立的静态长字符串模板。</p><TextBlock title="User 组合定义" text={jsonText(row.user_composition)} /></details>
        <details><summary>重试指令</summary><TextBlock title="固定重试指令" text={jsonText(row.user_composition.retry_instructions ?? {})} /></details>
        <details><summary>其他已登记固定片段与能力说明</summary><TextBlock title="固定上下文" text={jsonText(row.user_composition.fixed_context ?? {})} /></details>
        <details><summary>输出 Schema 生成定义</summary><p className="muted">实际动态输出 Schema 见授权调用快照。Evidence ID 的变化不表示模板修改。</p><TextBlock title="Schema 定义" text={jsonText(row.output_schema_definition)} /></details>
        <details><summary>组合实现与来源代码（{Object.keys(row.source_files).length} 个登记文件）</summary>{Object.entries(row.source_files).map(([path, source]) => <details key={path}><summary>{path}</summary><p className="wrap-code">源码哈希：{source.source_hash ?? 'unknown'}</p>{typeof source.source === 'string' ? <TextBlock title={path} text={source.source} /> : <p>源码 unavailable：该版本未登记完整内容。</p>}</details>)}</details>
      </section>
      <section className="trace-card"><h2>关联模型调用</h2><p className="muted">调用协议正常不等于分析结果已通过业务校验。Intent、Planner 尚无持久 Run 的调用仍单独可查。</p>
        {calls.loading ? <p role="status">正在读取关联调用…</p> : calls.error ? <RegistryError error={calls.error} retry={calls.reload} /> : calls.data && <>
          {calls.data.items.length ? <div className="trace-table-wrap"><table className="trace-table"><thead><tr><th>调用时间 / 节点</th><th>模型与状态</th><th>尝试 / 重试</th><th>关联</th></tr></thead><tbody>{calls.data.items.map(({ call, model, trace_available }) => <tr key={call.call_id}>
            <td>{timeText(call.started_at)}<small>{nodeLabels[call.node_id]}</small></td><td>{model ?? 'unknown'}<small>{callLabels[call.status] ?? call.status} · {durationText(call.duration_ms)}</small></td><td>第 {call.call_sequence} 次 · 重试序号 {call.retry_index}<small>{call.retry_reason}</small></td><td><Link className="trace-link" to={'/prompts/calls/' + encodeURIComponent(call.call_id)}>查看调用</Link>{trace_available && call.run_id ? <p><Link className="trace-link" to={'/traces/' + encodeURIComponent(call.run_id) + (call.span_id ? '?' + new URLSearchParams({ span: call.span_id }) : '')}>查看关联 Trace</Link></p> : <small>{call.run_id ? '关联 Trace unavailable' : '尚无持久 Trace Run'}</small>}</td>
          </tr>)}</tbody></table></div> : <p className="unavailable-note">此版本尚无匹配的已采集调用。</p>}
          <Pagination {...calls.data} label="调用" change={next => setParams({ offset: String(next) })} />
        </>}
      </section>
    </>}
  </>;
}
