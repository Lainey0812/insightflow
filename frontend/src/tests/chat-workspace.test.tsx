/** Controlled frontend fixtures. No model calls or production sessions are created. */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api/client';
import { MessageComposer } from '../components/MessageComposer';
import { isWorkflowRunning, workflowStep } from '../workflow/presentation';
import type { ReportGeneration, Session, SessionStatus } from '../types/contracts';
import fixture from './fixtures/hitl-v1.json';
import { reviewFixture } from './review-fixtures';

function ready(): Session { return { ...structuredClone(fixture) as Session, workflow_kind: 'real_v1', messages: [], report_generations: [], engine_execution_ids: [] }; }
function mount(current?: Session) {
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', mode: 'real', service: 'insightflow', version: '0.1.0' });
  vi.spyOn(api, 'list').mockResolvedValue(current ? [current] : []);
  vi.spyOn(api, 'review').mockResolvedValue(reviewFixture(current?.review_plan ? current : ready()));
  if (current) { localStorage.setItem('insightflow.session', current.id); vi.spyOn(api, 'session').mockResolvedValue(current); }
  return render(<App />);
}

it.each<SessionStatus>(['CREATED', 'PREPARING', 'PROFILING', 'PARSING_INTENT', 'PLANNING', 'VALIDATING', 'RUNNING'])('blocks send, new analysis and form bypass after restoring server state %s', async status => {
  const current = { ...ready(), status, review_plan: null };
  const create = vi.spyOn(api, 'create'), revise = vi.spyOn(api, 'revise'), clarify = vi.spyOn(api, 'clarify');
  mount(current);
  await screen.findByRole('region', { name: '真实流程状态' });
  expect(screen.getByRole('textbox', { name: '对话输入（暂不可用）' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '新建分析' })).toBeDisabled();
  fireEvent.submit(screen.getByRole('form', { name: '聊天输入' }));
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(create).not.toHaveBeenCalled(); expect(revise).not.toHaveBeenCalled(); expect(clarify).not.toHaveBeenCalled();
  expect(screen.getByText(/完成前暂不能发送新内容/)).toBeInTheDocument();
});

it('polls PREPARING and unlocks only when the saved state becomes clarification_required', async () => {
  const current = { ...ready(), status: 'PREPARING' as const, review_plan: null };
  mount(current);
  const next = { ...current, revision: current.revision + 1, status: 'WAITING_FOR_CLARIFICATION' as const };
  vi.mocked(api.session).mockResolvedValueOnce(current).mockResolvedValue(next);
  await screen.findByRole('region', { name: '真实流程状态' });
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  const answer = await screen.findByRole('textbox', { name: '补充分析需求' }, { timeout: 2500 });
  expect(answer).toBeEnabled();
  expect(screen.getByRole('button', { name: '新建分析' })).toBeEnabled();
});

it.each(['queued', 'generating'] as const)('keeps a completed Engine locked during the accepted report attempt: %s', async status => {
  const current = { ...ready(), status: 'COMPLETED' as const, engine_execution_ids: ['exec_ui'] };
  current.approved_plan_version = current.current_plan_version;
  current.report_generations = [{ session_id: current.id, execution_id: 'exec_ui', status, attempt: 1, report_id: null, error: null, queued_at: '2026-10-30T01:00:00Z', started_at: null, finished_at: null }];
  vi.spyOn(api, 'execution').mockResolvedValue({ execution_id: 'exec_ui', approval_id: 'approval', plan_id: 'plan', plan_version: 1, dataset_id: 'dataset', dataset_version: 'v', execution_status: 'success', warnings: [], tasks: [] });
  mount(current); await screen.findByRole('region', { name: '真实流程状态' });
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '新建分析' })).toBeDisabled();
  expect(screen.getByRole('region', { name: '真实流程状态' })).toHaveTextContent(status === 'queued' ? '报告已排队' : '整理分析报告');
});

it('does not inherit a queued historical report after a new unapproved plan', () => {
  const current = ready(); current.current_plan_version = 2; current.approved_plan_version = null;
  current.engine_execution_ids = ['exec_old']; current.report_generations = [{ execution_id: 'exec_old', session_id: current.id, status: 'generating' } as ReportGeneration];
  expect(isWorkflowRunning(current)).toBe(false);
  expect(workflowStep(current).title).toBe('等待确认方案');
});

it('deduplicates rapid submits and preserves a draft when the request fails', async () => {
  mount(); await screen.findByText('服务已连接');
  let reject!: (reason: Error) => void;
  const create = vi.spyOn(api, 'create').mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  const file = new File(['城市,订单\n上海,2'], 'orders.csv');
  fireEvent.change(screen.getByLabelText('上传数据文件'), { target: { files: [file] } });
  await userEvent.type(screen.getByLabelText('分析需求'), '比较各城市订单数量');
  const form = screen.getByRole('form', { name: '聊天输入' });
  act(() => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
  expect(create).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '上传数据' })).toBeDisabled();
  await act(async () => reject(new Error('连接中断，请重试。')));
  expect(screen.getByLabelText('分析需求')).toHaveValue('比较各城市订单数量');
  expect(screen.getByText('orders.csv')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '发送' })).toBeEnabled();
});

it('blocks Enter, file-input and drop handlers while running even if events are dispatched directly', () => {
  const send = vi.fn(), file = vi.fn();
  render(<MessageComposer text="测试" file={null} mode="goal_driven" busy={false} running hasSession={false} locked={false} headerRow="1" onHeaderRow={vi.fn()} onText={vi.fn()} onFile={file} onMode={vi.fn()} onSubmit={send} onNew={vi.fn()} />);
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  fireEvent.submit(screen.getByRole('form', { name: '聊天输入' }));
  fireEvent.drop(screen.getByRole('form', { name: '聊天输入' }), { dataTransfer: { files: [new File(['x'], 'data.csv')] } });
  fireEvent.change(screen.getByLabelText('上传数据文件'), { target: { files: [new File(['x'], 'data.csv')] } });
  expect(send).not.toHaveBeenCalled(); expect(file).not.toHaveBeenCalled();
});

it('retains an editable clarification box and locks it again after submitting an answer', async () => {
  const current = { ...ready(), status: 'WAITING_FOR_CLARIFICATION' as const, review_plan: null };
  mount(current);
  let finish!: (value: Session) => void;
  const clarify = vi.spyOn(api, 'clarify').mockImplementation(() => new Promise(done => { finish = done; }));
  await userEvent.type(await screen.findByLabelText('补充分析需求'), '先比较地区销售额');
  await userEvent.click(screen.getByRole('button', { name: '发送' }));
  expect(screen.getByRole('textbox')).toBeDisabled();
  expect(clarify).toHaveBeenCalledTimes(1);
  await act(async () => finish(ready()));
  await waitFor(() => expect(screen.getByRole('textbox')).toBeDisabled()); // approval awaits the real review, not more chat
});

it('supports the history drawer with Escape and returns focus to its trigger', async () => {
  mount(); await screen.findByText('服务已连接');
  const open = screen.getByRole('button', { name: '打开会话列表' });
  await userEvent.click(open);
  const side = screen.getByRole('complementary', { name: '咨询记录侧栏' });
  expect(within(side).getByRole('button', { name: '收起会话列表' })).toHaveFocus();
  fireEvent.keyDown(side, { key: 'Escape' });
  expect(open).toHaveAttribute('aria-expanded', 'false'); expect(open).toHaveFocus();
});
