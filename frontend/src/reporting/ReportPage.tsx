import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ExecutionResultV1 } from '../types/contracts';
import type { AnalysisReport, ReportPresentation, ChartSpec, ChartType, ResultTable, SampleStatistics } from '../types/report';
import { chartRows, compareValues, displayValue, toEChartsOption } from './chartAdapter';
import './report.css';

const InteractiveChart = lazy(() => import('./InteractiveChart'));
const chartNames: Record<ChartType,string> = { bar:'条形图', line:'折线图', pie:'饼图', kpi:'指标卡', table:'表格' };
const coverageNames = { complete:'计划内核心任务已有结果', partial:'目标部分覆盖', blocked:'核心目标未覆盖' };
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

function ReportScope({ report }: { report: AnalysisReport }) {
  const tasks = Object.entries(report.execution_metadata).filter(([, meta]) => meta.approved_scope?.length);
  return <section className="report-scope" aria-label="分析范围与统计口径">
    <div className="report-scope-heading"><h2>分析范围与统计口径</h2><span>依据已批准方案与执行记录</span></div>
    <p>数据来源：{report.dataset_name}　上传记录 {report.dataset_row_count.toLocaleString('zh-CN')} 条</p>
    <p className="v1-note">上传记录数不等于各指标的有效样本量；筛选条件、分组方式和计算方法以各分析方向为准。</p>
    <div className="report-scope-tasks">{tasks.map(([id, meta]) => <details key={id}>
      <summary>{report.task_metadata[id]?.title ?? '分析方向'}<span>查看范围与算法</span></summary>
      <ul>{Array.from(new Set(meta.approved_scope)).map((line, index) => <li key={index}>{line.replace('拟用统计口径：', '统计口径：')}</li>)}</ul>
      {typeof meta.valid_sample_count === 'number' && <p>执行记录有效样本量：{meta.valid_sample_count.toLocaleString('zh-CN')} 条；各指标非空记录以计算口径为准。</p>}
    </details>)}</div>
    {!tasks.length && <p>该历史报告未保存完整的已批准统计口径，请查看图表证据及原始计算结果。</p>}
  </section>;
}

function chartInsights(spec: ChartSpec, report: AnalysisReport) {
  return report.insights.filter(insight => {
    const evidence = insight.evidence_refs.map(id => report.evidence.find(e => e.evidence_id === id));
    return evidence.length > 0 && evidence.every(e => e && e.task_id === spec.task_id
      && e.data_ref === spec.data_ref && spec.metrics.includes(e.result_field));
  });
}

function includedCount(report: AnalysisReport, taskId: string): number | null {
  const meta = report.execution_metadata[taskId];
  const count = meta?.effective_row_count;
  const table = meta?.result_id ? report.result_data[meta.result_id] : null;
  return report.execution_source === 'engine' && meta?.status === 'success' && table
    && table.result_id === meta.result_id && meta.execution_metadata?.steps.length
    && Number.isInteger(count) && count! >= 0 && count! <= report.dataset_row_count ? count! : null;
}

function taskSamples(report: AnalysisReport, taskId: string): SampleStatistics | null {
  const saved = report.execution_metadata[taskId]?.execution_metadata?.sample_statistics;
  return saved?.version === 'execution-sample-v1' && saved.scope === 'before_single_aggregate'
    && saved.input_row_count === includedCount(report, taskId) ? saved : null;
}

function ApprovedBasis({report,taskId}:{report:AnalysisReport;taskId:string}) {
  const basis=report.execution_metadata[taskId]?.execution_metadata?.analysis_basis;
  if (report.execution_source !== 'engine' || !basis || basis.plan_version !== report.plan_version) return null;
  const grains={unknown:'业务粒度未声明',record:'每行一条记录',detail:'每行一条明细，同一实体可能多行',entity:'每行一个实体，批准时已核验标识非空且唯一'};
  return <details className="v1-evidence"><summary>审批绑定的指标定义</summary><p>上传数据粒度：{grains[basis.row_grain]}。</p><ul>{basis.metrics.map((metric,index)=><li key={index}>{metric.label}（{metric.function}）：{metric.basis}</li>)}</ul><p>绑定计划第 {basis.plan_version} 版；不依据字段名称补充币种、税费或退款定义。</p></details>;
}

function SampleDefinition({ report, taskId }: {report: AnalysisReport; taskId: string}) {
  const sample = taskSamples(report, taskId);
  if (!sample) return <p className="v1-note">此执行未保存联合完整性统计，不能从逐列缺失数推算缺失记录数。</p>;
  const basis = {rows:'逐行计数，不代表去重业务实体数', non_null_values:'按来源字段非空记录参与计算', distinct_non_null_values:'来源字段先排除缺失，再按不同值计数；参与记录数不是去重结果数'};
  return <details className="v1-evidence"><summary>样本与指标口径</summary>
    <p>范围：本方向聚合前的 {sample.input_row_count} 条记录；Top N 返回分组不会改变此处聚合输入口径。</p>
    {sample.key_fields.length ? <><p>统计关键字段：{sample.key_fields.map(field=>field.label).join('、')}。</p>
      <p>完整记录 {sample.complete_row_count} 条；至少一个关键字段缺失 {sample.missing_row_count} 条（按行去重）。</p>
      <ul>{sample.key_fields.map(field=><li key={field.field}>{field.label}：缺失 {field.missing_count} 条</li>)}</ul></>
      : <p>本方向仅计数记录，没有字段依赖，关键字段完整性统计不适用。</p>}
    <ul>{Object.entries(sample.metrics).map(([alias,metric])=><li key={alias}>{metric.label}（{metric.function}）：{basis[metric.basis]}；参与记录 {metric.participating_count} 条。</li>)}</ul>
    <p>缺失统计不会自动清洗或删除记录；各指标依照已批准函数处理缺失。字段完整不代表数值准确，也不自动确认业务实体、币种或税费范围。</p>
  </details>;
}

function DataOverview({ report, presentation }: {report: AnalysisReport; presentation: ReportPresentation | null}) {
  const ids = Object.keys(report.task_metadata);
  const count = ids.length === 1 ? includedCount(report, ids[0]) : null;
  const quality = presentation?.dataset_overview;
  const sample = ids.length === 1 ? taskSamples(report, ids[0]) : null;
  const perDirection = ids.length > 1 && ids.every(id => taskSamples(report, id));
  const completeValue = sample ? (sample.complete_row_count === null ? '不适用' : sample.complete_row_count.toLocaleString('zh-CN')) : perDirection ? '分方向统计' : '未统计';
  const missingValue = sample ? (sample.missing_row_count === null ? '不适用' : sample.missing_row_count.toLocaleString('zh-CN')) : perDirection ? '分方向统计' : '未统计';
  const cards = [
    {label:'上传记录数', value:report.dataset_row_count.toLocaleString('zh-CN'), note:'已读取数据行，不含表头'},
    {label:'本次纳入记录数', value:count !== null ? count.toLocaleString('zh-CN') : ids.length > 1 ? '分方向统计' : '未统计', note:'各分析方向的参与记录见下方'},
    {label:'关键字段完整记录数', value:completeValue, note:sample || perDirection ? '按各方向聚合输入字段统计' : '此执行尚未保存联合完整性统计'},
    {label:'关键字段缺失记录数', value:missingValue, note:'至少一个关键字段缺失，按行去重'},
  ];
  return <section className="report-overview" aria-label="数据概况"><h2>数据概况</h2>
    <div className="report-overview-grid">{cards.map(card => <article key={card.label}><h3>{card.label}</h3><strong>{card.value}</strong><p>{card.note}</p></article>)}</div>
    <p className="report-quality-note">{quality ? `上传范围共 ${quality.field_count} 个字段，缺失单元格 ${quality.missing_cell_count} 个，疑似重复记录 ${quality.duplicate_row_count} 条。未自动清洗或删除。` : '该报告未提供上传范围的完整数据质量画像。'} 完整性不代表准确性；各指标有效样本量以对应计算口径为准。</p>
  </section>;
}

function ChartInterpretation({ spec, report }: { spec: ChartSpec; report: AnalysisReport }) {
  // Saved evidence controls the binding. Missing explanations remain explicit.
  const insights = chartInsights(spec, report);
  return <section className="chart-interpretation" aria-label={`${spec.title}图表解读`}><h4>图表解读</h4>
    {insights.length ? insights.map(insight => <div key={insight.insight_id}>
      <p className="chart-finding">{insight.finding}</p><p>{insight.implication}</p>
      <details><summary>事实核对详情</summary><p>{insight.fact}</p></details>
      <EvidencePanel ids={insight.evidence_refs} report={report}/>
    </div>) : <p>该图表暂无与此指标直接对应的已保存解读，可查看结果数据与统计口径。不会据此推断差异原因。</p>}
  </section>;
}

function ChartCard({ spec, report }: { spec: ChartSpec; report: AnalysisReport }) {
  const [type, setType] = useState<ChartType>(spec.chart_type);
  const [showData, setShowData] = useState(false);
  const table = report.result_data[spec.data_ref];
  const option = useMemo(() => toEChartsOption(spec, table, type), [spec, table, type]);
  const priority = report.task_metadata[spec.task_id]?.priority;
  // A scalar aggregate can be read as cards. A grouped or truncated table cannot.
  const scalarCards = spec.chart_type === 'table' && spec.dimension === null && !table.truncated
    && table.total_result_rows === 1 && table.rows.length === 1 && spec.metrics.length > 0
    && table.columns.every(column => column.role === 'metric' && spec.metrics.includes(column.field))
    && spec.metrics.every(field => table.columns.some(column => column.field === field)
      && (table.rows[0][field] === null || typeof table.rows[0][field] === 'number'));
  return <article className="v1-chart-card"><div className="v1-card-heading"><h3>{spec.title}</h3><span className="v1-priority">{priority === 'P0' ? '核心分析' : '补充分析'}</span></div>
    <div className="v1-chart-controls">{!scalarCards && <label>展示方式 <select aria-label={`${spec.title}图表类型`} value={type} onChange={e => setType(e.target.value as ChartType)}>{spec.supported_chart_types.map(t => <option key={t} value={t}>{chartNames[t]}</option>)}</select></label>}
      {(scalarCards || type !== 'table') && <button onClick={() => setShowData(!showData)}>{showData ? '收起数据' : '查看结果数据'}</button>}</div>
    <p className="direction-sample">本方向纳入记录：{includedCount(report, spec.task_id)?.toLocaleString('zh-CN') ?? '未统计'}；指标有效样本量：{report.execution_metadata[spec.task_id]?.valid_sample_count?.toLocaleString('zh-CN') ?? '按指标分别统计或未提供'}。</p>
    <ApprovedBasis report={report} taskId={spec.task_id}/>
    <SampleDefinition report={report} taskId={spec.task_id}/>
    {spec.note && <p className="v1-note">{spec.note}</p>}
    {scalarCards && <div className="sales-overview-metrics" aria-label={`${spec.title}指标卡片`}>{spec.metrics.map(field => {
      const column = table.columns.find(c => c.field === field)!;
      const refs = report.evidence.filter(e => e.task_id === spec.task_id && e.data_ref === spec.data_ref && e.result_field === field).map(e => e.evidence_id);
      return <article className="sales-overview-metric" key={field}><h4>{column.label}</h4><p><strong>{displayValue(table.rows[0][field])}</strong>{column.unit && <span>{column.unit}</span>}</p><EvidencePanel ids={refs} report={report}/></article>;
    })}</div>}
    {!scalarCards && (type === 'kpi' ? <div className="v1-kpi-value">{displayValue(chartRows(spec, table)[0]?.[spec.metrics[0]] ?? null)} <small>{table.columns.find(c => c.field === spec.metrics[0])?.unit}</small></div> : type !== 'table' && <Suspense fallback={<p>正在绘制图表…</p>}><InteractiveChart option={option} title={spec.title} /></Suspense>)}
    {(showData || (!scalarCards && type === 'table')) && <ResultDataTable table={table} title={spec.title} />}
    {!scalarCards && ['bar', 'line', 'pie'].includes(type) && <ChartInterpretation spec={spec} report={report} />}
    <EvidencePanel ids={spec.evidence_refs} report={report} />
  </article>;
}

export function ReportDocument({ report, presentation }: { report: AnalysisReport; presentation?: ReportPresentation | null }) {
  const business = presentation?.report_id === report.report_id ? presentation : null;
  const evidenceReport = business ? {...report, evidence: [...report.evidence, ...business.evidence]} : report;
  const [downloadError, setDownloadError] = useState('');
  const [raw, setRaw] = useState<ExecutionResultV1 | null>(null);
  const [rawError, setRawError] = useState('');
  const [rawLoading, setRawLoading] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
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
    <h1>{business?.title ?? report.summary.headline}</h1>
    <p className="v1-goal">分析目标：{report.analysis_goal}</p>
    <p className="business-subtitle">数据来源：{report.dataset_name}</p>
    <DataOverview report={report} presentation={business}/>
    <section className="business-summary" aria-label="执行摘要"><h2>执行摘要</h2><p>{business?.executive_summary ?? report.summary.overview}</p></section>
    {business && business.key_metrics.length > 0 && <details className="v1-evidence"><summary>查看关键业务指标</summary><div className="v1-metric-grid business-metrics">{business.key_metrics.map((metric,index) => <article className="v1-metric" key={index}><h3>{metric.label}</h3><strong>{metric.display_value}</strong><p>{metric.caption}</p><EvidencePanel ids={metric.evidence_refs} report={evidenceReport}/></article>)}</div></details>}
    {report.llm?.is_mock && <p className="v1-warning">当前业务解释为测试内容，不能作为正式业务结论。</p>}
  </header>
    <section className="v1-section" aria-label="各分析方向"><h2>各分析方向</h2><p className="v1-section-description">按已批准方案展示真实结果。图表下方为对应发现、业务解读与证据。</p>
      {report.charts.length ? report.charts.map(spec => <ChartCard key={`${report.report_id}/${spec.chart_id}`} spec={spec} report={report}/>) : <p>暂无可展示的有效图表。</p>}
      {report.insights.filter(i => !report.charts.some(c => chartInsights(c, report).some(m => m.insight_id === i.insight_id))).length > 0 &&
        <details className="v1-evidence"><summary>未绑定图表的补充发现</summary>{report.insights.filter(i => !report.charts.some(c => chartInsights(c, report).some(m => m.insight_id === i.insight_id))).map(i => <article key={i.insight_id}><h3>{i.finding}</h3><p>{i.implication}</p><details><summary>事实核对详情</summary><p>{i.fact}</p></details><EvidencePanel ids={i.evidence_refs} report={report}/></article>)}</details>}
      {business?.presentation_version === 'business-report-v1' && business.findings.length > 0 && <details className="v1-evidence"><summary>历史报告补充解读</summary>{business.findings.map((finding, index) => <article key={index}><h3>{finding.title}</h3><p>{finding.body}</p><EvidencePanel ids={finding.evidence_refs} report={evidenceReport}/></article>)}</details>}
    </section>
    <section className="v1-section" aria-label="整体总结与下一步建议"><h2>整体总结与下一步建议</h2>
      <p>{coverageNames[report.goal_coverage]}；{statusNames[report.report_status]}。以上结论仅适用于本次已保存的分析范围。</p>
      <h3>下一步建议</h3>{Array.from(new Set(business?.recommendations ?? report.recommendations.map(r => r.text))).length
        ? Array.from(new Set(business?.recommendations ?? report.recommendations.map(r => r.text))).map((text,index) => <p key={index}>{text}</p>) : <p>证据不足，暂不提出行动建议。</p>}
    </section>
    <ReportScope report={report}/>
    <section className="v1-section"><h2>数据局限与证据</h2>
      {business ? <div className="business-data-notes">{business.data_notes.map((note,index) => <p key={index}>{note}</p>)}</div> : <ul className="v1-limitations">{report.limitations.map((l,index) => <li key={index}>{l}</li>)}</ul>}
      {report.uncompleted_tasks.length > 0 && <div className="v1-uncompleted"><h3>未完成任务</h3>{report.uncompleted_tasks.map(t => <p key={t.task_id}><strong>{t.title}（{t.priority === 'P0' ? '核心分析' : '补充分析'}）</strong>：{t.reason}</p>)}</div>}

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
