import { useState } from 'react';
import type { Session } from '../types/contracts';
import { api } from '../api/client';

export function PlanImport({session, busy, onSave}: {session: Session; busy: boolean; onSave: (action: () => Promise<Session>) => void}) {
  const [value, setValue] = useState(() => JSON.stringify({
    plan: {plan_id: crypto.randomUUID(), plan_version: 1, ...session.dataset_ref,
      core_requirements: [{requirement_id: 'C01', description: session.user_goal}], tasks: []},
    intent: {analysis_mode: session.analysis_mode, next_action: 'proceed',
      analysis_goal: {analysis_object: session.file.name, business_goal: session.user_goal, decision_goal: null},
      constraints: {time_range: null, filters: [], metric_requirements: [], analysis_limits: []}, uncertainties: [], clarification_questions: []},
  }, null, 2));
  const [error, setError] = useState('');
  return <section className="plan-card plan-import"><h3>提交真实结构化计划</h3>
    <p>当前未连接计划模型。请填写 AnalysisPlan 的任务和完整意图，保留原始业务目标，并如实列出约束与不确定性。空任务模板不能执行。</p>
    <details><summary>真实字段与画像</summary><pre>{JSON.stringify(session.profile, null, 2)}</pre></details>
    <label>计划与意图 JSON<textarea aria-label="计划与意图 JSON" value={value} onChange={e => setValue(e.target.value)} rows={18} disabled={busy}/></label>
    {error && <p role="alert">{error}</p>}
    <button className="primary-button" disabled={busy} onClick={() => {try {const payload = JSON.parse(value); setError(''); onSave(() => api.savePlan(session, payload));} catch {setError('请输入有效的 JSON。');}}}>保存并调用 Validator</button>
  </section>;
}
