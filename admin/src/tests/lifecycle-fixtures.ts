/** Explicit UI fixtures; never used as a production API fallback. */
import type { LifecycleReadModel } from '../types/lifecycle';
export function lifecycleFixture(): LifecycleReadModel {
  return {
    schema_version: 'lifecycle-read-v1',
    business_lifecycle: { status: 'succeeded', execution_status: 'success', report_generation_status: 'completed', report_status: 'complete', goal_coverage: 'complete', report_delivery: 'delivered' },
    activity: 'finished', reason_codes: ['trace_not_collected'],
    source_refs: { session_id: 'session_fixture', session_revision: 12, dataset_id: 'dataset_fixture', dataset_version: 'a'.repeat(64), plan_id: 'plan_fixture', plan_version: 1, validation_version: '1.0', approval_id: 'approval_fixture', execution_id: 'exec_fixture', report_attempt: 2, report_id: 'report_fixture', workflow_run_id: null, report_run_id: null },
    collection: { availability: 'not_collected', integrity: 'unknown', capture_scope: null, root_status: null, root_business_revision: null, report_trace_status: null, observed_spans: [], event_count: 0, report_attempt_history: 'not_guaranteed' },
    consistency: { status: 'consistent', business_snapshot: 'transactional', cross_store_snapshot: 'non_atomic', revision_rechecked: true, issues: [] },
  };
}
