import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { replayApi } from '../api/replay';
import type { ReplayRunPage } from '../types/replay';
import { TraceError } from '../features/traces/AccessPanel';
import { durationText, timeText } from '../features/traces/presentation';

export function ReplaysPage() {
  const [page, setPage] = useState<ReplayRunPage | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => { const c = new AbortController(); setLoading(true); setError(null); setPage(null);
    replayApi.list(c.signal).then(v => { if (!c.signal.aborted) setPage(v); }).catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort(); }, [refresh]);
  return <div className="wf-page"><header className="wf-heading"><div><h1>回放结果</h1><p>读取独立目录里的 Bad Case 回放。页面不启动回放，也不把结果写入日常 Workflow 列表。</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15}/>手动刷新</button></header>
    <p className="muted">新跑一轮：<code>.venv/bin/python backend/scripts/run_bad_case_replay.py --label "说明这次改了什么"</code>。默认只跑待确认和已确认。原会话和上传文件只读；会话或文件已经不在的案例记为不能回放。每次一个新目录，不覆盖旧结果。</p>
    {loading && <p role="status">正在读取回放结果…</p>}{error != null && <TraceError error={error} resource="回放结果" retry={() => setRefresh(v => v + 1)}/>}
    {page && <>
      <p className="muted">{page.notice}</p>
      {page.items.length === 0 ? <p className="wf-empty">还没有回放结果。用上面的命令跑一轮后再刷新。</p> : <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>说明</th><th>状态</th><th>未再出现</th><th>仍在</th><th>不能回放</th><th>模型调用</th><th>耗时</th><th>开始</th></tr></thead><tbody>
        {page.items.map(item => <tr key={item.run_id}><td><Link className="wf-link" to={'/bad-cases/replays/' + encodeURIComponent(item.run_id)}>{item.label}</Link><code className="wf-subid">{item.run_id}</code></td>
          <td>{item.state === 'finished' ? '已完成' : '未完成'}</td><td>{item.summary.cleared}/{item.summary.auto_total}</td><td>{item.summary.recurred}</td><td>{item.summary.source_missing}</td>
          <td>{item.summary.llm_calls}</td><td>{durationText(item.summary.duration_ms)}</td><td>{timeText(item.started_at)}</td></tr>)}
      </tbody></table></div>}
    </>}
  </div>;
}
