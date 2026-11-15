import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { regressionApi } from '../api/regression';
import type { RegressionCompare, RegressionRunPage } from '../types/regression';
import { ChangeBadge, CaseStatusBadge } from '../features/regression/RegressionShared';
import { TraceError } from '../features/traces/AccessPanel';
import { durationText, timeText } from '../features/traces/presentation';

export function RegressionsPage() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<RegressionRunPage | null>(null), [compared, setCompared] = useState<RegressionCompare | null>(null);
  const [error, setError] = useState<unknown>(null), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const left = params.get('left') || '', right = params.get('right') || '';
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setPage(null); setCompared(null);
    const load = regressionApi.list(c.signal).then(v => { if (c.signal.aborted) return; setPage(v);
      return left && right ? regressionApi.compare(left, right, c.signal).then(d => { if (!c.signal.aborted) setCompared(d); }) : undefined; });
    load.catch(e => { if (!c.signal.aborted) setError(e); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [left, right, refresh]);
  function compare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setParams({ left: String(fields.get('left') || ''), right: String(fields.get('right') || '') });
  }
  return <div className="wf-page"><header className="wf-heading"><div><h1>回归对比</h1><p>读取独立目录里的典型用例回归结果。页面不启动运行，也不把结果写入日常 Workflow 列表。</p></div><button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15}/>手动刷新</button></header>
    <p className="muted">新跑一轮：<code>.venv/bin/python backend/scripts/run_regression.py --label "说明这次改了什么"</code>。默认 TC01–TC12，真实模型，计划可审批时代为批准。TC13–TC15 不在自动范围。每次一个新目录，不覆盖旧结果。</p>
    {loading && <p role="status">正在读取回归结果…</p>}{error != null && <TraceError error={error} resource="回归结果" retry={() => setRefresh(v => v + 1)}/>}
    {page && <>
      <form className="wf-filters" onSubmit={compare} key={left + right}>
        <label>左侧（基准）<select name="left" defaultValue={left}><option value="">选择一次运行</option>{page.items.map(i => <option key={i.run_id} value={i.run_id}>{i.label} · {i.run_id}</option>)}</select></label>
        <label>右侧（本次）<select name="right" defaultValue={right}><option value="">选择一次运行</option>{page.items.map(i => <option key={i.run_id} value={i.run_id}>{i.label} · {i.run_id}</option>)}</select></label>
        <button className="primary-button" type="submit">对比</button></form>
      {compared && <section className="rg-compare" aria-labelledby="compare-heading"><header><h2 id="compare-heading">{compared.left.label} → {compared.right.label}</h2>
        <span>{Object.entries(compared.counts).map(([k, n]) => `${n} ${k === 'regressed' ? '变差' : k === 'improved' ? '变好' : k === 'unchanged' ? '不变' : '其他'}`).join(' · ') || '无可比用例'}</span></header>
        <p className="muted">{compared.notice} 模型 {compared.left.environment.model} → {compared.right.environment.model}。代码指纹 {compared.left.source_fingerprint.slice(0, 12)} → {compared.right.source_fingerprint.slice(0, 12)}。</p>
        <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>用例</th><th>左侧</th><th>右侧</th><th>变化</th><th>判定差异</th></tr></thead><tbody>
          {compared.cases.map(c => <tr key={c.case_id}><td>{c.case_id}<small className="wf-subid">{c.title}</small></td><td><CaseStatusBadge status={c.left_status}/></td><td><CaseStatusBadge status={c.right_status}/></td><td><ChangeBadge change={c.change}/></td><td>{c.check_changes.map(d => <code key={d.key} className="wf-subid">{d.label || d.key} {d.left || '无'} → {d.right || '无'}</code>)}</td></tr>)}
        </tbody></table></div></section>}
      <div className="wf-table-top"><strong>{page.total} 次回归</strong><span>按运行目录倒序</span></div>
      {page.items.length ? <div className="wf-table-scroll"><table className="wf-table"><thead><tr><th>运行</th><th>状态</th><th>通过</th><th>模型调用</th><th>耗时</th><th>开始时间</th></tr></thead><tbody>
        {page.items.map(i => <tr key={i.run_id}><td><Link className="wf-link" to={'/evaluations/regressions/' + encodeURIComponent(i.run_id)}>{i.label}</Link><code className="wf-subid">{i.run_id}</code></td><td>{i.state === 'finished' ? '已完成' : '未完成'}</td><td>{i.summary.passed}/{i.summary.auto_total}</td><td>{i.summary.llm_calls}</td><td>{durationText(i.summary.duration_ms)}</td><td>{timeText(i.started_at)}</td></tr>)}
      </tbody></table></div> : <div className="wf-empty"><h3>还没有回归结果</h3><p>用上面的命令跑一轮。结果写在 var/regression/runs，不进入日常库。</p></div>}
      <p className="muted">{page.notice}</p>
    </>}
  </div>;
}
