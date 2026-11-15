// Component fixtures derived from the frozen C2 sample; not browser or server data.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { isBadCase } from '../api/badCases';
import type { BadCase, BadCaseSummary } from '../types/badCases';
import type { WorkflowView } from '../types/workflows';
import fixture from './fixtures/workflow-c2.json';

const workflow = () => structuredClone(fixture) as unknown as WorkflowView;
function view(path: string) { render(<MemoryRouter initialEntries={[path]}><AdminRoutes /></MemoryRouter>); }
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } }); }
const summary: BadCaseSummary = { case_id: 'bc_1', workflow_id: fixture.workflow_id, span_id: null, node_name: null, category: 'insight', severity: 'high',
  title: '结论与数据不符', created_at: '2026-11-10T00:00:00+00:00', created_by: 'lainey', business_status: 'succeeded', status: 'open', sequence: 1, updated_at: '2026-11-10T00:00:00+00:00' };
const page = (items: BadCaseSummary[]) => ({ schema_version: 'bad-case-page-v1', items, total: items.length, limit: 20, offset: 0 });
function badCase(extra: Partial<BadCase> = {}): BadCase {
  const w = workflow(), node = w.trace!.nodes[0], call = w.trace!.llm_calls[0];
  return { schema_version: 'bad-case-v1', ...summary, span_id: node.span_id, node_name: node.name, observed: '华东并非增长最快', expected: '应为华南',
    events: [{ event_id: 'e1', sequence: 1, created_at: summary.created_at, kind: 'created', status: 'open', note: '', annotator: 'lainey' }],
    evidence_sha256: 'a'.repeat(64), evidence_intact: true, evidence_notice: '冻结证据不含原始数据。',
    evidence: { schema_version: 'bad-case-evidence-v1', workflow_id: w.workflow_id, root_run_id: w.root_run_id, business_lifecycle: w.business_lifecycle, failure: null, quality: null,
      consistency: w.consistency, collection_status: 'observed',
      nodes: w.trace!.nodes.map(n => ({ span_id: n.span_id, name: n.name, node_key: n.node_key ?? null, status: n.status, error_code: n.error_code ?? null, started_at: n.started_at, finished_at: n.finished_at ?? null, duration_ms: n.duration_ms ?? null, attributes: n.attributes || {} })),
      llm_calls: call ? [{ call_id: call.call_id, node_id: call.node_id, span_id: node.span_id, status: 'succeeded', retry_index: 1, error_code: null, request_snapshot_id: 'r', template_snapshot_id: 't', response_hash: null }] : [],
      replay_refs: { session_id: w.session_id, execution_id: 'exec_1', dataset_version: null, llm_call_ids: [] } },
    ...extra } as BadCase;
}

it('does not put Bad Case annotation on the workflow graph', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(workflow())));
  view('/traces/workflows/' + fixture.workflow_id);
  expect(await screen.findByRole('heading', { name: '完整 Workflow' })).toBeVisible();
  expect(screen.queryByRole('region', { name: '人工标注' })).not.toBeInTheDocument();
});
it('lists cases with filters', async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL) => json(page([summary])));
  vi.stubGlobal('fetch', fetcher);
  view('/bad-cases');
  expect(await screen.findByRole('link', { name: '结论与数据不符' })).toHaveAttribute('href', '/bad-cases/bc_1');
  expect(screen.getByText('待处理', { selector: '.bc-status' })).toBeVisible();
  fireEvent.change(screen.getByLabelText('处理状态'), { target: { value: 'confirmed' } });
  fireEvent.click(screen.getByRole('button', { name: '查询' }));
  await waitFor(() => expect(String(fetcher.mock.calls.at(-1)?.[0])).toContain('status=confirmed'));
});

it('shows frozen evidence, history, integrity warnings and appends a status change', async () => {
  const updated = badCase({ status: 'confirmed', sequence: 2, events: [...badCase().events, { event_id: 'e2', sequence: 2, created_at: summary.created_at, kind: 'status_changed', status: 'confirmed', note: '复核属实', annotator: 'reviewer' }] });
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST' ? json(updated, 201) : json(badCase({ evidence_intact: false })));
  vi.stubGlobal('fetch', fetcher);
  view('/bad-cases/bc_1');
  expect(await screen.findByRole('alert')).toHaveTextContent('哈希不一致');
  expect(screen.getByRole('link', { name: fixture.workflow_id })).toHaveAttribute('href', '/traces/workflows/' + fixture.workflow_id);
  expect(screen.getByText('华东并非增长最快')).toBeVisible();
  expect(screen.getByRole('heading',{name:'测试输入'})).toBeVisible();
  expect(screen.getByRole('heading',{name:'预期行为'})).toBeVisible();
  expect(screen.getByText('应为华南')).toBeVisible();
  expect(screen.getByRole('heading',{name:'评测规则'})).toBeVisible();
  expect(screen.getByText(/未关联冻结测试用例或评测规则/)).toBeVisible();
  expect(screen.getByText(/冻结证据未保存测试输入原文/)).toBeVisible();
  const form = screen.getByRole('form', { name: '更新处理状态' });
  fireEvent.change(within(form).getByLabelText('新状态'), { target: { value: 'confirmed' } });
  fireEvent.change(within(form).getByLabelText('操作人'), { target: { value: 'reviewer' } });
  fireEvent.click(within(form).getByRole('button', { name: '追加记录' }));
  expect(await screen.findByText('复核属实')).toBeVisible();
  const post = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(String(post[1]!.body))).toEqual({ status: 'confirmed', note: '', annotator: 'reviewer', expected_sequence: 1 });
});

it('rejects malformed Bad Case payloads', () => {
  expect(isBadCase(badCase())).toBe(true);
  expect(isBadCase({ ...badCase(), status: 'guess' })).toBe(false);
  expect(isBadCase({ ...badCase(), events: [] })).toBe(false);
  expect(isBadCase({ ...badCase(), evidence: { ...badCase().evidence, schema_version: 'x' } })).toBe(false);
});
