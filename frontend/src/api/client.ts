import type { AnalysisMode, Health, Session, SessionSummary, AnalysisPlanV1, ParsedIntent, PlanVersion, ExecutionResultV1, ReviewPresentation, ReportGeneration, ScopePreview, ScopeTarget } from '../types/contracts';

import type { AnalysisReport, ReportPresentation } from '../types/report';

const BASE = '/api/v1';
export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number) { super(message); }
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if ((path === '/sessions' && (!options?.method || options.method === 'GET')) || path.startsWith('/reports/')) {
    const keys = Object.fromEntries(Object.keys(localStorage).filter(key => key.startsWith('insightflow.access.')).map(key => [key.slice('insightflow.access.'.length), localStorage.getItem(key)]));
    options = {...options, headers: {...options?.headers, 'X-Session-Keys': JSON.stringify(keys)}};
  }
  const sessionId = path.match(/^\/sessions\/([^/]+)/)?.[1];
  const token = sessionId ? localStorage.getItem(`insightflow.access.${sessionId}`) : null;
  if (token) options = {...options, headers: {...options?.headers, 'X-Session-Token': token}};
  let response: Response;
  try { response = await fetch(`${BASE}${path}`, options); }
  catch { throw new ApiError('无法连接后端，请确认服务已启动后重试。', 'NETWORK_ERROR', 0); }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(body?.error?.message ?? '请求失败，请稍后重试。', body?.error?.code ?? 'HTTP_ERROR', response.status);
  if (body?.review_access_token && body?.id) localStorage.setItem(`insightflow.access.${body.id}`, body.review_access_token);
  return body as T;
}
function post<T>(path: string, data: unknown, token?: string | null): Promise<T> {
  return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? {'X-Session-Token': token} : {}) }, body: JSON.stringify(data) });
}
function reportHeaders() {
  return {'X-Session-Keys': JSON.stringify(Object.fromEntries(Object.keys(localStorage)
    .filter(k => k.startsWith('insightflow.access.')).map(k => [k.slice('insightflow.access.'.length), localStorage.getItem(k)])))};
}
export const api = {
  reportExecution: (id: string) => request<ExecutionResultV1>(`/reports/${encodeURIComponent(id)}/execution`),
  generateReport: (executionId: string, sessionId: string, expectedAttempt?: number) => post<ReportGeneration>(
    `/executions/${encodeURIComponent(executionId)}/report`, expectedAttempt ? {expected_attempt: expectedAttempt} : {}, localStorage.getItem(`insightflow.access.${sessionId}`)),
  downloadReport: async (id: string) => {
    const response = await fetch(`${BASE}/reports/${encodeURIComponent(id)}/download`, {headers: reportHeaders()});
    if (!response.ok) throw new Error('报告下载失败，请确认会话仍可访问后重试。');
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a'); a.href = url; a.download = `${id}.html`; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  reportPresentation: (id: string) => request<ReportPresentation>(`/reports/${encodeURIComponent(id)}/presentation`),
  analysisReport: (id: string) => request<AnalysisReport>(`/reports/${encodeURIComponent(id)}`),
  health: () => request<Health>('/health'),
  list: () => request<SessionSummary[]>('/sessions'),
  session: (id: string) => request<Session>(`/sessions/${encodeURIComponent(id)}`),
  create: (file: File, goal: string, mode: AnalysisMode, headerRow = 1) => {
    const data = new FormData(); data.append('file', file); data.append('goal', goal); data.append('mode', mode);
    data.append('header_row', String(headerRow)); data.append('real_workflow', 'true');
    return request<Session>('/sessions', { method: 'POST', body: data });
  },
  revise: (session: Session, instruction: string, removeTaskIds: string[] = []) => post<Session>(`/sessions/${session.id}/plan-revisions`, {
    expected_revision: session.revision, plan_version: session.current_plan_version,
    instruction, remove_task_ids: removeTaskIds, ...(session.review_plan ? {plan_id: session.review_plan.plan_id} : {}),
  }),
  editDirection: (session: Session, taskId: string, stepParams: Record<string, Record<string, unknown>>) => post<Session>(`/sessions/${session.id}/plan-revisions`, {
    expected_revision:session.revision, plan_id:session.review_plan!.plan_id, plan_version:session.review_plan!.plan_version,
    task_edits:[{task_id:taskId,step_params:stepParams}],
  }),
  previewScope: (session:Session,target:ScopeTarget,mode:'exact'|'normalized_contains') => post<ScopePreview>(`/sessions/${session.id}/scope-preview`, {
    expected_revision:session.revision,plan_id:session.review_plan!.plan_id,plan_version:session.review_plan!.plan_version,...target,mode,
  }),
  confirmScope: (session:Session,target:ScopeTarget,mode:'exact'|'normalized_contains',digest:string) => post<Session>(`/sessions/${session.id}/scope-confirmations`, {
    expected_revision:session.revision,plan_id:session.review_plan!.plan_id,plan_version:session.review_plan!.plan_version,...target,mode,preview_digest:digest,
  }),
  clarify: (session: Session, answer: string) => post<Session>(`/sessions/${session.id}/clarifications`, {
    expected_revision: session.revision, answer,
  }),
  reviewAnswer: (session: Session, answer: string) => post<Session>(`/sessions/${session.id}/review-answers`, {
    expected_revision: session.revision, answer,
  }),
  retryPreparation: (session: Session) => post<Session>(`/sessions/${session.id}/retry-preparation`, {expected_revision: session.revision}),
  approve: (session: Session) => post<Session>(`/sessions/${session.id}/approvals`, {
    expected_revision: session.revision, plan_version: session.current_plan_version,
  }),
  execute: (session: Session) => post<Session>(`/sessions/${session.id}/execute`, {
    expected_revision: session.revision, plan_version: session.current_plan_version,
  }),
  savePlan: (session: Session, data: {plan: AnalysisPlanV1; intent: ParsedIntent}) => post<Session>(`/sessions/${session.id}/plans`, {...data, expected_revision: session.revision}),
  versions: (id: string) => request<PlanVersion[]>(`/sessions/${id}/plans`),
  saveAnalysisBasis: (session: Session, rowGrain: string, entityField: string | null) => post<Session>(`/sessions/${session.id}/analysis-basis`, {
    expected_revision:session.revision, plan_id:session.review_plan!.plan_id, plan_version:session.review_plan!.plan_version,
    row_grain:rowGrain, entity_field_id:entityField,
  }),
  review: (id: string) => request<ReviewPresentation>(`/sessions/${id}/review`),
  constraintAudits: (id: string) => request<unknown[]>(`/sessions/${id}/constraint-audits`),
  approvals: (id: string) => request<{approval_id: string; plan_version: number; approved_at: string; execution_ids: string[]}[]>(`/sessions/${id}/approvals`),
  approveReal: (session: Session, warnings: string[]) => {
    const plan = session.review_plan!;
    const key = `insightflow.approval.${session.id}.${plan.plan_version}`;
    let requestId = localStorage.getItem(key);
    if (!requestId) { requestId = crypto.randomUUID(); localStorage.setItem(key, requestId); }
    return post<Session>(`/sessions/${session.id}/approvals`, {
      expected_revision: session.revision, plan_id: plan.plan_id, plan_version: plan.plan_version,
      dataset_id: plan.dataset_id, dataset_version: plan.dataset_version, validation_version: plan.validation_version,
      approval_request_id: requestId, acknowledged_warnings: warnings,
    });
  },
  executeReal: (session: Session) => {
    const plan = session.review_plan!;
    const key = `insightflow.execution.${session.id}.${plan.plan_version}`;
    let requestId = localStorage.getItem(key);
    if (!requestId) { requestId = crypto.randomUUID(); localStorage.setItem(key, requestId); }
    return post<ExecutionResultV1>('/executions', {session_id: session.id, plan_id: plan.plan_id,
      plan_version: plan.plan_version, execution_request_id: requestId}, localStorage.getItem(`insightflow.access.${session.id}`));
  },
  execution: (id: string, sessionId: string) => request<ExecutionResultV1>(`/executions/${encodeURIComponent(id)}`, {headers: {'X-Session-Token': localStorage.getItem(`insightflow.access.${sessionId}`) ?? ''}}),
  reportUrl: (id: string, action: 'preview' | 'download') => `${BASE}/sessions/${encodeURIComponent(id)}/report/${action}`,
};
