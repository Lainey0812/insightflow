import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isReplayRun } from '../api/replay';
import type { ReplayRun, ReplayRunItem } from '../types/replay';

const item = (id: string, label: string): ReplayRunItem => ({
  run_id: id, label, started_at: '2026-11-10T01:00:00+00:00', finished_at: '2026-11-10T01:10:00+00:00', state: 'finished',
  environment: { model: 'qwen' }, source_fingerprint: 'f'.repeat(64), selected_cases: ['bc_' + 'ab'.repeat(16)],
  summary: { counts: { cleared: 1 }, auto_total: 1, cleared: 1, recurred: 0, source_missing: 0, llm_calls: 4, duration_ms: 1000, prompt_templates: {}, notice: '期望结果仍需人工看。' },
});
const run: ReplayRun = { ...item('rp_20261110-010000_aaaaaa', '修校验后'), approval_policy: '计划可审批时由回放运行器代为批准。', cases: [
  { case_id: 'bc_' + 'ab'.repeat(16), title: '结论不符', observed: '报告称增长最快', expected: '应指出华南更高', outcome: 'cleared', reason: '原错误代码已不在。',
    original_workflow_id: 'wf_daily', workflow_id: 'wf_isolated', approved_by_runner: true, failure: null },
] };
function view(path: string) { render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function json(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } }); }

it('lists saved replays and does not offer a start button', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ schema_version: 'replay-run-page-v1', items: [item('rp_20261110-010000_aaaaaa', '修校验后')], total: 1, notice: '页面不启动回放。' })));
  view('/bad-cases/replays');
  expect(await screen.findByRole('link', { name: '修校验后' })).toHaveAttribute('href', '/bad-cases/replays/rp_20261110-010000_aaaaaa');
  expect(screen.getByText(/run_bad_case_replay.py/)).toBeVisible();
  expect(screen.queryByRole('button', { name: '开始回放' })).not.toBeInTheDocument();
});

it('shows the expected text and keeps the isolated workflow id out of the daily list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(run)));
  view('/bad-cases/replays/rp_20261110-010000_aaaaaa');
  expect(await screen.findByText('应指出华南更高')).toBeVisible();
  expect(screen.getByText('运行器代为批准')).toBeVisible();
  expect(screen.getByRole('link', { name: 'wf_daily' })).toHaveAttribute('href', '/traces/workflows/wf_daily');
  expect(screen.getByText('wf_isolated')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'wf_isolated' })).not.toBeInTheDocument();
});

it('rejects a replay payload with an unknown outcome', () => {
  expect(isReplayRun(run)).toBe(true);
  expect(isReplayRun({ ...run, cases: [{ ...run.cases[0], outcome: 'passed' }] })).toBe(false);
});
