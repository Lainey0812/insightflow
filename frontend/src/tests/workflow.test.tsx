import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api/client';
import { PlanReviewCard } from '../components/PlanReviewCard';
import { ReportLinkCard } from '../components/ReportLinkCard';
import type { Plan, Session } from '../types/contracts';

vi.mock('../components/ReportChart', () => ({ default: () => <div>示例图表</div> }));
const provenance = { source: 'mock' as const, dataset: 'insightflow-demo-v1', plan_version: 1, notice: 'Mock 示例' };
const plan: Plan = { version: 1, created_at: '2026-10-24T12:00:00Z', reason: '初始计划', provenance,
  tasks: [{ id: 't1', title: '销售概况', description: '概况', operation: 'summary', priority: 1 }, { id: 't2', title: '月度销售趋势', description: '趋势', operation: 'trend', priority: 1 }] };
const session: Session = {
  id: 'demo', title: '分析销售', status: 'AWAITING_APPROVAL', revision: 5, updated_at: '2026-10-24T12:00:00Z',
  created_at: '2026-10-24T12:00:00Z', data_source: 'mock', file: { id: 'file', name: 'sales.csv', size: 12, extension: '.csv' },
  user_goal: '分析销售', analysis_mode: 'goal_driven', current_plan_version: 1, approved_plan_version: null,
  plans: [plan], messages: [{ id: 'm1', role: 'assistant', kind: 'plan', content: '请确认计划', plan_version: 1, created_at: '2026-10-24T12:00:00Z' }], report: null, error: null,
};

function mockStart() {
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', mode: 'mock', service: 'insightflow', version: '0.1.0' });
  vi.spyOn(api, 'list').mockResolvedValue([]);
}

describe('single-screen workflow', () => {
  it('submits clarification answers instead of revising or approving a plan', async () => {
    mockStart();
    const waiting: Session = { ...session, status: 'WAITING_FOR_CLARIFICATION', plans: [], current_plan_version: null,
      messages: [{ ...session.messages[0], kind: 'text', content: '你希望比较哪些城市？' }] };
    localStorage.setItem('insightflow.session', waiting.id);
    vi.mocked(api.list).mockResolvedValue([waiting]);
    vi.spyOn(api, 'session').mockResolvedValue(waiting);
    const clarify = vi.spyOn(api, 'clarify').mockResolvedValue(session);
    const revise = vi.spyOn(api, 'revise');
    render(<App />);
    await userEvent.type(await screen.findByLabelText('补充分析需求'), '上海、北京');
    expect(screen.queryByRole('button', { name: '确认并执行' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByRole('region', { name: '分析计划 v1' });
    expect(clarify).toHaveBeenCalledWith(waiting, '上海、北京');
    expect(revise).not.toHaveBeenCalled();
  });

  it('calls health, requires a file, and submits a goal into the chat', async () => {
    mockStart();
    const create = vi.spyOn(api, 'create').mockResolvedValue(session);
    render(<App />);
    await screen.findByText('服务已连接');
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: /看清业务趋势/ }));
    const file = new File(['a\n1'], 'sales.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByLabelText('上传数据文件'), { target: { files: [file] } });
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByRole('region', { name: '分析计划 v1' });
    expect(create).toHaveBeenCalledWith(file, expect.stringContaining('销售额'), 'goal_driven', 1);
    expect(localStorage.getItem('insightflow.session')).toBe('demo');
    expect(screen.getByLabelText('修改分析计划')).toBeInTheDocument();
  });

  it('validates a custom header row and forwards it when creating the session', async () => {
    mockStart();
    const create = vi.spyOn(api, 'create').mockResolvedValue(session);
    render(<App />);
    await screen.findByText('服务已连接');
    await userEvent.click(screen.getByRole('button', { name: /看清业务趋势/ }));
    const file = new File(['title\na\n1'], 'data.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByLabelText('上传数据文件'), { target: { files: [file] } });
    const header = screen.getByRole('spinbutton', { name: '表头行' });
    expect(header).toHaveValue(1);
    await userEvent.clear(header);
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
    await userEvent.type(header, '0');
    expect(header).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
    await userEvent.clear(header);
    await userEvent.type(header, '6');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByRole('region', { name: '分析计划 v1' });
    expect(create).toHaveBeenCalledWith(file, expect.any(String), 'goal_driven', 6);
  });

  it('approves before executing and leaves the report in the conversation', async () => {
    mockStart();
    localStorage.setItem('insightflow.session', session.id);
    vi.mocked(api.list).mockResolvedValue([session]);
    vi.spyOn(api, 'session').mockResolvedValue(session);
    const approved = { ...session, status: 'APPROVED' as const, revision: 6, approved_plan_version: 1 };
    const approve = vi.spyOn(api, 'approve').mockResolvedValue(approved);
    const execute = vi.spyOn(api, 'execute').mockImplementation(async current => {
      expect(approve).toHaveBeenCalledOnce();
      expect(current).toBe(approved);
      return { ...approved, status: 'COMPLETED', report: { title: '示例报告', sections: [], provenance, generated_at: '' }, messages: [{ ...session.messages[0], kind: 'report', content: '完成' }] };
    });
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: '确认并执行' }));
    expect(await screen.findByRole('link', { name: /预览完整报告/ })).toHaveAttribute('href', '/api/v1/sessions/demo/report/preview');
    expect(execute).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText('修改分析计划')).not.toBeInTheDocument();
  });

  it('preserves draft when the backend rejects a revision', async () => {
    mockStart(); localStorage.setItem('insightflow.session', session.id);
    vi.mocked(api.list).mockResolvedValue([session]); vi.spyOn(api, 'session').mockResolvedValue(session);
    vi.spyOn(api, 'revise').mockRejectedValue(new Error('Mock 不支持此修订'));
    render(<App />);
    await userEvent.type(await screen.findByLabelText('修改分析计划'), '预测收入');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));
    await screen.findByRole('alert');
    await waitFor(() => expect(screen.getByLabelText('修改分析计划')).toHaveValue('预测收入'));
  });

  it('makes old plans read-only and exposes delete only on current plans', async () => {
    const remove = vi.fn();
    const { rerender } = render(<PlanReviewCard plan={plan} session={session} busy={false} onRemove={remove} onConfirm={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '删除月度销售趋势' }));
    expect(remove).toHaveBeenCalledWith('t2');
    rerender(<PlanReviewCard plan={plan} session={{ ...session, current_plan_version: 2 }} busy={false} onRemove={remove} onConfirm={vi.fn()} />);
    expect(screen.getByText('历史版本')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /确认并执行/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument();
  });

  it('provides preview and download links with an explicit mock notice', () => {
    render(<ReportLinkCard sessionId="demo" report={{ title: '示例报告', sections: [], provenance, generated_at: '' }} />);
    expect(screen.getByRole('link', { name: /下载报告/ })).toHaveAttribute('download');
    expect(screen.getByText(/非上传文件分析结果/)).toBeInTheDocument();
  });
});
