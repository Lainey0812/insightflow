/** Explicit UI fixtures. Production always reads the real Registry API. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { promptApi } from '../api/prompts';
import { traceApi } from '../api/traces';
import { ApiError } from '../api/client';
import type { CallSummary, PromptCatalog, TemplateDetail, TemplateHistory, TemplateSummary } from '../types/prompts';

vi.mock('../api/prompts', () => ({ promptApi: { catalog: vi.fn(), history: vi.fn(), detail: vi.fn(), compare: vi.fn(), calls: vi.fn(), call: vi.fn(), raw: vi.fn() } }));
vi.mock('../api/traces', () => ({ traceApi: { run: vi.fn(), spans: vi.fn(), events: vi.fn(), grant: vi.fn(), revoke: vi.fn() } }));
const one: TemplateSummary = { template_snapshot_id: 'pt_one', node_id: 'intent_parser', version: 'intent-one', content_hash: 'a'.repeat(64), created_at: '2026-10-29T00:00:00Z', source_commit: null, provenance: 'runtime_source_verified', change_summary: 'fixture only' };
const two = { ...one, template_snapshot_id: 'pt_two', version: 'intent-two', content_hash: 'b'.repeat(64) };
const registration = { latest_registered: one, runtime_snapshot_id: one.template_snapshot_id, runtime_registration: 'registered' as const };
const history: TemplateHistory = { ...registration, prompt_id: 'intent_parser', label: 'Intent Parser', items: [one], total: 1, limit: 20, offset: 0 };
const detail: TemplateDetail = { ...registration, availability: 'available', template: { ...one, system_template: 'FIXED SYSTEM\nOnly evidence.', user_composition: { ordered_user_keys: ['user_query'], retry_instructions: { retry: 'retry safely' } }, output_schema_definition: { generator: 'fixture' }, source_files: {} }, variables_schema_availability: 'unavailable', variables_notice: '未保存独立变量类型 Schema。' };
const call: CallSummary = { call: { call_id: 'call_one', node_id: 'intent_parser', operation_id: 'operation_one', call_sequence: 1, retry_index: 0, retry_reason: null, retry_of_call_id: null, template_snapshot_id: one.template_snapshot_id, request_snapshot_id: 'request_one', run_id: null, span_id: null, status: 'succeeded', started_at: '2026-10-29T00:00:00Z', finished_at: null, duration_ms: 10, error_code: null, outcome_scope: 'provider_protocol' }, request_snapshot: { request_snapshot_id: 'request_one', template_snapshot_id: one.template_snapshot_id, messages_hash: 'message-hash', schema_hash: 'schema-hash', request_hash: 'request-hash', model_parameters: { model: 'qwen3.8-flash' }, client_config: {}, created_at: '', expires_at: null }, trace_available: false, raw_availability: 'retained', redaction: { messages: 'hidden' } };
function Location() { return <output aria-label="Prompt URL">{useLocation().pathname + useLocation().search}</output>; }
function view(url: string) { return render(<MemoryRouter initialEntries={[url]}><AdminRoutes /><Location /></MemoryRouter>); }
beforeEach(() => {
  vi.resetAllMocks();
  const items = (['intent_parser', 'analysis_planner', 'insight_generator'] as const).map(node => ({ ...registration, node_id: node, prompt_id: node, label: node, version_count: 1, latest_registered: { ...one, node_id: node } }));
  vi.mocked(promptApi.catalog).mockResolvedValue({ items, notice: 'Only registered snapshots.' } as PromptCatalog);
  vi.mocked(promptApi.history).mockResolvedValue(history);
  vi.mocked(promptApi.detail).mockResolvedValue(detail);
  vi.mocked(promptApi.calls).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
  vi.mocked(promptApi.call).mockResolvedValue(call);
  vi.mocked(promptApi.compare).mockResolvedValue({ left: one, right: two, content_hash_equal: false, notice: 'Stored only.', sections: [{ key: 'system', label: 'System', availability: 'available', changed: true, lines: [{ kind: 'replace', left: 'old text\n', right: 'new text\n', left_number: 1, right_number: 1 }] }] });
});

it('shows the three stored nodes and restores node filters from URL', async () => {
  view('/prompts/catalog?node=analysis_planner');
  await screen.findByRole('heading', { name: 'analysis_planner' });
  expect(promptApi.catalog).toHaveBeenCalledWith('analysis_planner', expect.any(AbortSignal));
  fireEvent.change(screen.getByLabelText('LLM 节点'), { target: { value: 'insight_generator' } });
  await waitFor(() => expect(promptApi.catalog).toHaveBeenLastCalledWith('insight_generator', expect.any(AbortSignal)));
  expect(screen.getByLabelText('Prompt URL')).toHaveTextContent('node=insight_generator');
});
it('renders an unregistered node without invented history', async () => {
  vi.mocked(promptApi.catalog).mockResolvedValue({ items: [{ ...registration, prompt_id: 'intent_parser', node_id: 'intent_parser', label: 'Intent Parser', version_count: 0, latest_registered: null }], notice: '' });
  view('/prompts/catalog'); expect(await screen.findByText('尚无已登记快照')).toBeVisible();
  expect(screen.queryByRole('link', { name: '查看最新登记' })).not.toBeInTheDocument();
});
it('handles single-version history and unknown commit honestly', async () => {
  view('/prompts/intent_parser');
  expect(await screen.findByText(/当前仅有一个已登记版本/)).toBeVisible();
  expect(screen.getByText('Commit：unknown')).toBeVisible();
  expect(screen.getByRole('navigation', { name: '版本分页' })).toHaveTextContent('共 1 条版本');
  expect(screen.getByRole('link', { name: '查看版本' })).toHaveAttribute('href', '/prompts/intent_parser/versions/pt_one');
});
it('restores and paginates actual history in URL', async () => {
  vi.mocked(promptApi.history).mockResolvedValue({ ...history, total: 21 });
  view('/prompts/intent_parser'); await screen.findByRole('link', { name: '查看版本' });
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  await waitFor(() => expect(promptApi.history).toHaveBeenLastCalledWith('intent_parser', 20, expect.any(AbortSignal)));
  expect(screen.getByLabelText('Prompt URL')).toHaveTextContent('offset=20');
});
it('shows recorded composition and copies exact System text', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined); Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  view('/prompts/intent_parser/versions/pt_one'); await screen.findByRole('heading', { name: 'intent-one' });
  fireEvent.click(screen.getByRole('button', { name: '复制System' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('FIXED SYSTEM\nOnly evidence.'));
  expect(screen.getByText('已复制')).toBeVisible();
  expect(screen.queryByText('PRIVATE_USER_GOAL')).not.toBeInTheDocument();
});
it('keeps page selection and exact saved text on directly opened Diff URLs', async () => {
  vi.mocked(promptApi.history).mockResolvedValue({ ...history, items: [one, two], total: 2 });
  view('/prompts/versions?node=intent_parser&left=pt_one&right=pt_two&offset=20');
  expect(await screen.findByRole('heading', { name: '文本 Diff' })).toBeVisible();
  expect(promptApi.compare).toHaveBeenCalledWith('pt_one', 'pt_two', expect.any(AbortSignal));
  expect(promptApi.history).toHaveBeenCalledWith('intent_parser', 20, expect.any(AbortSignal));
  expect(screen.getByText('old text')).toBeVisible(); expect(screen.getByText('new text')).toBeVisible();
  expect(document.querySelector('.diff-removed')).toHaveTextContent('old text');
  expect(document.querySelector('.diff-added')).toHaveTextContent('new text');
});
it('allows selecting two real versions but never compares a snapshot to itself', async () => {
  vi.mocked(promptApi.history).mockResolvedValue({ ...history, items: [one, two], total: 2 });
  view('/prompts/versions'); await screen.findByLabelText('设为左侧 intent-one');
  fireEvent.click(screen.getByLabelText('设为左侧 intent-one')); fireEvent.click(screen.getByLabelText('设为右侧 intent-one'));
  expect(await screen.findByText('请选择两个不同快照。')).toBeVisible(); expect(promptApi.compare).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('设为右侧 intent-two'));
  await waitFor(() => expect(promptApi.compare).toHaveBeenCalledWith('pt_one', 'pt_two', expect.any(AbortSignal)));
});
it('does not fetch raw content on call detail and cannot invent a Run link', async () => {
  view('/prompts/calls/call_one'); await screen.findByRole('heading', { name: '请求脱敏摘要' });
  expect(promptApi.raw).not.toHaveBeenCalled();
  expect(screen.getByText(/此调用尚无持久 Trace Run/)).toBeVisible();
  expect(screen.queryByRole('link', { name: '打开关联 Run / Span' })).not.toBeInTheDocument();
});
it('requires extra authorization, clears the secret and supports hiding raw text', async () => {
  vi.mocked(promptApi.raw).mockResolvedValue({ request_snapshot_id: 'request_one', payload: { messages: [{ role: 'user', content: 'AUTHORIZED_PRIVATE_INPUT' }] } });
  view('/prompts/calls/call_one'); const field = await screen.findByLabelText('快照读取凭证');
  fireEvent.change(field, { target: { value: 'temporary-secret' } }); fireEvent.click(screen.getByRole('button', { name: '授权查看完整请求' }));
  await screen.findByText(/AUTHORIZED_PRIVATE_INPUT/);
  expect(promptApi.raw).toHaveBeenCalledWith('call_one', 'temporary-secret', expect.any(AbortSignal));
  expect(field).toHaveValue(''); expect(localStorage.getItem('snapshot-token')).toBeNull(); expect(sessionStorage.getItem('snapshot-token')).toBeNull();
  expect(screen.getByLabelText('Prompt URL')).not.toHaveTextContent('temporary-secret');
  fireEvent.click(screen.getByRole('button', { name: '隐藏原始请求' })); expect(screen.queryByText(/AUTHORIZED_PRIVATE_INPUT/)).not.toBeInTheDocument();
});
it('shows denied raw access without leaking private error content', async () => {
  vi.mocked(promptApi.raw).mockRejectedValue(new ApiError('HTTP_ERROR', 'PRIVATE_ERROR', 403));
  view('/prompts/calls/call_one'); fireEvent.change(await screen.findByLabelText('快照读取凭证'), { target: { value: 'wrong' } });
  fireEvent.click(screen.getByRole('button', { name: '授权查看完整请求' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('快照读取授权失败'); expect(screen.queryByText('PRIVATE_ERROR')).not.toBeInTheDocument();
});
it('marks missing history unavailable instead of reconstructing current content', async () => {
  vi.mocked(promptApi.detail).mockRejectedValue(new ApiError('HTTP_ERROR', 'missing', 404));
  view('/prompts/intent_parser/versions/missing'); expect(await screen.findByRole('heading', { name: '历史内容 unavailable' })).toBeVisible();
  expect(screen.queryByText(/FIXED SYSTEM/)).not.toBeInTheDocument();
});
it('does not turn API failure into an empty registry', async () => {
  vi.mocked(promptApi.catalog).mockRejectedValue(new ApiError('HTTP_ERROR', 'PRIVATE_ERROR', 503));
  view('/prompts'); expect(await screen.findByRole('heading', { name: '无法加载Prompt 数据' })).toBeVisible();
  expect(screen.queryByText('尚无已登记快照')).not.toBeInTheDocument();
});
it('links calls to actual persisted Run and Span when available', async () => {
  vi.mocked(promptApi.calls).mockResolvedValue({ items: [{ call: { ...call.call, run_id: 'run_saved', span_id: 'span_saved' }, model: 'qwen3.8-flash', trace_available: true }], total: 1, limit: 20, offset: 0 });
  view('/prompts/intent_parser/versions/pt_one');
  expect(await screen.findByRole('link', { name: '查看关联 Trace' })).toHaveAttribute('href', '/traces/run_saved?span=span_saved');
});
it('links Report Trace to its saved template rather than a current version', async () => {
  vi.mocked(traceApi.run).mockResolvedValue({ run: { run_id: 'run_saved', status: 'success', manifest: { prompt_template_snapshots: { insight_generator: 'pt_recorded' } } } });
  vi.mocked(traceApi.spans).mockResolvedValue([{ span_id: 's', run_id: 'run_saved', name: 'insight_generator', status: 'complete' }]);
  vi.mocked(traceApi.events).mockResolvedValue({ items: [], limit: 100, offset: 0 });
  view('/traces/run_saved'); const inspector = await screen.findByRole('complementary', { name: '节点 Inspector' });
  expect(within(inspector).getByRole('link', { name: /Insight Generator · 查看本次模板快照/ })).toHaveAttribute('href', '/prompts/insight_generator/versions/pt_recorded');
});
