import { useState } from 'react';
import { ArrowUpRight, FileChartColumn, LoaderCircle } from 'lucide-react';
import { api } from '../api/client';
import type { ReportGeneration } from '../types/contracts';

export function ReportGenerationCard({executionId, sessionId, record, onChange}: {
  executionId: string; sessionId: string; record?: ReportGeneration; onChange?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = record?.status === 'queued' || record?.status === 'generating';
  async function generate() {
    setBusy(true); setError('');
    try { await api.generateReport(executionId, sessionId, record?.status === 'failed' ? record.attempt : undefined); onChange?.(); }
    catch(e) { setError(e instanceof Error ? e.message : '报告生成请求失败。'); }
    finally { setBusy(false); }
  }
  return <section className="report-card" aria-label="业务分析报告"><div className="report-heading"><span className="report-file-icon"><FileChartColumn size={23}/></span><div><h3>业务分析报告</h3>
    <p>{pending ? '计算结果已保存，正在整理证据与业务洞察…' : record?.status === 'completed' ? '基于真实计算结果，包含图表、发现与数据依据。' : record?.status === 'unavailable' ? '没有可用于报告的有效证据，请查看计算结果及未完成任务。' : record?.status === 'failed' ? '报告生成未完成，已保存的计算结果仍可查看。' : '可基于已保存的计算结果生成报告。'}</p></div></div>
    {pending && <p role="status"><LoaderCircle className="spin" size={17}/>正在生成报告</p>}
    {record?.error && <p role="alert">{record.error.message}</p>}{error && <p role="alert">{error}</p>}
    {record?.report_id && <div className="report-actions"><a className="primary-button" href={`/reports/${encodeURIComponent(record.report_id)}`} target="_blank" rel="noreferrer">预览分析报告<ArrowUpRight size={15}/></a></div>}
    {(!record || (record.status === 'failed' && record.error?.retryable !== false)) && <button className="secondary-button" disabled={busy} onClick={() => void generate()}>{busy ? '正在提交…' : record ? '重新生成报告' : '生成分析报告'}</button>}
    <p className="report-disclaimer">报告可在线预览；需要保存时，可在报告页选择下载。</p>
  </section>;
}
