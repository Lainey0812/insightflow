import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { ErrorBoundary } from '../components/ErrorBoundary';

describe('independent admin routes', () => {
  it.each([
    ['/dashboard', '运行总览', '暂未开放'],
    ['/versions', '版本对比', '暂未开放'],
    ['/settings', '环境配置', '暂未开放'],
  ])('directly renders %s without API calls or fabricated monitoring data', (path, title, content) => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>);
    expect(screen.getByRole('heading', { level: 1, name: title })).toBeVisible();
    expect(screen.getByRole('heading', { level: 2, name: content })).toBeVisible();
    expect(screen.getByText(/当前开放运行追踪、Prompt 管理、Bad Case 与回归对比；其他模块暂未开放/)).toBeVisible();
    expect(screen.queryByText(/100%|超级管理员|登录成功/)).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('redirects the root to Trace and handles unknown URLs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }), { status: 200 })));
    const { unmount } = render(<MemoryRouter initialEntries={['/']}><AdminRoutes /></MemoryRouter>);
    expect(screen.getByRole('heading', { level: 1, name: 'Workflow' })).toBeVisible();
    unmount();
    render(<MemoryRouter initialEntries={['/not-a-page']}><AdminRoutes /></MemoryRouter>);
    expect(screen.getByRole('heading', { level: 1, name: '页面不存在' })).toBeVisible();
    expect(screen.getByRole('link', { name: '返回运行追踪' })).toHaveAttribute('href', '/traces/workflows');
  });
  it('keeps the future permission integration point separate from fake login', () => {
    render(<MemoryRouter initialEntries={['/traces']}><AdminRoutes resolveAccess={() => 'denied'} /></MemoryRouter>);
    expect(screen.getByRole('alert')).toHaveTextContent('权限检查未允许访问');
    expect(screen.queryByText('暂无可查看的 Trace')).not.toBeInTheDocument();
  });
  it('shows a controlled fallback for rendering errors', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    function Broken(): never { throw new Error('internal diagnostic details'); }
    render(<ErrorBoundary><Broken /></ErrorBoundary>);
    expect(screen.getByRole('heading', { name: '管理台暂时无法显示' })).toBeVisible();
    expect(screen.queryByText('internal diagnostic details')).not.toBeInTheDocument();
  });
});
