/** Explicit UI fixtures for the controlled model response section. */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { AdminRoutes } from '../app/routes';
import { promptApi } from '../api/prompts';
import { ApiError } from '../api/client';
import type { CallSummary } from '../types/prompts';

vi.mock('../api/prompts', () => ({ promptApi: { catalog: vi.fn(), history: vi.fn(), detail: vi.fn(), compare: vi.fn(), calls: vi.fn(), call: vi.fn(), raw: vi.fn(), rawResponse: vi.fn() } }));
const base: CallSummary = { call: { call_id: 'call_one', node_id: 'intent_parser', operation_id: 'op', call_sequence: 1, retry_index: 0, retry_reason: null, retry_of_call_id: null, template_snapshot_id: 'pt_one', request_snapshot_id: 'request_one', run_id: null, span_id: null, status: 'succeeded', started_at: '2026-11-09T00:00:00Z', finished_at: null, duration_ms: 10, error_code: null, outcome_scope: 'provider_protocol' },
  request_snapshot: { request_snapshot_id: 'request_one', template_snapshot_id: 'pt_one', messages_hash: 'm', schema_hash: 's', request_hash: 'r', model_parameters: { model: 'qwen3.8-flash' }, client_config: {}, created_at: '', expires_at: null },
  trace_available: false, raw_availability: 'retained', redaction: { messages: 'hidden' }, response_availability: 'retained', response_kind: 'content' };
function view() { render(<MemoryRouter initialEntries={['/prompts/calls/call_one']}><AdminRoutes /></MemoryRouter>); }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(promptApi.call).mockResolvedValue(base); });

it('does not read the response until authorized, then pretty-prints and clears the secret', async () => {
  vi.mocked(promptApi.rawResponse).mockResolvedValue({ call_id: 'call_one', call_status: 'succeeded', error_code: null, kind: 'content', content: '{"answer":"PRIVATE_MODEL_TEXT"}', truncated: false, content_sha256: 'h' });
  view(); const field = await screen.findByLabelText('快照读取凭证（模型返回）');
  expect(promptApi.rawResponse).not.toHaveBeenCalled(); expect(screen.queryByText(/PRIVATE_MODEL_TEXT/)).not.toBeInTheDocument();
  fireEvent.change(field, { target: { value: 'temporary-secret' } }); fireEvent.click(screen.getByRole('button', { name: '授权查看模型返回' }));
  expect(await screen.findByTestId('raw-response')).toHaveTextContent('"answer": "PRIVATE_MODEL_TEXT"');
  expect(promptApi.rawResponse).toHaveBeenCalledWith('call_one', 'temporary-secret', expect.any(AbortSignal));
  expect(field).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: '隐藏模型返回' })); expect(screen.queryByText(/PRIVATE_MODEL_TEXT/)).not.toBeInTheDocument();
});

it('labels failed-call raw bodies and truncation', async () => {
  vi.mocked(promptApi.call).mockResolvedValue({ ...base, call: { ...base.call, status: 'failed', error_code: 'LLM_INCOMPLETE_OUTPUT' }, response_kind: 'raw_body' });
  vi.mocked(promptApi.rawResponse).mockResolvedValue({ call_id: 'call_one', call_status: 'failed', error_code: 'LLM_INCOMPLETE_OUTPUT', kind: 'raw_body', content: '{"partial', truncated: true, content_sha256: 'h' });
  view(); expect(await screen.findByText(/保留的是 Provider 原始响应体/)).toBeVisible();
  fireEvent.change(screen.getByLabelText('快照读取凭证（模型返回）'), { target: { value: 'x' } }); fireEvent.click(screen.getByRole('button', { name: '授权查看模型返回' }));
  expect(await screen.findByText(/调用失败时的 Provider 原始响应体.*已截断/)).toBeVisible();
  expect(screen.getByTestId('raw-response')).toHaveTextContent('{"partial');
});

it('explains unavailable responses without offering a read form', async () => {
  vi.mocked(promptApi.call).mockResolvedValue({ ...base, response_availability: 'unavailable', response_kind: null });
  view(); expect(await screen.findByText(/模型返回未保留/)).toBeVisible();
  expect(screen.queryByRole('button', { name: '授权查看模型返回' })).not.toBeInTheDocument();
});

it('shows integrity and authorization failures without leaking content', async () => {
  vi.mocked(promptApi.rawResponse).mockRejectedValueOnce(new ApiError('HTTP_ERROR', 'PRIVATE_ERROR', 503));
  view(); fireEvent.change(await screen.findByLabelText('快照读取凭证（模型返回）'), { target: { value: 'x' } });
  fireEvent.click(screen.getByRole('button', { name: '授权查看模型返回' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('完整性校验失败'); expect(screen.queryByText('PRIVATE_ERROR')).not.toBeInTheDocument();
});
