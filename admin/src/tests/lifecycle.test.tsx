import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { LifecyclePanel } from '../features/traces/LifecyclePanel';
import { lifecycleApi } from '../api/lifecycle';
import { ApiError } from '../api/client';
import type { LifecycleReadModel } from '../types/lifecycle';
import type { TraceRun } from '../types/traces';
import { lifecycleFixture } from './lifecycle-fixtures';
vi.mock('../api/lifecycle', () => ({ lifecycleApi: { get: vi.fn() } }));
const run: TraceRun = { run_id: 'run_fixture', kind: 'report_generation', session_id: 'session_fixture', execution_id: 'exec_fixture', attempt: 2, status: 'success' };
function view(data = lifecycleFixture(), selected = run) {
  vi.mocked(lifecycleApi.get).mockResolvedValue(data);
  return render(<MemoryRouter><LifecyclePanel run={selected} refresh={0} /></MemoryRouter>);
}
beforeEach(() => vi.resetAllMocks());
it('keeps verified business success visible when no Trace was collected, without invented nodes', async () => {
  view();
  expect(await screen.findByText('分析与报告已完成')).toBeVisible();
  expect(screen.getByText('计算成功')).toBeVisible(); expect(screen.getByText('报告已交付')).toBeVisible();
  expect(screen.getByText('相关追踪未采集')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'Workflow Trace' })).not.toBeInTheDocument();
  expect(document.querySelector('.span-node')).toBeNull();
});
it('shows Engine success plus Report failure as partial with explicit missing delivery', async () => {
  const data = lifecycleFixture();
  Object.assign(data.business_lifecycle, { status: 'partially_succeeded', report_generation_status: 'failed', report_status: null, report_delivery: 'not_delivered', goal_coverage: null });
  data.reason_codes = ['report_failed', 'report_not_delivered']; view(data);
  expect(await screen.findByText('部分完成')).toBeVisible(); expect(screen.getByText('计算成功')).toBeVisible();
  expect(screen.getByText(/^报告生成失败，/, { selector: 'small' })).toBeVisible(); expect(screen.getByText('报告未交付')).toBeVisible();
  expect(screen.queryByText('分析与报告已完成')).not.toBeInTheDocument();
});
it('clearly separates an old Report Trace from the newly revised current plan', async () => {
  const data = lifecycleFixture();
  Object.assign(data.business_lifecycle, { status: 'waiting_approval', execution_status: null, report_generation_status: null, report_status: null, report_delivery: 'unknown', goal_coverage: null });
  Object.assign(data.source_refs, { plan_version: 2, approval_id: null, execution_id: null, report_attempt: null, report_id: null });
  data.activity = 'review'; data.reason_codes = ['approval_required', 'historical_branch_ignored']; view(data);
  expect(await screen.findByText('等待确认方案')).toBeVisible(); expect(screen.getByText(/当前查看的是历史报告 Trace/)).toBeVisible();
  fireEvent.click(screen.getByText('查看当前分支、版本与记录依据'));
  expect(screen.getByText('方案版本').nextElementSibling).toHaveTextContent('2');
  expect(screen.queryByText('报告已交付')).not.toBeInTheDocument();
});
it.each(['unknown', 'inconsistent'] as const)('shows %s consistency as requiring review without success styling', async consistency => {
  const data = lifecycleFixture();
  data.business_lifecycle.status = 'unknown'; data.business_lifecycle.report_delivery = 'unknown'; data.activity = 'unknown';
  data.consistency.status = consistency; data.reason_codes = ['branch_mismatch']; view(data);
  expect(await screen.findByText('状态待核查')).toBeVisible(); expect(screen.getByRole('alert')).toBeVisible();
  expect(document.querySelector('.lifecycle-succeeded')).not.toBeInTheDocument();
});
it('retains failure as query failure and supports an independent retry', async () => {
  vi.mocked(lifecycleApi.get).mockRejectedValueOnce(new ApiError('HTTP_ERROR', 'PRIVATE_ERROR', 503)).mockResolvedValueOnce(lifecycleFixture());
  render(<MemoryRouter><LifecyclePanel run={run} refresh={0} /></MemoryRouter>);
  expect(await screen.findByText(/生命周期服务暂不可用/)).toBeVisible(); expect(screen.queryByText('PRIVATE_ERROR')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '重新加载生命周期' }));
  expect(await screen.findByText('分析与报告已完成')).toBeVisible();
});
it('does not invent missing legacy session associations', async () => {
  view(lifecycleFixture(), { run_id: 'legacy', status: 'error' });
  expect(await screen.findByText(/历史 Trace 未保存会话关联/)).toBeVisible(); expect(lifecycleApi.get).not.toHaveBeenCalled();
});
it('discards a stale response after changing runs and cancels the replaced request', async () => {
  let resolve!: (value: LifecycleReadModel) => void;
  vi.mocked(lifecycleApi.get).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(lifecycleFixture());
  const mounted = render(<MemoryRouter><LifecyclePanel run={run} refresh={0} /></MemoryRouter>);
  const signal = vi.mocked(lifecycleApi.get).mock.calls[0][1]!;
  mounted.rerender(<MemoryRouter><LifecyclePanel run={{ ...run, run_id: 'other_run' }} refresh={1} /></MemoryRouter>);
  expect(await screen.findByText('分析与报告已完成')).toBeVisible();
  const stale = lifecycleFixture(); stale.business_lifecycle.status = 'failed';
  await act(async () => resolve(stale));
  expect(signal.aborted).toBe(true); expect(screen.getByText('分析与报告已完成')).toBeVisible();
  expect(screen.queryByText('分析失败')).not.toBeInTheDocument();
});
it('links only to actual collected Run IDs and exposes the saved versions on expansion', async () => {
  const data = lifecycleFixture(); data.source_refs.workflow_run_id = 'run_root'; data.source_refs.report_run_id = 'run_current'; view(data);
  await screen.findByText('分析与报告已完成'); fireEvent.click(screen.getByText('查看当前分支、版本与记录依据'));
  expect(screen.getByRole('link', { name: 'Workflow Trace' })).toHaveAttribute('href', '/traces/run_root');
  expect(screen.getByRole('link', { name: '当前报告 Trace' })).toHaveAttribute('href', '/traces/run_current');
});
