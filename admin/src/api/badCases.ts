import { ApiError, createAdminClient } from './client';
import { badCaseCategories, badCaseSeverities, badCaseStatuses } from '../types/badCases';
import type { Attribution, BadCase, BadCaseDraft, BadCasePage, BadCaseTransition } from '../types/badCases';

const client = createAdminClient();
const part = encodeURIComponent;
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
function invalid(): never { throw new ApiError('INVALID_RESPONSE', 'Bad Case 接口返回结构不正确。'); }
function summary(v: unknown) {
  return object(v) && ['case_id','workflow_id','title','created_at','created_by','updated_at'].every(k => typeof v[k] === 'string')
    && badCaseCategories.includes(v.category as never) && badCaseSeverities.includes(v.severity as never)
    && badCaseStatuses.includes(v.status as never) && Number.isInteger(v.sequence);
}
export function isBadCase(v: unknown): v is BadCase {
  if (!object(v) || v.schema_version !== 'bad-case-v1' || !summary({ ...v, updated_at: v.created_at }) || typeof v.observed !== 'string' || typeof v.expected !== 'string') return false;
  if (typeof v.evidence_intact !== 'boolean' || !Array.isArray(v.events) || !v.events.length) return false;
  if (!v.events.every(e => object(e) && Number.isInteger(e.sequence) && badCaseStatuses.includes(e.status as never) && typeof e.annotator === 'string' && typeof e.note === 'string')) return false;
  const e = v.evidence;
  return object(e) && e.schema_version === 'bad-case-evidence-v1' && object(e.business_lifecycle) && Array.isArray(e.nodes) && Array.isArray(e.llm_calls) && object(e.replay_refs);
}
async function checked(value: Promise<unknown>) { const v = await value; if (!isBadCase(v)) invalid(); return v; }
const headers = (token: string) => (token ? { 'X-Admin-Annotation-Token': token } : undefined);

export const badCaseApi = {
  async list(query: string, signal?: AbortSignal) {
    const value = await client.get<BadCasePage>('bad-cases?' + query, { signal, cache: 'no-store' });
    if (!value || value.schema_version !== 'bad-case-page-v1' || !Array.isArray(value.items) || !Number.isInteger(value.total) || !value.items.every(summary)) invalid();
    return value;
  },
  get(id: string, signal?: AbortSignal) { return checked(client.get(`bad-cases/${part(id)}`, { signal, cache: 'no-store' })); },
  create(draft: BadCaseDraft, token: string) { return checked(client.post('bad-cases', draft, { headers: headers(token) })); },
  transition(id: string, change: BadCaseTransition, token: string) { return checked(client.post(`bad-cases/${part(id)}/events`, change, { headers: headers(token) })); },
  attribute(id:string,body:Attribution&{annotator:string;expected_sequence:number},token:string){return checked(client.post(`bad-cases/${part(id)}/attribution`,body,{headers:headers(token)}));},
  saveRepairDraft(id:string,body:{base_snapshot_id:string;system_prompt:string;expected_sequence:number},token:string){return client.post<{template_snapshot_id:string}>(`bad-cases/${part(id)}/repair-draft`,body,{headers:headers(token)});},
  completeRepair(id:string,body:{template_snapshot_id:string;annotator:string;note:string;expected_sequence:number},token:string){return checked(client.post(`bad-cases/${part(id)}/repair-completion`,body,{headers:headers(token)}));},
};

export function writeErrorText(error: unknown) {
  const status = error instanceof ApiError ? error.status : undefined;
  const code = error instanceof ApiError ? error.serverCode : undefined;
  if(code==='BAD_CASE_REPAIR_NO_CHANGE')return '请先修改 Prompt，再确认提交修复。';
  if(code==='BAD_CASE_NOT_EDITABLE')return '该问题已关闭，请先重新打开，再提交归因。';
  if(code==='BAD_CASE_REPAIR_NOT_ALLOWED')return '当前归因或状态不允许提交修复，请返回详情重新核对。';
  if(code==='BAD_CASE_REPAIR_VERSION_MISMATCH')return '修复草稿与归因节点不一致，请返回详情重新选择。';
  if (status === 403) return '标注凭证无效或缺失。';
  if (status === 503) return '服务端未配置标注凭证（INSIGHTFLOW_ADMIN_ANNOTATION_TOKEN），Admin 当前只读。';
  if (status === 409) return '该 Bad Case 已被他人更新，请刷新后再提交。';
  if (status === 404) return 'Workflow 或 Bad Case 不存在。';
  if (status === 422) return '输入不符合要求，请检查必填项与长度；状态未变化时需填写备注。';
  return error instanceof Error ? error.message : '保存失败。';
}
