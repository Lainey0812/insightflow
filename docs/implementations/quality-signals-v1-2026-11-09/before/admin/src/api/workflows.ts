import { ApiError, createAdminClient } from './client';
import { businessStatuses, failureCategories } from '../types/workflows';
import type { WorkflowView, WorkflowPage } from '../types/workflows';
const client = createAdminClient();
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const texts = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const numeric = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0;
export function isWorkflow(v: unknown): v is WorkflowView {
  if (!object(v) || v.schema_version !== 'workflow-observability-v1' || !['workflow_id','session_id','root_run_id','created_at'].every(k => typeof v[k] === 'string')) return false;
  if (!object(v.business_lifecycle) || !businessStatuses.includes(v.business_lifecycle.status as never) || !object(v.collection) || !['observed','incomplete'].includes(String(v.collection.status))) return false;
  if (!Array.isArray(v.collection.findings) || !v.collection.findings.every(f => object(f) && ['not_executed','executed_trace_missing','observation_incomplete','inconsistent','unknown'].includes(String(f.category)) && typeof f.code === 'string' && texts(f.evidence_refs))) return false;
  if (!object(v.source_refs) || !object(v.consistency) || !['consistent','inconsistent','unknown'].includes(String(v.consistency.status)) || !texts(v.consistency.issues) || !texts(v.reason_codes) || !(v.duration_ms === null || numeric(v.duration_ms))) return false;
  if (v.failure !== undefined && v.failure !== null) {
    const f = v.failure;
    if (!object(f) || !failureCategories.includes(f.category as never) || !['code','label','hint'].every(k => typeof f[k] === 'string')
      || !['node','business','report_generation'].includes(String(f.source)) || !object(f.inputs)) return false;
  }
  if (v.trace !== undefined && v.trace !== null) {
    const t = v.trace;
    if (!object(t) || t.workflow_id !== v.workflow_id || t.root_run_id !== v.root_run_id || !['nodes','events','llm_calls','plan_versions','approvals','executions','report_generations','reports','report_artifact_runs'].every(k => Array.isArray(t[k]))) return false;
    if (!(t.nodes as unknown[]).every(n => object(n) && typeof n.span_id === 'string' && n.run_id === v.root_run_id && typeof n.name === 'string' && typeof n.status === 'string' && (n.duration_ms === null || numeric(n.duration_ms)))) return false;
    if (!(t.root === null || (object(t.root) && t.root.run_id === v.root_run_id))) return false;
    if (!(t.events as unknown[]).every(e => object(e) && typeof e.event_id === 'string' && e.run_id === v.root_run_id && typeof e.event_type === 'string')) return false;
    if (!(t.llm_calls as unknown[]).every(c => object(c) && typeof c.call_id === 'string' && typeof c.node_id === 'string' && (c.span_id === null || typeof c.span_id === 'string') && numeric(c.call_sequence) && numeric(c.retry_index) && (c.duration_ms === null || numeric(c.duration_ms)))) return false;
    const ids=(t.nodes as {span_id:string}[]).map(n=>n.span_id);
    if (new Set(ids).size !== ids.length) return false;
  }
  return true;
}
export const workflowApi = {
  async list(query: string, signal?: AbortSignal): Promise<WorkflowPage> {
    const v: unknown = await client.get('workflow-observability' + (query ? '?' + query : ''), { signal, cache: 'no-store' });
    if (!object(v) || v.schema_version !== 'workflow-observability-page-v1' || !Array.isArray(v.items) || !v.items.every(isWorkflow) || !numeric(v.total) || !numeric(v.limit) || !numeric(v.offset)) throw new ApiError('INVALID_RESPONSE','Workflow 列表结构不正确。');
    return v as unknown as WorkflowPage;
  },
  async get(id: string, signal?: AbortSignal): Promise<WorkflowView> {
    const v: unknown = await client.get('workflow-observability/' + encodeURIComponent(id), { signal, cache: 'no-store' });
    if (!isWorkflow(v) || v.workflow_id !== id || v.trace === undefined) throw new ApiError('INVALID_RESPONSE','Workflow 详情结构或归属不正确。');
    return v;
  },
};
