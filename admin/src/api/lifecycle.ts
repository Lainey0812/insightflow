import { ApiError, createAdminClient } from './client';
import { traceStatuses } from '../features/traces/presentation';
import { lifecycleActivities, lifecycleReasons, lifecycleStatuses } from '../types/lifecycle';
import type { LifecycleReadModel } from '../types/lifecycle';

const client = createAdminClient();
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const member = (value: unknown, options: readonly unknown[]) => options.includes(value);
const nullableText = (value: unknown) => value === null || typeof value === 'string';
const integer = (value: unknown, min = 0) => typeof value === 'number' && Number.isInteger(value) && value >= min;
const nullableInteger = (value: unknown, min = 0) => value === null || integer(value, min);
const reasons = (value: unknown) => Array.isArray(value) && value.every(item => member(item, lifecycleReasons));

export function isLifecycle(value: unknown, sessionId: string): value is LifecycleReadModel {
  if (!object(value) || value.schema_version !== 'lifecycle-read-v1') return false;
  const b = value.business_lifecycle, r = value.source_refs, c = value.collection, k = value.consistency;
  return object(b) && object(r) && object(c) && object(k) &&
    member(b.status, lifecycleStatuses) && member(value.activity, lifecycleActivities) && reasons(value.reason_codes) &&
    member(b.execution_status, [null, 'running', 'success', 'partial_success', 'failed']) &&
    member(b.report_generation_status, [null, 'queued', 'generating', 'completed', 'failed', 'unavailable']) &&
    member(b.report_status, [null, 'complete', 'partial', 'unavailable']) && member(b.goal_coverage, [null, 'complete', 'partial', 'blocked']) &&
    member(b.report_delivery, ['delivered', 'not_delivered', 'unknown']) && r.session_id === sessionId && nullableInteger(r.session_revision) &&
    ['dataset_id', 'dataset_version', 'plan_id', 'validation_version', 'approval_id', 'execution_id', 'report_id', 'workflow_run_id', 'report_run_id'].every(key => nullableText(r[key])) &&
    nullableInteger(r.plan_version, 1) && nullableInteger(r.report_attempt, 1) &&
    member(c.availability, ['available', 'not_collected', 'unavailable', 'unknown']) && member(c.integrity, ['incomplete', 'unknown']) &&
    ['capture_scope', 'root_status', 'report_trace_status'].every(key => nullableText(c[key])) && nullableInteger(c.root_business_revision) &&
    integer(c.event_count) && c.report_attempt_history === 'not_guaranteed' && Array.isArray(c.observed_spans) &&
    c.observed_spans.every(span => object(span) && typeof span.span_id === 'string' && typeof span.run_id === 'string' && typeof span.node === 'string' &&
      nullableText(span.node_key) && nullableInteger(span.node_attempt, 1) && member(span.status, traceStatuses)) &&
    member(k.status, ['consistent', 'unknown', 'inconsistent']) && (k.status === 'consistent' || b.status === 'unknown') && member(k.business_snapshot, ['transactional', 'unavailable']) &&
    k.cross_store_snapshot === 'non_atomic' && typeof k.revision_rechecked === 'boolean' && reasons(k.issues);
}
export const lifecycleApi = {
  async get(sessionId: string, signal?: AbortSignal): Promise<LifecycleReadModel> {
    const value: unknown = await client.get('workflows/' + encodeURIComponent(sessionId) + '/lifecycle', { signal, cache: 'no-store' });
    if (!isLifecycle(value, sessionId)) throw new ApiError('INVALID_RESPONSE', '生命周期接口返回结构不正确。');
    return value;
  },
};
