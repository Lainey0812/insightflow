import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { currentNavigation } from '../app/navigation';

function view(path: string) { return render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
it('only enables Trace and Prompt navigation while keeping other groups visibly disabled', () => {
  view('/traces/workflows');
  const nav = screen.getByRole('navigation', { name: '主导航' });
  for (const label of ['运行总览', '工作流管理', '版本与发布', '系统管理']) {
    const button = within(nav).getByRole('button', { name: label });
    expect(button).toBeVisible(); expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(within(nav).queryByRole('link', { name: 'Planning' })).not.toBeInTheDocument();
  }
  expect(within(nav).getByRole('link', { name: 'Workflow' })).toHaveAttribute('aria-current', 'page');
  expect(within(nav).queryByRole('link', { name: 'Run Explorer' })).not.toBeInTheDocument();
  expect(within(nav).queryByRole('link', { name: 'Trace Detail' })).not.toBeInTheDocument();
  expect(within(nav).getByRole('button', { name: '运行追踪' })).toBeEnabled();
  fireEvent.click(within(nav).getByRole('button', { name: 'Prompt 管理' }));
  expect(within(nav).getByRole('link', { name: 'Prompt 列表' })).toHaveAttribute('href', '/prompts');
  expect(within(nav).getByRole('link', { name: '版本详情与 Diff' })).toHaveAttribute('href', '/prompts/versions');
  const playground = within(nav).getByRole('link', { name: 'Playground（后期）' });
  expect(playground).toHaveAttribute('aria-disabled', 'true');
  expect(playground).not.toHaveAttribute('href');
  fireEvent.click(within(nav).getByRole('button', { name: 'Bad Case' }));
  expect(within(nav).getByRole('link', { name: '问题列表' })).toHaveAttribute('href', '/bad-cases');
  expect(within(nav).getByRole('link', { name: '回放结果' })).toHaveAttribute('href', '/bad-cases/replays');
  fireEvent.click(within(nav).getByRole('button', { name: '评测中心' }));
  expect(within(nav).getByRole('link', { name: '回归对比' })).toHaveAttribute('href', '/evaluations/regressions');
  expect(within(nav).getByRole('link', { name: '测试数据集' })).toHaveAttribute('href', '/evaluations/datasets');
});
it('directly loads a future page without simulated data or model/API calls', () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  view('/prompts/playground');
  expect(screen.getByRole('heading', { name: 'Playground' })).toBeVisible();
  expect(screen.getByRole('heading', { name: '暂未开放' })).toBeVisible();
  expect(within(screen.getByRole('main')).queryByRole('button', { name: '运行模型' })).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});
it('sends the removed trace directories back to Workflow', () => {
  view('/traces/detail');
  expect(screen.getByRole('heading', { name: 'Workflow' })).toBeVisible();
});
it('maps trace URLs onto the single workflow navigation entry', () => {
  expect(currentNavigation('/traces/compare').group?.label).toBe('运行追踪');
  expect(currentNavigation('/traces/compare').page?.label).toBe('Workflow');
  expect(currentNavigation('/traces/run_existing').page?.label).toBe('Workflow');
  expect(currentNavigation('/traces/run_existing').group?.label).toBe('运行追踪');
  expect(currentNavigation('/does-not-exist').page).toBeUndefined();
});
it('keeps permission integration for new placeholder routes', () => {
  render(<MemoryRouter initialEntries={['/evaluations/datasets']}><AdminRoutes resolveAccess={() => 'denied'} /></MemoryRouter>);
  expect(screen.getByRole('alert')).toHaveTextContent('权限检查未允许访问');
  expect(screen.queryByRole('heading', { name: '尚未接入' })).not.toBeInTheDocument();
});

it('maps Workflow observability details without stealing similarly named Run IDs', () => {
  expect(currentNavigation('/traces/workflows').page?.key).toBe('workflow-explorer');
  expect(currentNavigation('/traces/workflows/wf_real').page?.key).toBe('workflow-explorer');
  expect(currentNavigation('/traces/workflows_other_run').page?.key).toBe('workflow-explorer');
});
