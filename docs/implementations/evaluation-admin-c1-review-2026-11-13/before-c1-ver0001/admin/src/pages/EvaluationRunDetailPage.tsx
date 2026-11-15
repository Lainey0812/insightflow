import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, RefreshCw } from 'lucide-react';
import { evaluationApi } from '../api/evaluations';
import { verdicts } from '../types/evaluations';
import type { RunDetail, TrustedMetrics, Verdict } from '../types/evaluations';
import { timeText } from '../features/traces/presentation';
import {
  E2EBadge, EvaluationError, ExecutionBadge, IntegrityBadge, LifecycleBadge, RateValue, Recorded, ShortHash, TrustBadge, VerdictBadge,
  attributionLabels, caseStateLabels, gateLabels, integrityExplanations, provenanceLabels, rateText, runTypeLabels, safeRef,
} from '../features/evaluations/EvaluationShared';

const metricTitle: Record<TrustedMetrics['trust'], string> = {
  verified: '可信指标',
  partial_verified: '局部统计（仅校验通过的 Case，不是整次运行结果）',
  unverified: '运行指标（不可信：历史记录无法校验）',
  incomplete: '运行指标（运行未完成，仅覆盖已记录 Case）',
  none: '运行指标（不报告）',
};
const metricNotice: Record<TrustedMetrics['trust'], string> = {
  verified: '所有 Case 的证据都通过最终 manifest 校验。',
  partial_verified: '证据校验失败。下列数值只覆盖校验通过的 Case，不能称为整次运行成功率。',
  unverified: '历史运行没有 manifest，数值按原始记录计算，但无法确认记录未被改动。',
  incomplete: '运行未结束或缺少 Case，数值只代表已记录的部分。',
  none: '证据校验失败，且没有任何 Case 通过校验，因此不报告指标。',
};

function verdictCounts(counts: Record<string, number>) {
  const known = verdicts.filter(v => counts[v]);
  return known.length ? known.map(v => <span key={v} className="ev-count"><VerdictBadge verdict={v as Verdict} /> {counts[v]}</span>) : <Recorded value={null} />;
}

function Metrics({ run }: { run: RunDetail }) {
  const m = run.metrics, partial = m.trust === 'partial_verified', prefix = partial ? '局部 ' : '';
  return <section className="trace-card" aria-labelledby="run-metrics">
    <h2 id="run-metrics">B. {metricTitle[m.trust]}</h2>
    <p className={m.trusted ? 'muted' : 'trace-notice trace-warning'}><TrustBadge trust={m.trust} /> {metricNotice[m.trust]}</p>
    <div className="ev-metric-grid">
      <RateValue label={prefix + 'E2E 确认成功率'} value={m.e2e_confirmed_success_rate} trust={m.trust} />
      <RateValue label={prefix + '可判定样本通过率'} value={m.decidable_pass_rate} trust={m.trust} />
      <RateValue label={prefix + '评测覆盖率'} value={m.evaluation_coverage} trust={m.trust} />
      <RateValue label={prefix + '执行完成率'} value={m.execution_completion_rate} trust={m.trust} />
    </div>
    <p className="muted">计入统计 {m.included_case_ids.length} 个 Case{m.included_case_ids.length ? `：${m.included_case_ids.join('、')}` : ''}。</p>
    {m.excluded.length > 0 && <div className="trace-notice trace-warning" role="note"><strong>已排除 {m.excluded.length} 个 Case</strong>
      <ul>{m.excluded.map((e, i) => <li key={(e.case_id || '') + i}>{e.case_id || '未知 Case'}：<code>{e.reason || e.status || '证据未通过校验'}</code></li>)}</ul></div>}
    <h3>Evaluator 结果分布与健康度</h3>
    {m.evaluators.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">Evaluator 健康度</caption>
      <thead><tr><th>Evaluator</th><th>Evaluator Verdict 分布</th><th>Evaluator Error Rate</th><th>未评测比例</th></tr></thead>
      <tbody>{m.evaluators.map(e => <tr key={e.evaluator_id}><td><code>{e.evaluator_id}</code>{e.evaluator_id === m.oracle_evaluator_id ? <small className="wf-subid">Oracle</small> : null}</td>
        <td>{verdictCounts(e.counts)}</td>
        <td>{rateText(e.error_rate)}<small className="wf-subid">{e.error_rate.numerator} / {e.error_rate.denominator}</small></td>
        <td>{rateText(e.not_evaluated_rate)}<small className="wf-subid">{e.not_evaluated_rate.numerator} / {e.not_evaluated_rate.denominator}</small></td></tr>)}</tbody>
    </table></div> : <p className="muted">没有可统计的 Evaluator 结果。</p>}
  </section>;
}

export function EvaluationRunDetailPage() {
  const { runId = '' } = useParams();
  const [run, setRun] = useState<RunDetail | null>(null), [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setRun(null);
    evaluationApi.getRun(runId, c.signal)
      .then(v => { if (!c.signal.aborted) setRun(v); })
      .catch(e => { if (!c.signal.aborted) setError(e); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [runId, refresh]);
  const integrity = run?.integrity.status ?? null;
  const badFiles = run ? run.integrity.files.filter(f => f.status !== 'ok') : [];
  return <div className="wf-page"><Link className="wf-back" to="/evaluations/runs"><ChevronLeft size={15} />Evaluation Runs</Link>
    <header className="wf-heading"><div><h1>评测运行</h1><p className="wf-id">{runId}</p></div>
      <button className="secondary-button" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw size={15} />手动刷新</button></header>
    {loading && <p role="status">正在读取评测运行…</p>}
    {error != null && <EvaluationError error={error} resource="评测运行" retry={() => setRefresh(v => v + 1)} back={{ to: '/evaluations/runs', label: '返回运行列表' }} />}
    {run && <>
      <section className="trace-card" aria-labelledby="run-integrity"><h2 id="run-integrity">A. 完整性与来源</h2>
        <p className={integrity === 'VERIFIED' ? 'muted' : 'trace-notice trace-warning'} role="note">
          <IntegrityBadge status={integrity} /> {integrity ? integrityExplanations[integrity] : '运行没有记录完整性状态。'}
          {run.integrity.reasons.length > 0 && <> 原因：{run.integrity.reasons.map(r => <code key={r} className="ev-code">{r}</code>)}</>}</p>
        <dl className="trace-keyvalues">
          <div><dt>Run Type</dt><dd>{runTypeLabels[run.run_type]}</dd></div>
          <div><dt>生命周期</dt><dd><LifecycleBadge status={run.lifecycle_status} /> 只表示运行器是否写完记录，与 E2E 结果无关。</dd></div>
          <div><dt>数据来源</dt><dd>{provenanceLabels[run.provenance]}{run.provenance === 'legacy_projection' ? '：从历史运行格式投影，缺失字段保持为空。' : ''}</dd></div>
          <div><dt>Agent</dt><dd><Recorded value={run.agent_id} /> · 版本 <Recorded value={run.agent_version} /></dd></div>
          <div><dt>数据集</dt><dd>{run.dataset_id ? <Link className="wf-link" to={'/evaluations/datasets/' + encodeURIComponent(run.dataset_id)}>{run.dataset_id}</Link> : <Recorded value={null} />} · 版本 <Recorded value={run.dataset_version} /> · 哈希 <ShortHash value={run.dataset_hash} /></dd></div>
          <div><dt>创建 / 结束</dt><dd>{run.created_at ? timeText(run.created_at) : <Recorded value={null} />} → {run.finished_at ? timeText(run.finished_at) : <Recorded value={null} />}</dd></div>
          <div><dt>未记录字段</dt><dd>{run.unverified_fields.length ? run.unverified_fields.map(f => <code key={f} className="ev-code">{f}</code>) : '无'}</dd></div>
          {run.run_type === 'tc_regression' && <div><dt>原始回归记录</dt><dd><Link className="wf-link" to={'/evaluations/regressions/' + encodeURIComponent(run.run_id)}>在回归对比中查看</Link></dd></div>}
        </dl>
        {badFiles.length > 0 && <><h3>未通过校验的文件</h3><ul>{badFiles.map((f, i) => <li key={(f.ref || '') + i}>
          <code>{safeRef(f.ref) || '路径已隐藏'}</code> · {f.role}{f.case_id ? ` · ${f.case_id}` : ''} · <code>{f.status}</code></li>)}</ul></>}
        <h3>Evaluator 版本</h3>
        {run.evaluator_manifest ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">Evaluator 清单</caption>
          <thead><tr><th>Evaluator</th><th>版本</th><th>要求</th><th>范围</th><th>配置哈希</th></tr></thead>
          <tbody>{run.evaluator_manifest.map(e => <tr key={e.evaluator_id}><td><code>{e.evaluator_id}</code></td><td><Recorded value={e.evaluator_version} /></td>
            <td>{e.requirement === 'required' ? '必选' : e.requirement === 'optional' ? '可选' : e.requirement === 'required_when_applicable' ? '适用时必选' : <Recorded value={null} />}</td>
            <td><Recorded value={e.scope} /></td><td><ShortHash value={e.config_sha256} /></td></tr>)}</tbody></table></div>
          : <p className="muted">此运行格式没有记录 Evaluator 清单与版本（未记录）。</p>}
      </section>
      <Metrics run={run} />
      <section className="trace-card" aria-labelledby="run-cases"><h2 id="run-cases">C. Case Results</h2>
        <p className="muted">共 {run.case_counts.total} 个 Case：已记录 {run.case_counts.present} · 缺失 {run.case_counts.missing} · 未开始 {run.case_counts.not_started} · 无法读取 {run.case_counts.unreadable}。
          执行状态、E2E 结果与完整性分列显示，不合并为单一成功或失败。</p>
        {run.missing_case_ids.length > 0 && <p className="trace-notice trace-warning" role="note">缺失 Case：{run.missing_case_ids.join('、')}。这些 Case 没有结果，不计为通过或失败。</p>}
        {run.unreadable_case_ids.length > 0 && <p className="trace-notice trace-warning" role="note">无法读取的 Case：{run.unreadable_case_ids.join('、')}。</p>}
        {run.cases.length ? <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">Case Results</caption>
          <thead><tr><th>Case</th><th>Case 状态</th><th>Execution Status</th><th>E2E Verdict</th><th>E2E Gate</th><th>失败归因</th><th>Case Integrity</th></tr></thead>
          <tbody>{run.cases.map(c => <tr key={c.case_id} data-case={c.case_id}>
            <td><Link className="wf-link" to={`/evaluations/runs/${encodeURIComponent(run.run_id)}/cases/${encodeURIComponent(c.case_id)}`}>{c.case_id}</Link></td>
            <td>{caseStateLabels[c.case_state]}</td>
            <td><ExecutionBadge status={c.execution_status} />{c.blocking_stage ? <small className="wf-subid">停在 {c.blocking_stage}</small> : null}</td>
            <td><E2EBadge verdict={c.e2e_verdict} /></td>
            <td>{c.e2e_gate ? gateLabels[c.e2e_gate] || c.e2e_gate : <Recorded value={null} />}{c.e2e_reason ? <code className="wf-subid">{c.e2e_reason}</code> : null}</td>
            <td>{attributionLabels[c.attribution.value]}</td>
            <td><IntegrityBadge status={c.case_integrity} /></td>
          </tr>)}</tbody></table></div> : <div className="wf-empty"><p>这次运行没有 Case 记录。</p></div>}
        <p className="muted">运行详情接口不提供逐 Case 的 Evaluator 结果；逐项结果与证据将在 Case 详情（下一阶段）开放。</p>
      </section>
    </>}
  </div>;
}
