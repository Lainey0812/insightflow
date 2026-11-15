import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ExecutionResultV1 } from '../types/contracts';
import type { AnalysisReport, ReportPresentation, ChartSpec, ChartType, ResultTable } from '../types/report';
import { chartRows, compareValues, displayValue, toEChartsOption } from './chartAdapter';
import './report.css';

const InteractiveChart = lazy(() => import('./InteractiveChart'));
const chartNames: Record<ChartType,string> = { bar:'条形图', line:'折线图', pie:'饼图', kpi:'指标卡', table:'表格' };
const coverageNames = { complete:'计划内核心任务已有结果', partial:'目标部分覆盖', blocked:'核心目标未覆盖' };
function metricValue(value: string | number | boolean | null, unit: string | null) {
  if (unit === '%' && typeof value === 'number') return `${Math.abs(value - Math.round(value * 100) / 100) > 1e-10 ? '≈' : ''}${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  return displayValue(value);
}
const statusNames = { complete:'报告已生成', partial:'报告部分生成', unavailable:'暂无有效报告' };

function EvidencePanel({ ids, report }: { ids: string[]; report: AnalysisReport }) {
  const selected = report.evidence.filter(e => ids.includes(e.evidence_id));
  return <details className="v1-evidence"><summary>查看证据与统计口径（{selected.length}）</summary>
    {selected.map(e => <article key={e.evidence_id}><strong>{e.evidence_id} · {e.statement}</strong><p>统计范围：{e.scope}</p><p>计算口径：{e.calculation}</p>
      <small>任务 {e.task_id} · 结果 {e.data_ref} · 字段 {e.result_field} · 来源行 {e.source_row_indices.map(i => i + 1).join('、') || '执行元数据'}{e.related_result_refs.length > 0 && ` · 总体依据 ${e.related_result_refs.join('、')}`}</small>
      {report.execution_metadata[e.task_id]?.sample_definition && <p>样本口径：{report.execution_metadata[e.task_id].sample_definition}</p>}</article>)}
  </details>;
}

export function ResultDataTable({ table, title }: { table: ResultTable; title: string }) {
  const [field, setField] = useState(table.columns[0].field);
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);
  const rows = useMemo(() => [...table.rows].sort((a,b) => {
    if (a[field] === null) return b[field] === null ? 0 : 1;
    if (b[field] === null) return -1;
    return compareValues(a[field], b[field]) * (direction === 'asc' ? 1 : -1);
  }), [table, field, direction]);
  return <div className="v1-data"><div className="v1-table-controls"><label>排序字段 <select aria-label={`${title}排序字段`} value={field} onChange={e => { setField(e.target.value); setPage(0); }}>{table.columns.map(c => <option key={c.field} value={c.field}>{c.label}</option>)}</select></label>
    <button onClick={() => { setDirection(direction === 'asc' ? 'desc' : 'asc'); setPage(0); }}>{direction === 'asc' ? '升序' : '降序'}</button>
    <span>已返回 {table.rows.length} / {table.total_result_rows} 行{table.truncated ? '（上游已截断）' : ''}</span></div>
    <div className="v1-table-scroll"><table aria-label={`${title}结果数据`}><thead><tr>{table.columns.map(c => <th key={c.field}>{c.label}{c.unit && `（${c.unit}）`}</th>)}</tr></thead>
      <tbody>{rows.slice(page * 50, (page + 1) * 50).map((row,index) => <tr key={index}>{table.columns.map(c => <td key={c.field}>{displayValue(row[c.field])}</td>)}</tr>)}</tbody></table></div>
    {rows.length > 50 && <div className="v1-pagination"><button disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page + 1} / {Math.ceil(rows.length / 50)} 页</span><button disabled={(page + 1) * 50 >= rows.length} onClick={() => setPage(page + 1)}>下一页</button></div>}
  </div>;
}

function ChartCard({ spec, report }: { spec: ChartSpec; report: AnalysisReport }) {
  const [type, setType] = useState<ChartType>(spec.chart_type);
  const [showData, setShowData] = useState(false);
  const table = report.result_data[spec.data_ref];
  const option = useMemo(() => toEChartsOption(spec, table, type), [spec, table, type]);
  const priority = report.task_metadata[spec.task_id]?.priority;
  return <article className="v1-chart-card"><div className="v1-card-heading"><h3>{spec.title}</h3><span className="v1-priority">{priority === 'P0' ? '核心分析' : '补充分析'}</span></div>
    <div className="v1-chart-controls"><label>展示方式 <select aria-label={`${spec.title}图表类型`} value={type} onChange={e => setType(e.target.value as ChartType)}>{spec.supported_chart_types.map(t => <option key={t} value={t}>{chartNames[t]}</option>)}</select></label>
      {type !== 'table' && <button onClick={() => setShowData(!showData)}>{showData ? '收起数据' : '查看结果数据'}</button>}</div>
    {spec.note && <p className="v1-note">{spec.note}</p>}
    {type === 'kpi' ? <div className="v1-kpi-value">{displayValue(chartRows(spec, table)[0]?.[spec.metrics[0]] ?? null)} <small>{table.columns.find(c => c.field === spec.metrics[0])?.unit}</small></div> : type !== 'table' && <Suspense fallback={<p>正在绘制图表…</p>}><InteractiveChart option={option} title={spec.title} /></Suspense>}
    {(showData || type === 'table') && <ResultDataTable table={table} title={spec.title} />}
    <EvidencePanel ids={spec.evidence_refs} report={report} />
  </article>;
}

export function ReportDocument({ report, presentation }: { report: AnalysisReport; presentation?: ReportPresentation | null }) {
  const business = presentation?.report_id === report.report_id ? presentation : null;
  const evidenceReport = business ? {...report, evidence: [...report.evidence, ...business.evidence]} : report;
  const [chartsOpen, setChartsOpen] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const [raw, setRaw] = useState<ExecutionResultV1 | null>(null);
  const [rawError, setRawError] = useState('');
  const [rawLoading, setRawLoading] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const scope = Object.entries(report.execution_metadata).filter(([,m]) => m.approved_scope?.length);
  async function download() {
    setDownloadError('');
    try { await api.downloadReport(report.report_id); } catch (e) { setDownloadError(e instanceof Error ? e.message : '下载失败。'); }
  }
  async function loadRaw() {
    setRawOpen(!rawOpen);
    if (raw || rawLoading || rawOpen) return;
    setRawLoading(true); setRawError('');
    try { setRaw(await api.reportExecution(report.report_id)); }
    catch (e) { setRawError(e instanceof Error ? e.message : '读取结果失败。'); }
    finally { setRawLoading(false); }
  }
  return <main className="v1-report"><header className="v1-report-header"><div className="v1-report-top"><a href="/" className="v1-brand">INSIGHTFLOW{business && <span> / 业务分析报告</span>}</a><a className="v1-download" href={`/api/v1/reports/${encodeURIComponent(report.report_id)}/download`} download onClick={e => {e.preventDefault(); void download();}}>下载报告（HTML）</a></div>
    {downloadError && <p role="alert">{downloadError}</p>}
    <div className={`v1-status-row ${business && report.report_status === 'complete' && report.goal_coverage === 'complete' ? 'business-status-complete' : ''}`}><span>{statusNames[report.report_status]}</span><span className={`v1-coverage ${report.goal_coverage}`}>{coverageNames[report.goal_coverage]}</span></div>
    {business ? <><h1>{business.title}</h1><p className="business-subtitle">{business.subtitle}</p>
      <section className="business-summary" aria-label="执行摘要"><h2>执行摘要</h2><p>{business.executive_summary}</p></section>
    </> : <><p className="v1-eyebrow">分析概览 / EXECUTIVE SUMMARY</p><h1>{report.summary.headline}</h1><p className="v1-goal">分析目标：{report.analysis_goal}</p><p>{report.summary.overview}</p>
      <p className="v1-source">{report.dataset_name} · 上传记录 {report.dataset_row_count.toLocaleString('zh-CN')} 条 · 计划 v{report.plan_version} · {report.execution_source === 'imported' ? '上游导入的计算结果' : '分析引擎计算结果'}</p>
      {scope.length > 0 && <details className="v1-evidence"><summary>分析范围与统计口径</summary>{scope.map(([task,m]) => <article key={task}><strong>{report.task_metadata[task]?.title}</strong><ul>{m.approved_scope!.map((line,i) => <li key={i}>{line.replace('拟用统计口径：', '统计口径：')}</li>)}</ul></article>)}</details>}
    </>}
    {report.llm?.is_mock && <p className="v1-warning">当前业务解释为测试内容，不能作为正式业务结论。</p>}
    {business ? <div className="v1-metric-grid business-metrics">{business.key_metrics.map((m,index) => <article className="v1-metric" key={index}><h3>{m.label}</h3><strong>{m.display_value}</strong><p>{m.caption}</p><EvidencePanel ids={m.evidence_refs} report={evidenceReport}/></article>)}</div>
      : <div className="v1-metric-grid">{report.key_metrics.map((m,index) => <div className="v1-metric" key={index}><small>{m.label}</small><strong>{metricValue(m.value, m.unit)} <em>{m.unit}</em></strong><span>依据 {m.evidence_ref}</span></div>)}</div>}
  </header>
    {business ? <>
      <section className="v1-section business-findings"><h2>核心发现与业务解读</h2>
        {business.findings.length ? business.findings.map((finding,index) => <article className="business-finding" key={index}><h3>发现 {index + 1}：{finding.title}</h3><p>{finding.body}</p><EvidencePanel ids={finding.evidence_refs} report={evidenceReport}/></article>) : <p>暂无可用发现，请查看未完成任务与数据说明。</p>}
        {report.charts.length > 0 && <details className="business-chart-details" onToggle={e => setChartsOpen(e.currentTarget.open)}><summary>查看图表与结果数据</summary>{chartsOpen && report.charts.map(spec => <ChartCard key={`${report.report_id}/${spec.chart_id}`} spec={spec} report={evidenceReport}/>)}</details>}
      </section>
      <section className="v1-section"><h2>建议进一步分析</h2>{business.recommendations.length ? business.recommendations.map((text,index) => <p key={index}>{text}</p>) : <p>证据不足，暂不提出行动建议。</p>}</section>
    </> : <>
      <section className="v1-section"><p className="v1-eyebrow">KEY FINDINGS</p><h2>主要发现</h2>{!report.insights.length && <p>暂无可用洞察，请查看未完成任务与数据局限。</p>}
        {report.insights.map((i,index) => <article className="v1-finding" key={i.insight_id}><span className="v1-finding-number">{String(index + 1).padStart(2,'0')}</span><div><h3>{i.finding}</h3><p>{i.implication}</p><details><summary>事实核对详情</summary><p className="v1-fact">{i.fact}</p></details><ul className="v1-small-limitations">{i.limitations.map((l,n) => <li key={n}>{l}</li>)}</ul><EvidencePanel ids={i.evidence_refs} report={report}/></div></article>)}
      </section>
      <section className="v1-section"><p className="v1-eyebrow">INTERACTIVE CHARTS</p><h2>交互图表</h2><p className="v1-section-description">切换展示方式、查看数据或排序，仅使用已有结果。</p>{!report.charts.length && <p>暂无可展示的有效图表。</p>}{report.charts.map(spec => <ChartCard key={`${report.report_id}/${spec.chart_id}`} spec={spec} report={report}/>)}</section>
      <section className="v1-section"><p className="v1-eyebrow">RECOMMENDATIONS</p><h2>下一步建议</h2>{report.recommendations.length ? <ol className="v1-recommendations">{report.recommendations.map((r,index) => <li key={index}>{r.text}<small>依据 {r.evidence_refs.join('、')}</small></li>)}</ol> : <p>证据不足，暂不提出行动建议。</p>}</section>
    </>}
    <section className="v1-section"><h2>{business ? '数据说明' : '数据局限与未完成任务'}</h2>
      {business ? <div className="business-data-notes">{business.data_notes.map((note,index) => <p key={index}>{note}</p>)}</div> : <ul className="v1-limitations">{report.limitations.map((l,index) => <li key={index}>{l}</li>)}</ul>}
      {report.uncompleted_tasks.length > 0 && <div className="v1-uncompleted"><h3>未完成任务</h3>{report.uncompleted_tasks.map(t => <p key={t.task_id}><strong>{t.title}（{t.priority === 'P0' ? '核心分析' : '补充分析'}）</strong>：{t.reason}</p>)}</div>}
      {business && business.scope.length > 0 && <details className="v1-trace"><summary>完整分析范围与统计口径</summary><ul>{business.scope.map((line,i) => <li key={i}>{line}</li>)}</ul></details>}
      <p className="v1-note">数值事实按结构化证据核对；业务解释和建议仍需结合实际情况判断。</p>
      <details className="v1-trace"><summary>报告来源与版本</summary><p>执行编号：{report.execution_id}</p><p>数据集版本：{report.dataset_version}</p><p>生成时间：{new Date(report.generated_at).toLocaleString('zh-CN')}</p>
        {business && <p>展示版本：{business.presentation_version}{business.presentation_version === 'business-report-v1' && '（历史报告展示逻辑）'}</p>}
        {Object.entries(report.execution_metadata).filter(([,m])=>m.insight_generation_version).map(([task,m])=><div key={task}><p>洞察生成版本：{m.insight_generation_version}</p>
          {m.rejected_insights && m.rejected_insights.length > 0 && <details><summary>候选洞察校验记录</summary>{m.rejected_insights.map((item,index)=><p key={index}>候选 {item.candidate_index + 1} · 证据 {item.primary_evidence_id} · {item.error_code}</p>)}</details>}</div>)}
      </details>
      {report.execution_source === 'engine' && <div className="v1-trace"><button onClick={() => void loadRaw()}>{rawOpen ? '收起原始计算结果' : '查看原始计算结果'}</button>
        {rawOpen && <>{rawLoading && <p role="status">正在读取已保存的计算结果…</p>}{rawError && <p role="alert">{rawError}</p>}
        {raw && <><p>计算状态：{{success:'计算成功', partial_success:'部分任务成功', failed:'计算失败'}[raw.execution_status]}</p>
          {raw.tasks.map(t => <article key={t.task_id}><h3>{report.task_metadata[t.task_id]?.title ?? '分析结果'}</h3>{t.failure_reason && <p>{t.failure_reason}</p>}{t.result && <ResultDataTable table={t.result} title={report.task_metadata[t.task_id]?.title ?? '原始计算'}/>}</article>)}
          <details><summary>执行记录与技术详情</summary><pre>{JSON.stringify(raw, null, 2)}</pre></details></>}</>}
      </div>}
    </section><footer className="v1-report-footer">InsightFlow · 从数据到可追溯的业务发现</footer>
  </main>;
}

export default function ReportPage({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [presentation, setPresentation] = useState<ReportPresentation | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setError(''); setReport(null); setPresentation(null);
    Promise.all([api.analysisReport(reportId), api.reportPresentation(reportId).catch(() => null)]).then(([value, view]) => { if (alive) { setReport(value); setPresentation(view); } }).catch(error => { if (alive) setError(error instanceof Error ? error.message : '报告加载失败。'); });
    return () => { alive = false; };
  }, [reportId, attempt]);
  if (error) return <main className="v1-report v1-loading" role="alert"><h1>暂时无法打开报告</h1><p>{error}</p><button onClick={() => setAttempt(attempt + 1)}>重新加载</button><a href="/">返回工作空间</a></main>;
  if (!report) return <main className="v1-report v1-loading" role="status">正在读取分析报告…</main>;
  return <ReportDocument report={report} presentation={presentation}/>;
}
