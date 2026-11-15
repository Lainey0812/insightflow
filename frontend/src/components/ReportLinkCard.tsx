import { lazy, Suspense } from 'react';
import { ArrowUpRight, Download, FileChartColumn, Check } from 'lucide-react';
import { api } from '../api/client';
import type { Report } from '../types/contracts';

const ReportChart = lazy(() => import('./ReportChart'));
export function ReportLinkCard({ sessionId, report }: { sessionId: string; report: Report }) {
  const featured = report.sections.find(s => s.result.operation === 'trend') ?? report.sections[0];
  return <section className="report-card" aria-label="示例分析报告">
    <div className="report-heading"><span className="report-file-icon"><FileChartColumn size={23} /></span><div><h3>{report.title}</h3><p>HTML 报告 · {report.sections.length} 个分析任务 · v{report.provenance.plan_version}</p></div><span className="report-ready"><Check size={12} /> 已生成</span></div>
    {featured && <><div className="chart-caption">{featured.title}<span>单位：元 · 固定示例</span></div><Suspense fallback={<div className="report-chart chart-loading">图表加载中…</div>}><ReportChart option={featured.chart_option} /></Suspense><p className="report-insight">{featured.insight}</p></>}
    <div className="report-actions"><a className="primary-button" href={api.reportUrl(sessionId, 'preview')} target="_blank" rel="noreferrer">预览完整报告<ArrowUpRight size={15} /></a><a className="secondary-button" href={api.reportUrl(sessionId, 'download')} download>下载报告<Download size={15} /></a></div>
    <p className="report-disclaimer">Mock 示例，非上传文件分析结果。下载文件含离线图表与数据依据。</p>
  </section>;
}
