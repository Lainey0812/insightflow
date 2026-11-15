import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ReportPage, { ReportDocument } from '../reporting/ReportPage';
import { api } from '../api/client';
import { chartRows, toEChartsOption } from '../reporting/chartAdapter';
import type { AnalysisReport } from '../types/report';
import fixture from './fixtures/report-v1.json';

vi.mock('../reporting/InteractiveChart', () => ({ default: ({ title }: { title: string }) => <div role="img" aria-label={title}>图表</div> }));
const report = fixture as unknown as AnalysisReport;

it('renders the five report sections, evidence, limits and optional download', () => {
  render(<ReportDocument report={report} />);
  const headings = screen.getAllByRole('heading', { level: 2 }).map(e => e.textContent);
  expect(headings).toEqual(['数据概况','执行摘要','各分析方向','整体总结与下一步建议','分析范围与统计口径','数据局限与证据']);
  expect(screen.getByText(report.summary.headline)).toBeInTheDocument();
  expect(screen.getByText(/当前业务解释为测试内容/)).toBeInTheDocument();
  const download = screen.getByRole('link', { name: '下载报告（HTML）' });
  expect(download).toHaveAttribute('download');
  expect(download).toHaveAttribute('href', `/api/v1/reports/${report.report_id}/download`);
  fireEvent.click(screen.getAllByText(/查看证据与统计口径/)[0]);
  expect(screen.getAllByText(/统计范围：/).length).toBeGreaterThan(0);
  expect(screen.getByText(/解释和行动建议采用谨慎表述/)).toBeInTheDocument();
});

it('switches compatible charts, exposes rows and sorts locally without repeated analysis', async () => {
  const load = vi.spyOn(api, 'analysisReport').mockResolvedValue(report);
  const create = vi.spyOn(api, 'create');
  render(<ReportPage reportId={report.report_id} />);
  await screen.findByRole('heading', { name: report.summary.headline });
  const selector = screen.getByLabelText(`${report.charts[0].title}图表类型`);
  expect(within(selector).queryByRole('option', { name: '词云' })).toBeNull();
  fireEvent.change(selector, { target: { value:'pie' } });
  expect(selector).toHaveValue('pie');
  fireEvent.click(screen.getByRole('button', { name: '查看结果数据' }));
  const table = screen.getByRole('table', { name: `${report.charts[0].title}结果数据` });
  const sort = screen.getByLabelText(`${report.charts[0].title}排序字段`);
  fireEvent.change(sort, { target: { value:'job_count' } });
  fireEvent.click(screen.getByRole('button', { name:'升序' }));
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('上海');
  fireEvent.change(selector, { target: { value:'table' } });
  expect(screen.getByRole('table')).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(1);
  expect(create).not.toHaveBeenCalled();
});

it('shows failed tasks and blocked goal independently from report generation status', () => {
  const partial = { ...report, report_status:'partial', goal_coverage:'blocked',
    uncompleted_tasks:[{task_id:'A02', title:'技能分析', priority:'P0', reason:'文本频次能力未支持。'}] } as AnalysisReport;
  render(<ReportDocument report={partial} />);
  expect(screen.getByText('报告部分生成')).toBeInTheDocument();
  expect(screen.getByText('核心目标未覆盖')).toBeInTheDocument();
  expect(screen.getByText(/技能分析（核心分析）/)).toBeInTheDocument();
  expect(screen.getByText(/文本频次能力未支持/)).toBeInTheDocument();
});

it('handles unavailable reports and load failure with an explicit retry', async () => {
  const load = vi.spyOn(api, 'analysisReport').mockRejectedValueOnce(new Error('报告不存在。')).mockResolvedValueOnce({
    ...report, report_status:'unavailable', goal_coverage:'blocked', insights:[], charts:[], recommendations:[], evidence:[]
  });
  render(<ReportPage reportId={report.report_id} />);
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name:'重新加载' }));
  await screen.findByText('暂无有效报告');
  expect(screen.getByText('暂无可展示的有效图表。')).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(2);
});

it('treats untrusted labels as text and uses a controlled chart adapter', () => {
  const changed = structuredClone(report);
  changed.charts[0].title = '<script>alert(1)</script>';
  render(<ReportDocument report={changed} />);
  expect(screen.getByRole('heading', { name:'<script>alert(1)</script>' })).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  const option = toEChartsOption(report.charts[0], report.result_data[report.charts[0].data_ref], 'bar');
  expect(option).toMatchObject({ tooltip:{ renderMode:'richText' }, yAxis:{ type:'category' } });
  expect(() => toEChartsOption(report.charts[0], report.result_data[report.charts[0].data_ref], 'line')).toThrow('不兼容');
});

it('limits only chart display, preserving complete sortable result rows', () => {
  const spec = { ...report.charts[0], display_limit:1 };
  const table = report.result_data[spec.data_ref];
  const before = structuredClone(table);
  expect(chartRows(spec, table)).toHaveLength(1);
  expect(table).toEqual(before);
  expect(table.rows).toHaveLength(2);
});
