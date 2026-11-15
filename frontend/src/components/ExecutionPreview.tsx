import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ExecutionResultV1 } from '../types/contracts';
export function ExecutionPreview({executionId, sessionId}: {executionId: string; sessionId: string}) {
  const [result, setResult] = useState<ExecutionResultV1 | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {let alive = true; api.execution(executionId, sessionId).then(r => {if(alive) setResult(r);}).catch(e => {if(alive) setError(e.message);}); return () => {alive = false;};}, [executionId, sessionId]);
  return <section className="plan-card execution-preview" aria-label="真实执行结果"><h3>真实执行结果</h3><p>{executionId}</p>{error && <p role="alert">{error}</p>}
    {result && <><p>状态：{result.execution_status} · 计划 v{result.plan_version} · 审批 {result.approval_id}</p>
    {result.tasks.map(task => <div key={task.task_id}><h4>{task.task_id} · {task.status} · {task.row_count ?? 0} 行</h4>
      {task.failure_reason && <p>{task.failure_reason}</p>}{task.result && <><div className="result-scroll"><table><thead><tr>{task.result.columns.map(c => <th key={c.field}>{c.label}</th>)}</tr></thead>
      <tbody>{task.result.rows.map((r, i) => <tr key={i}>{task.result!.columns.map(c => <td key={c.field}>{String(r[c.field] ?? '—')}</td>)}</tr>)}</tbody></table></div>
      {task.result.truncated && <p>当前显示预览，完整结果共 {task.result.total_result_rows} 行。</p>}</>}</div>)}
      <details><summary>ExecutionResult 与步骤记录</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></>}
  </section>;
}
