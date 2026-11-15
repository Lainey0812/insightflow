/** Component fixtures only. Production comparison always reads the authenticated API. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { traceApi } from '../api/traces';
import { ApiError } from '../api/client';
import type { RunComparison } from '../types/traces';
vi.mock('../api/traces', () => ({ traceApi: { runs: vi.fn(), run: vi.fn(), spans: vi.fn(), events: vi.fn(), comparison: vi.fn(), grant: vi.fn(), revoke: vi.fn() } }));
const left = { run_id: 'left', status: 'error' as const, error_code: 'REPORT_UNVERIFIED_FACT', manifest: {} };
const right = { run_id: 'right', status: 'error' as const, manifest: {} };
const fixture: RunComparison = { left, right, live: false, scope: 'report_generation',
  comparability: { status: 'partially_comparable', checks: [{ key: 'user_goal', left: 'hashA', right: 'hashB', status: 'different' }], bindings: [], versions: [], models: [], git: { key: 'git_commit', status: 'unknown' }, notice: '运行差异不能直接归因于 Prompt 变更。' },
  spans: [{ node_key: 'fact_validator', node_attempt: 2, match_basis: 'stable', left: { span_id: 'sl', run_id: 'left', name: 'fact_validator', status: 'failed' }, right: { span_id: 'sr', run_id: 'right', name: 'fact_validator', status: 'partial' } }],
  artifacts: { left: { evidence: { availability: 'unknown' } }, right: { report: { availability: 'available', source: 'runtime_controlled_snapshot', content_sha256: 'test-hash', projection: { report_status: 'partial' } } } },
  diagnostics: { left: [{ sequence: 1, event_type: 'candidate.validated', payload: { rule_ids: ['FREE_TEXT_GUARD'], raw_output: 'PRIVATE_DO_NOT_RENDER' } }], right: [] },
};
function Location() { return <output aria-label="url">{useLocation().pathname + useLocation().search}</output>; }
function view(path: string) { return render(<MemoryRouter initialEntries={[path]}><AdminRoutes /><Location /></MemoryRouter>); }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(traceApi.comparison).mockResolvedValue(fixture); vi.mocked(traceApi.runs).mockResolvedValue({ items: [left, right], total: 2, limit: 20, offset: 0 }); });
it('reloads comparison directly from URL, preserves differences and links to original spans', async () => {
  view('/traces/compare?left=left&right=right');
  expect(await screen.findByRole('heading', { name: '部分可比较 · 存在差异或缺口' })).toBeVisible();
  expect(traceApi.comparison).toHaveBeenCalledWith('left', 'right', expect.any(AbortSignal));
  expect(screen.getByText('已知不同')).toBeVisible();
  expect(screen.getAllByRole('link', { name: '打开原始节点' })[0]).toHaveAttribute('href', '/traces/left?span=sl');
  expect(screen.getByText('FREE_TEXT_GUARD')).toBeVisible();
  expect(screen.queryByText('PRIVATE_DO_NOT_RENDER')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('AnalysisReport', { selector: 'summary' }));
  expect(screen.getByText('SHA256 test-hash')).toBeVisible();
  expect(screen.getAllByText(/unknown/).length).toBeGreaterThan(0);
});
it('keeps comparison on the run-id page instead of row checkboxes', async () => {
  view('/traces');
  expect(await screen.findByRole('link', { name: '通过 Run ID 对比两次运行' })).toHaveAttribute('href', '/traces/compare');
  expect(screen.queryByLabelText('选择对比 left')).not.toBeInTheDocument();
});
it('rejects same run locally and makes no request', () => {
  view('/traces/compare?left=left&right=left');
  expect(screen.getByRole('alert')).toHaveTextContent('两次不同运行');
  expect(traceApi.comparison).not.toHaveBeenCalled();
});
it('supports manual selection without retrieving nonexistent placeholders', async () => {
  view('/traces/compare'); expect(traceApi.comparison).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('左侧 Run ID'), { target: { value: 'left' } });
  fireEvent.change(screen.getByLabelText('右侧 Run ID'), { target: { value: 'right' } });
  fireEvent.click(screen.getByRole('button', { name: '开始对比' }));
  await waitFor(() => expect(traceApi.comparison).toHaveBeenCalled());
});
it('does not replace authentication failures with empty or successful comparison', async () => {
  vi.mocked(traceApi.comparison).mockRejectedValue(new ApiError('HTTP_ERROR', 'private error', 403));
  view('/traces/compare?left=left&right=right');
  expect(await screen.findByLabelText('管理员只读凭证')).toHaveAttribute('type', 'password');
  expect(screen.queryByText('private error')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /关键输入已验证相同/ })).not.toBeInTheDocument();
});
it('aborts a replaced comparison request and refreshes from the same IDs', async () => {
  view('/traces/compare?left=left&right=right');
  await screen.findByText('已知不同'); const signal=vi.mocked(traceApi.comparison).mock.calls[0][2]!;
  fireEvent.click(screen.getByRole('button', { name: '手动刷新' }));
  await waitFor(() => expect(traceApi.comparison).toHaveBeenCalledTimes(2));
  expect(signal.aborted).toBe(true);
});
