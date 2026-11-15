import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { regressionApi } from '../api/regression';
import type { RegressionRun } from '../types/regression';
import { CaseStatusBadge } from '../features/regression/RegressionShared';
import { TraceError } from '../features/traces/AccessPanel';
import { durationText, timeText } from '../features/traces/presentation';

export function RegressionDetailPage() {
  const { runId = '' } = useParams();
  const [run, setRun] = useState<RegressionRun | null>(null), [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => { const c = new AbortController(); setRun(null); setError(null); setLoading(true);
    regressionApi.get(runId, c.signal).then(v => { if (!c.signal.aborted) setRun(v); }).catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort(); }, [runId, refresh]);
  return <div className="wf-page"><Link className="wf-back" to="/evaluations/regressions"><ChevronLeft size={15}/>回归列表</Link>
    <header className="wf-heading"><div><h1>{run?.label || '回归详情'}</h1><p className="wf-id">{runId}</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15}/>手动刷新</button></header>
    {loading && <p role="status">正在读取这次回归…</p>}{error != null && <TraceError error={error} resource="回归详情" retry={() => setRefresh(v => v + 1)}/>}
    {run && <><section className="bc-summary"><dl className="wf-node-facts">
      <div><dt>状态</dt><dd>{run.state === 'finished' ? '已完成' : '未完成（只有已落盘的用例）'}</dd></div>
      <div><dt>通过</dt><dd>{run.summary.passed}/{run.summary.auto_total}</dd></div>
      <div><dt>模型</dt><dd>{run.environment.model}</dd></div>
      <div><dt>开始</dt><dd>{timeText(run.started_at)}</dd></div>
      <div><dt>代码指纹</dt><dd><code>{run.source_fingerprint.slice(0, 12)}</code></dd></div>
      <div><dt>用例集</dt><dd>{run.suite.version || '未记录'} · {run.suite.cases_sha256 ? run.suite.cases_sha256.slice(0, 12) : '无哈希'}</dd></div>
    </dl>{run.approval_policy && <p className="muted">{run.approval_policy}</p>}
      <p className="muted">Prompt 快照：{Object.entries(run.summary.prompt_templates).map(([node, ids]) => `${node} ${ids.join(', ')}`).join('；') || '未采集'}</p></section>
      <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>用例</th><th>判定</th><th>自动检查</th><th>业务结果</th><th>耗时</th></tr></thead><tbody>
        {run.cases.map(item => <tr key={item.case_id}><td>{item.case_id}<small className="wf-subid">{item.title}</small>{item.reason && <small className="wf-subid">{item.reason}</small>}</td>
          <td><CaseStatusBadge status={item.status}/>{item.approved_by_runner && <small className="wf-subid">运行器代为批准</small>}</td>
          <td>{item.checks.filter(c => c.status !== 'skip').map(c => <span key={c.key} className={c.status === 'fail' ? 'wf-warning' : undefined}>{c.label}{c.status === 'fail' ? `：期望 ${String(c.expected)}，实际 ${String(c.actual)}` : ''}<br/></span>)}{item.runner_error && <span className="wf-warning">{item.runner_error}</span>}</td>
          <td>{item.workflow_id ? <code className="wf-subid" title="属于这次回归的独立库，不在日常 Workflow 列表">{item.workflow_id}</code> : '—'}<small className="wf-subid">{[item.final_status, item.execution_status, item.report_status].filter(Boolean).join(' · ') || item.error_code || ''}</small></td>
          <td>{durationText(item.duration_ms)}</td></tr>)}
      </tbody></table></div>
      <p className="muted">安全边界仍需人工看，自动判定不覆盖文案是否越界。</p></>}
  </div>;
}
