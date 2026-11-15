import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isRegressionCompare } from '../api/regression';
import type { RegressionCompare, RegressionRun, RegressionRunItem } from '../types/regression';

const item = (id: string, label: string, passed: number): RegressionRunItem => ({
  run_id: id, label, started_at: '2026-11-10T01:00:00+00:00', finished_at: '2026-11-10T01:10:00+00:00', state: 'finished',
  suite: { version: 'typical-suite-v1', cases_sha256: 'abc' }, environment: { model: 'qwen' }, source_fingerprint: 'f'.repeat(64),
  summary: { counts: { passed }, auto_total: 12, passed, llm_calls: 30, duration_ms: 1000, prompt_templates: { intent_parser: ['pt_1'] } }, selected_cases: ['TC01'],
});
const run: RegressionRun = { ...item('rg_20261110-010000_aaaaaa', 'baseline', 12), approval_policy: '计划可审批时由回归运行器代为批准。', cases: [
  { case_id: 'TC01', title: '销售', status: 'passed', checks: [{ key: 'rows', label: '结果', status: 'pass', expected: 1, actual: 1 }], manual_review: [], approved_by_runner: true, workflow_id: 'wf_isolated', final_status: 'COMPLETED', duration_ms: 10 },
  { case_id: 'TC14', title: '故障', status: 'not_run', checks: [], manual_review: [], reason: '需要故障注入' },
] };
const compared: RegressionCompare = {
  schema_version: 'regression-compare-v1', left: item('rg_20261110-010000_aaaaaa', 'baseline', 12), right: item('rg_20261110-020000_bbbbbb', 'after', 11),
  counts: { regressed: 1, unchanged: 11 }, notice: '右侧相对左侧。',
  cases: [{ case_id: 'TC01', title: '销售', left_status: 'passed', right_status: 'failed', change: 'regressed', check_changes: [{ key: 'rows', label: '结果', left: 'pass', right: 'fail' }] }],
};
function view(path: string) { render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function json(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } }); }

it('lists runs and compares the two selected runs', async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => json(String(input).includes('regression-compare') ? compared
    : { schema_version: 'regression-run-page-v1', items: [item('rg_20261110-020000_bbbbbb', 'after', 11), item('rg_20261110-010000_aaaaaa', 'baseline', 12)], total: 2, notice: '独立存储' }));
  vi.stubGlobal('fetch', fetcher);
  view('/evaluations/regressions');
  expect(await screen.findByRole('link', { name: 'baseline' })).toHaveAttribute('href', '/evaluations/regressions/rg_20261110-010000_aaaaaa');
  fireEvent.change(screen.getByLabelText('左侧（基准）'), { target: { value: 'rg_20261110-010000_aaaaaa' } });
  fireEvent.change(screen.getByLabelText('右侧（本次）'), { target: { value: 'rg_20261110-020000_bbbbbb' } });
  fireEvent.click(screen.getByRole('button', { name: '对比' }));
  const region = await screen.findByRole('region', { name: 'baseline → after' });
  expect(within(region).getByText('变差')).toBeVisible();
  expect(within(region).getByText('结果 pass → fail')).toBeVisible();
  await waitFor(() => expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('left=rg_20261110-010000_aaaaaa'));
});

it('shows case checks and keeps the isolated workflow id out of the daily list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(run)));
  view('/evaluations/regressions/rg_20261110-010000_aaaaaa');
  expect(await screen.findByText('运行器代为批准')).toBeVisible();
  expect(screen.getByText('wf_isolated')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'wf_isolated' })).not.toBeInTheDocument();
  expect(screen.getByText('需要故障注入')).toBeVisible();
});

it('rejects a compare payload with an unknown change', () => {
  expect(isRegressionCompare(compared)).toBe(true);
  expect(isRegressionCompare({ ...compared, cases: [{ ...compared.cases[0], change: 'guess' }] })).toBe(false);
});
