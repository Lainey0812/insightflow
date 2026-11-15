/** Explicit component fixtures only; the production application has no mock fallback. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { traceApi } from '../api/traces';
import { lifecycleApi } from '../api/lifecycle';
import { lifecycleFixture } from './lifecycle-fixtures';
import { ApiError } from '../api/client';
import { AdminRoutes } from '../app/routes';
import { flattenSpans, durationText } from '../features/traces/presentation';
import type { TraceRun, TraceSpan, TraceEvent } from '../types/traces';

vi.mock('../api/traces', () => ({ traceApi: { runs: vi.fn(), run: vi.fn(), spans: vi.fn(), events: vi.fn(), grant: vi.fn(), revoke: vi.fn() } }));
vi.mock('../api/lifecycle', () => ({ lifecycleApi: { get: vi.fn() } }));
const base: TraceRun = { run_id: 'run_fixture', status: 'error', session_id: 'session_fixture', execution_id: 'exec_fixture', attempt: 2, retry_of_run_id: 'run_previous', queued_at: '2026-10-28T01:00:00Z', started_at: '2026-10-28T01:00:00Z', duration_ms: 150, manifest: { versions: { prompt_version: 'report-v-test' }, bindings: {} } };
const spans: TraceSpan[] = [
  { span_id: 'span_input', run_id: base.run_id, name: 'evidence_builder', status: 'complete', duration_ms: 5 },
  { span_id: 'span_bad', run_id: base.run_id, parent_span_id: 'span_input', name: 'fact_validator', status: 'error', error_code: 'REPORT_UNVERIFIED_FACT', attributes: { candidate_count: 2, accepted_count: 1, rejected_count: 1 } },
];
const event: TraceEvent = { event_id: 'evt_bad', run_id: base.run_id, span_id: 'span_bad', sequence: 1, event_type: 'candidate.validated', payload: { candidate_index: 1, candidate_status: 'rejected', primary_evidence_id: 'E01', evidence_refs: ['E01'], role: 'implication', rule_ids: ['FREE_TEXT_GUARD', 'NUMERIC'], error_code: 'REPORT_UNVERIFIED_FACT', raw_output: 'SHOULD_NOT_RENDER_PRIVATE_TEXT' } };
function Location() { return <output aria-label="当前位置">{useLocation().search}</output>; }
function view(path: string) { return render(<MemoryRouter initialEntries={[path]}><AdminRoutes /><Location /></MemoryRouter>); }
beforeEach(() => {
  vi.resetAllMocks();
  const lifecycle = lifecycleFixture(); lifecycle.business_lifecycle.status = 'partially_succeeded'; lifecycle.business_lifecycle.report_status = 'partial';
  vi.mocked(lifecycleApi.get).mockResolvedValue(lifecycle);
  vi.mocked(traceApi.runs).mockResolvedValue({ items: [base], total: 1, limit: 20, offset: 0 });
  vi.mocked(traceApi.run).mockResolvedValue({ run: base, business_source: { status: 'completed', report_status: 'partial', same_attempt: true } });
  vi.mocked(traceApi.spans).mockResolvedValue(spans);
  vi.mocked(traceApi.events).mockResolvedValue({ items: [event], limit: 100, offset: 0 });
  vi.mocked(traceApi.grant).mockResolvedValue({}); vi.mocked(traceApi.revoke).mockResolvedValue(undefined);
});

describe('Run Explorer', () => {
  it('loads real API responses with a distinct partial state and detail link', async () => {
    view('/traces'); expect(screen.getByText('正在读取后端运行记录…')).toBeVisible();
    const link = await screen.findByRole('link', { name: '查看详情' });
    expect(link).toHaveAttribute('href', '/traces/run_fixture');
    expect(document.querySelector('.status-error')).toHaveTextContent('错误');
    expect(screen.getByText('report-v-test')).toBeVisible();
  });
  it('puts composable filters and page offset in URL and requests backend filtering', async () => {
    vi.mocked(traceApi.runs).mockResolvedValue({ items: [base], total: 25, limit: 20, offset: 0 });
    view('/traces'); await screen.findByRole('link', { name: '查看详情' });
    fireEvent.change(screen.getByLabelText('状态'), { target: { value: 'error' } });
    fireEvent.change(screen.getByLabelText('包含节点'), { target: { value: 'fact_validator' } });
    fireEvent.change(screen.getByLabelText('版本精确匹配'), { target: { value: 'v-old' } });
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }));
    await waitFor(() => expect(traceApi.runs).toHaveBeenLastCalledWith(expect.stringContaining('node=fact_validator'), expect.any(AbortSignal)));
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('status=error');
    await waitFor(() => expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => expect(traceApi.runs).toHaveBeenLastCalledWith(expect.stringContaining('offset=20'), expect.any(AbortSignal)));
  });
  it('restores filters from a directly opened URL', async () => {
    view('/traces?status=error&version=vA&offset=20&limit=10');
    await screen.findByRole('link', { name: '查看详情' });
    expect(screen.getByLabelText('状态')).toHaveValue('error');
    expect(traceApi.runs).toHaveBeenCalledWith('limit=10&offset=20&status=error&version=vA', expect.any(AbortSignal));
  });
  it('shows an authenticated empty result separately from a failure', async () => {
    vi.mocked(traceApi.runs).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    view('/traces'); expect(await screen.findByRole('heading', { name: '没有匹配的运行记录' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: '无法加载追踪数据' })).not.toBeInTheDocument();
  });
  it('offers credential exchange only on 403 and clears the input without storage', async () => {
    vi.mocked(traceApi.runs).mockRejectedValueOnce(new ApiError('HTTP_ERROR', 'denied', 403));
    view('/traces'); const input = await screen.findByLabelText('管理员只读凭证');
    expect(input).toHaveAttribute('type', 'password');
    fireEvent.change(input, { target: { value: 'test-credential' } }); fireEvent.click(screen.getByRole('button', { name: '启用只读访问' }));
    await waitFor(() => expect(traceApi.grant).toHaveBeenCalledWith('test-credential'));
    await screen.findByRole('link', { name: '查看详情' });
    expect(localStorage.getItem('admin-token')).toBeNull(); expect(sessionStorage.getItem('admin-token')).toBeNull();
  });
  it('does not turn a 503 into empty data or expose a raw response error', async () => {
    vi.mocked(traceApi.runs).mockRejectedValue(new ApiError('HTTP_ERROR', 'PRIVATE_SERVER_TEXT', 503));
    view('/traces'); expect(await screen.findByText(/后端未配置管理员访问/)).toBeVisible();
    expect(screen.queryByText('PRIVATE_SERVER_TEXT')).not.toBeInTheDocument();
  });
  it('cancels a replaced list request', async () => {
    view('/traces'); await screen.findByRole('link', { name: '查看详情' });
    const first = vi.mocked(traceApi.runs).mock.calls.at(-1)![1]!;
    fireEvent.click(screen.getByRole('button', { name: '手动刷新' }));
    await waitFor(() => expect(first.aborted).toBe(true));
  });
});

describe('Trace Detail and Inspector', () => {
  it('highlights the failed span, preserves partial Run status and shows actual rules', async () => {
    view('/traces/run_fixture');
    expect(await screen.findByRole('heading', { name: '报告生成尝试' })).toBeVisible();
    expect(document.querySelector('.span-failed')).toHaveTextContent('事实校验');
    const inspector = screen.getByRole('complementary', { name: '节点 Inspector' });
    expect(inspector).toHaveTextContent('REPORT_UNVERIFIED_FACT');
    await waitFor(() => expect(inspector).toHaveTextContent('FREE_TEXT_GUARD'));
    expect(inspector).toHaveTextContent('implication'); expect(inspector).toHaveTextContent('E01');
    expect(inspector).toHaveTextContent('完整原始输入、输出、候选文本：未保留');
    expect(screen.queryByText('SHOULD_NOT_RENDER_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看上一次运行' })).toHaveAttribute('href', '/traces/run_previous');
    expect(document.querySelector('.run-summary .status-error')).toHaveTextContent('错误');
  });
  it('restores selected span from URL and changes it with node selection', async () => {
    view('/traces/run_fixture?span=span_input');
    await screen.findByRole('heading', { name: '报告生成尝试' });
    expect(traceApi.events).toHaveBeenCalledWith('span_input', 0, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole('button', { name: /事实校验.*错误/s }));
    await waitFor(() => expect(traceApi.events).toHaveBeenLastCalledWith('span_bad', 0, expect.any(AbortSignal)));
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('span=span_bad');
  });
  it('does not invent an unknown span or legacy timing', async () => {
    view('/traces/run_fixture?span=absent');
    expect(await screen.findByText(/URL 中所选节点不属于当前 Run/)).toBeVisible();
    expect(traceApi.events).not.toHaveBeenCalled();
    expect(durationText(null)).toBe('未采集');
  });
  it('supports missing legacy manifest and no spans', async () => {
    vi.mocked(traceApi.run).mockResolvedValue({ run: { run_id: 'old', status: 'error' } }); vi.mocked(traceApi.spans).mockResolvedValue([]);
    view('/traces/old'); expect(await screen.findByText(/此 Run 没有已保存的 Span/)).toBeVisible();
    expect(screen.getByText('历史记录未采集 RunManifest。')).toBeInTheDocument();
  });
  it('loads additional event pages without guessing totals from the first page', async () => {
    const first = Array.from({ length: 100 }, (_, index) => ({ ...event, event_id: 'evt_' + index, sequence: index + 1 }));
    vi.mocked(traceApi.events).mockResolvedValueOnce({ items: first, limit: 100, offset: 0 }).mockResolvedValueOnce({ items: [{ ...event, event_id: 'evt_last', sequence: 101 }], limit: 100, offset: 100 });
    view('/traces/run_fixture');
    fireEvent.click(await screen.findByRole('tab', { name: 'Raw Output' }));
    fireEvent.click(await screen.findByRole('button', { name: '加载更多事件' }));
    await waitFor(() => expect(traceApi.events).toHaveBeenLastCalledWith('span_bad', 100, expect.any(AbortSignal)));
    expect(await screen.findByText(/已加载 101 条事件/)).toBeVisible();
    expect(screen.queryByRole('button', { name: '加载更多事件' })).not.toBeInTheDocument();
  });
});

it('preserves real hierarchy and exposes orphan/cycle records instead of dropping them', () => {
  const ordered = flattenSpans(spans); expect(ordered[1].depth).toBe(1);
  const broken = flattenSpans([{ ...spans[0], parent_span_id: 'missing' }, { ...spans[1], parent_span_id: 'span_bad' }]);
  expect(broken).toHaveLength(2); expect(broken.every(item => item.warning)).toBe(true);
});

it('submits local date filters as timezone-qualified values and rejects reversed ranges', async () => {
  view('/traces'); await screen.findByRole('link', { name: '查看详情' });
  fireEvent.change(screen.getByLabelText('排队时间从（本地）'), { target: { value: '2026-10-28T10:30:15' } });
  fireEvent.change(screen.getByLabelText('排队时间至（本地）'), { target: { value: '2026-10-28T11:30:20' } });
  fireEvent.click(screen.getByRole('button', { name: '应用筛选' }));
  await waitFor(() => expect(vi.mocked(traceApi.runs).mock.calls.length).toBe(2));
  const query = new URLSearchParams(vi.mocked(traceApi.runs).mock.calls.at(-1)![0]);
  expect(query.get('from_time')).toBe(new Date('2026-10-28T10:30:15').toISOString());
  expect(query.get('to_time')).toBe(new Date('2026-10-28T11:30:20').toISOString());
  fireEvent.change(screen.getByLabelText('排队时间从（本地）'), { target: { value: '2026-10-29T10:00:00' } });
  fireEvent.click(screen.getByRole('button', { name: '应用筛选' }));
  expect(screen.getByRole('alert')).toHaveTextContent('开始时间不能晚于结束时间');
  expect(vi.mocked(traceApi.runs).mock.calls).toHaveLength(2);
});

it('restores Workflow selection from URL, preserves waiting states and labels actual capture scope', async () => {
  vi.mocked(traceApi.runs).mockResolvedValue({ items: [{ ...base, kind: 'workflow', execution_id: null, status: 'suspended' }], total: 1, limit: 20, offset: 0 });
  view('/traces?kind=workflow');
  await screen.findByRole('link', { name: '查看详情' });
  expect(traceApi.runs).toHaveBeenCalledWith('limit=20&offset=0&kind=workflow', expect.any(AbortSignal));
  expect(screen.getByLabelText('记录范围')).toHaveValue('workflow');
  expect(screen.getByText('暂停', { selector: '.status-badge' })).toBeVisible();
  expect(screen.getByText(/当前 Run 仅覆盖 Workflow 准备阶段/)).toBeVisible();
});
it('labels Root detail as preparation Trace and keeps lifecycle failure from hiding original spans', async () => {
  vi.mocked(traceApi.run).mockResolvedValue({ run: { ...base, kind: 'workflow', status: 'suspended', manifest: { capture_scope: 'workflow_preparation' } } });
  vi.mocked(lifecycleApi.get).mockRejectedValue(new ApiError('HTTP_ERROR', 'private', 503));
  view('/traces/run_fixture');
  expect(await screen.findByRole('heading', { name: 'Workflow 准备阶段追踪' })).toBeVisible();
  expect(await screen.findByText(/生命周期服务暂不可用/)).toBeVisible();
  expect(screen.getByRole('heading', { name: '执行节点' })).toBeVisible();
  expect(document.querySelector('.span-failed')).toHaveTextContent('事实校验');
});
