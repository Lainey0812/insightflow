// Component fixtures derived from the frozen C2 sample; not browser or server data.
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isWorkflow } from '../api/workflows';
import type { WorkflowQuality, WorkflowView } from '../types/workflows';
import fixture from './fixtures/workflow-c2.json';

const quality: WorkflowQuality = {
  attention_count: 2, unavailable_count: 1, notice: '信号由已采集的节点与调用推导，未采集项不按 0 处理。',
  signals: [
    { key: 'clarification_rounds', stage: 'understanding', label: '需求澄清轮数', value: 0, level: 'normal', note: '' },
    { key: 'f0_count', stage: 'planning', label: 'F0 不可执行任务数', value: null, level: 'unavailable', note: '早于本功能的记录未采集。' },
    { key: 'hitl_revisions', stage: 'review', label: '用户修改计划次数', value: 1, level: 'attention', note: '' },
    { key: 'report_status', stage: 'report', label: '报告完整度', value: 'partial', level: 'attention', note: '' },
  ],
};
const source = () => ({ ...structuredClone(fixture), quality }) as unknown as WorkflowView;
function view(path: string) { render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function response(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } }); }

it('keeps the workflow graph free of the quality summary', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response(source())));
  view('/traces/workflows/' + fixture.workflow_id);
  expect(await screen.findByRole('heading', { name: '完整 Workflow' })).toBeVisible();
  expect(screen.queryByRole('region', { name: '质量信号' })).not.toBeInTheDocument();
});

it('shows the attention count in the workflow list', async () => {
  const data = source(); delete data.trace;
  vi.stubGlobal('fetch', vi.fn(async () => response({ schema_version: 'workflow-observability-page-v1', items: [data], total: 1, limit: 20, offset: 0, sort: 's', notice: 'n' })));
  view('/traces/workflows');
  expect(await screen.findByText('2 项需关注')).toHaveAttribute('title', '用户修改计划次数、报告完整度');
});

it('rejects malformed quality payloads', () => {
  const data = source();
  expect(isWorkflow(data)).toBe(true);
  expect(isWorkflow({ ...data, quality: undefined })).toBe(true);
  expect(isWorkflow({ ...data, quality: { ...quality, signals: [{ ...quality.signals[0], level: 'guess' }] } })).toBe(false);
  expect(isWorkflow({ ...data, quality: { ...quality, signals: [{ ...quality.signals[0], stage: 'other' }] } })).toBe(false);
  expect(isWorkflow({ ...data, quality: { ...quality, attention_count: -1 } })).toBe(false);
});
