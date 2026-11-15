import { ApiError, createAdminClient } from './client';
import type { CallPage, CallResponseContent, CallSummary, PromptCatalog, PromptDiff, TemplateDetail, TemplateHistory } from '../types/prompts';

const client = createAdminClient();
const part = encodeURIComponent;
function invalid(): never { throw new ApiError('INVALID_RESPONSE', 'Prompt 接口返回结构不正确。'); }
function page(value: { items: unknown[]; total: number; limit: number; offset: number }) {
  if (!value || !Array.isArray(value.items) || !Number.isInteger(value.total) || value.total < 0 || !Number.isInteger(value.limit) || value.limit < 1 || !Number.isInteger(value.offset) || value.offset < 0) invalid();
}
export const promptApi = {
  async catalog(node: string, signal?: AbortSignal) {
    const value = await client.get<PromptCatalog>('prompts' + (node ? '?' + new URLSearchParams({ node }) : ''), { signal, cache: 'no-store' });
    if (!value || !Array.isArray(value.items) || value.items.some(i => !i || typeof i.prompt_id !== 'string' || !Number.isInteger(i.version_count))) invalid();
    return value;
  },
  async history(node: string, offset = 0, signal?: AbortSignal) {
    const value = await client.get<TemplateHistory>(`prompts/${part(node)}/versions?limit=20&offset=${offset}`, { signal, cache: 'no-store' });
    page(value);
    if (value.prompt_id !== node || value.items.some(v => typeof v.template_snapshot_id !== 'string' || v.node_id !== node)) invalid();
    return value;
  },
  async detail(node: string, id: string, signal?: AbortSignal) {
    const value = await client.get<TemplateDetail>(`prompts/${part(node)}/versions/${part(id)}`, { signal, cache: 'no-store' });
    if (!value?.template || value.template.template_snapshot_id !== id || value.template.node_id !== node || typeof value.template.system_template !== 'string' || !value.template.user_composition || !value.template.source_files) invalid();
    return value;
  },
  async compare(left: string, right: string, signal?: AbortSignal) {
    const value = await client.get<PromptDiff>('prompts/compare?' + new URLSearchParams({ left, right }), { signal, cache: 'no-store' });
    if (!value || value.left?.template_snapshot_id !== left || value.right?.template_snapshot_id !== right || !Array.isArray(value.sections) || value.sections.some(s => !s || !Array.isArray(s.lines))) invalid();
    return value;
  },
  async calls(node: string, id: string, offset: number, signal?: AbortSignal) {
    const value = await client.get<CallPage>(`prompts/${part(node)}/versions/${part(id)}/calls?limit=20&offset=${offset}`, { signal, cache: 'no-store' });
    page(value);
    if (value.items.some(i => !i.call || i.call.template_snapshot_id !== id || typeof i.call.call_id !== 'string')) invalid();
    return value;
  },
  async call(id: string, signal?: AbortSignal) {
    const value = await client.get<CallSummary>(`llm-calls/${part(id)}/summary`, { signal, cache: 'no-store' });
    if (!value?.call || value.call.call_id !== id || !value.redaction) invalid();
    return value;
  },
  async raw(id: string, token: string, signal?: AbortSignal) {
    const value = await client.get<{ request_snapshot_id: string; payload: Record<string, unknown> }>(`llm-calls/${part(id)}/request`, { headers: { 'X-Admin-Snapshot-Token': token }, signal, cache: 'no-store' });
    if (!value || typeof value.request_snapshot_id !== 'string' || !value.payload || !Array.isArray(value.payload.messages)) invalid();
    return value;
  },
  async rawResponse(id: string, token: string, signal?: AbortSignal) {
    const value = await client.get<CallResponseContent>(`llm-calls/${part(id)}/response`, { headers: { 'X-Admin-Snapshot-Token': token }, signal, cache: 'no-store' });
    if (!value || value.call_id !== id || !['content', 'raw_body'].includes(value.kind) || typeof value.content !== 'string' || typeof value.truncated !== 'boolean') invalid();
    return value;
  },
};
