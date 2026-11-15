import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { replayApi } from '../api/replay';
import type { ReplayRun } from '../types/replay';
import { OutcomeBadge } from '../features/replay/ReplayShared';
import { TraceError } from '../features/traces/AccessPanel';
import { durationText, timeText } from '../features/traces/presentation';

export function ReplayDetailPage() {
  const { runId = '' } = useParams();
  const [run, setRun] = useState<ReplayRun | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => { const c = new AbortController(); setRun(null); setError(null); setLoading(true);
    replayApi.get(runId, c.signal).then(v => { if (!c.signal.aborted) setRun(v); }).catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort(); }, [runId, refresh]);
  return <div className="wf-page"><Link className="wf-back" to="/bad-cases/replays"><ChevronLeft size={15}/>回放列表</Link>
    <header className="wf-heading"><div><h1>{run?.label || '回放详情'}</h1><p className="wf-id">{runId}</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15}/>手动刷新</button></header>
    {loading && <p role="status">正在读取这次回放…</p>}{error != null && <TraceError error={error} resource="回放详情" retry={() => setRefresh(v => v + 1)}/>}
    {run && <><section className="bc-summary"><dl className="wf-node-facts">
      <div><dt>状态</dt><dd>{run.state === 'finished' ? '已完成' : '未完成（只有已落盘的案例）'}</dd></div>
      <div><dt>未再出现</dt><dd>{run.summary.cleared}/{run.summary.auto_total}</dd></div>
      <div><dt>模型</dt><dd>{run.environment.model}</dd></div>
      <div><dt>开始</dt><dd>{timeText(run.started_at)}</dd></div>
      <div><dt>代码指纹</dt><dd><code>{run.source_fingerprint.slice(0, 12)}</code></dd></div>
    </dl>{run.approval_policy && <p className="muted">{run.approval_policy}</p>}
      <p className="muted">{run.summary.notice || run.notice}</p></section>
      <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>案例</th><th>自动结果</th><th>保存时</th><th>期望</th><th>这次</th></tr></thead><tbody>
        {run.cases.map(item => <tr key={item.case_id}><td><Link className="wf-link" to={'/bad-cases/' + encodeURIComponent(item.case_id)}>{item.title}</Link><code className="wf-subid">{item.case_id}</code></td>
          <td><OutcomeBadge outcome={item.outcome}/>{item.reason && <small className="wf-subid">{item.reason}</small>}{item.approved_by_runner && <small className="wf-subid">运行器代为批准</small>}</td>
          <td>{item.observed}</td><td>{item.expected || '未填写'}</td>
          <td>{item.original_workflow_id && <Link className="wf-link wf-id" to={'/traces/workflows/' + encodeURIComponent(item.original_workflow_id)}>{item.original_workflow_id}</Link>}
            {item.workflow_id && <code className="wf-subid" title="属于这次回放的独立库，不在日常 Workflow 列表">{item.workflow_id}</code>}
            <small className="wf-subid">{[item.failure?.code, item.business_status, item.final_status].filter(Boolean).join(' · ') || '无新错误代码'}</small>
            <small className="wf-subid">{durationText(item.duration_ms)}</small></td></tr>)}
      </tbody></table></div></>}
  </div>;
}
