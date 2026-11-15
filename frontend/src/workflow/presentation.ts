/** UI projection of saved business records; no simulated steps or Trace completion. */
import type { ReportGeneration, Session, SessionStatus } from '../types/contracts';

export const activeStatuses: readonly SessionStatus[] = ['CREATED', 'PREPARING', 'PROFILING', 'PARSING_INTENT', 'PLANNING', 'VALIDATING', 'RUNNING'];

export function currentReportGeneration(session: Session | null): ReportGeneration | undefined {
  if (!session || session.workflow_kind !== 'real_v1' || session.current_plan_version === null ||
      session.approved_plan_version !== session.current_plan_version) return undefined;
  // Engine appends IDs only after accepting an execution. A new unapproved plan cannot inherit this activity.
  const acceptedId = session.engine_execution_ids?.at(-1);
  return acceptedId ? session.report_generations?.find(record => record.execution_id === acceptedId && record.session_id === session.id) : undefined;
}

export function isWorkflowRunning(session: Session | null): boolean {
  if (!session) return false;
  const report = currentReportGeneration(session);
  return activeStatuses.includes(session.status) || session.review_status === 'executing' ||
    session.review_status === 'validating' || report?.status === 'queued' || report?.status === 'generating';
}

export function workflowStep(session: Session): { title: string; description: string; running: boolean } {
  const report = currentReportGeneration(session);
  if (session.status === 'COMPLETED' && report) {
    const reportSteps = {
      queued: { title: '报告已排队', description: '计算结果已保存，正在等待报告生成。' },
      generating: { title: '整理分析报告', description: '计算结果已保存，正在整理证据与业务洞察。' },
      completed: { title: '报告已生成', description: '可在对话中预览报告，核对发现、依据和未完成事项。' },
      failed: { title: '报告生成未完成', description: '计算结果仍然保留，可在下方查看或重试报告。' },
      unavailable: { title: '暂无可用报告', description: '请查看已保存的计算结果和未完成事项。' },
    };
    return { ...reportSteps[report.status], running: isWorkflowRunning(session) };
  }
  const steps: Record<SessionStatus, { title: string; description: string }> = {
    CREATED: { title: '已提交，等待开始', description: '需求与文件已保存，请等待处理。' },
    PREPARING: { title: '准备中', description: '正在准备本次分析所需的信息。' },
    PROFILING: { title: '数据画像中', description: '正在读取表格，检查字段与数据质量。' },
    PARSING_INTENT: { title: '理解需求中', description: '正在结合字段信息理解你的业务问题。' },
    PLANNING: { title: '生成计划中', description: '正在整理分析方向，完成后请你确认方案。' },
    VALIDATING: { title: '校验计划中', description: '正在核对分析条件与可执行的统计操作。' },
    WAITING_FOR_CLARIFICATION: { title: '等待补充需求', description: '请在下方回复问题，补充后继续规划。' },
    AWAITING_APPROVAL: { title: '等待确认方案', description: '核对下方分析方向；确认前不会执行计算。' },
    APPROVED: { title: '方案已确认', description: '计算尚未启动，请从方案中开始已确认的分析。' },
    RUNNING: { title: '正在执行分析', description: '正在按照已批准的方案计算，请等待结果。' },
    COMPLETED: { title: '计算结果已保存', description: '请在下方查看报告状态与原始计算结果。' },
    FAILED: { title: '本次处理未完成', description: '请查看失败原因，已有记录仍然保留。' },
  };
  return { ...steps[session.status], running: isWorkflowRunning(session) };
}
