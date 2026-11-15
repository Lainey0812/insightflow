import type { Metadata, TraceSpan } from '../../types/traces';

export const traceStatuses = ['success', 'error', 'running', 'skipped', 'suspended'] as const;
export type TraceStatus = typeof traceStatuses[number];
export const traceStatusLabels: Record<TraceStatus, string> = { success: '成功', error: '错误', running: '运行中', skipped: '跳过', suspended: '暂停' };
const storedGroups: Record<TraceStatus, readonly string[]> = {
  success: ['complete', 'succeeded'],
  error: ['failed', 'partial', 'unavailable', 'error'],
  running: ['running', 'queued'],
  skipped: ['skipped'],
  suspended: ['interrupted', 'waiting_input', 'waiting_approval', 'cancelled'],
};
export function traceStatus(stored: string): TraceStatus {
  const found = traceStatuses.find(status => stored === status || storedGroups[status].includes(stored));
  return found ?? 'error';
}
export const nodeTypes = { llm: 'LLM', tool: 'Tool', condition: 'Condition', router: 'Router', rag: 'RAG' } as const;
const nodeTypeByName: Record<string, keyof typeof nodeTypes> = {
  intent_parser: 'llm', analysis_planner: 'llm', insight_generator: 'llm',
  plan_validator: 'condition', fact_validator: 'condition',
  data_profiler: 'tool', evidence_builder: 'tool', report_assembler: 'tool', report_persistence: 'tool',
};
export function nodeType(name: string): keyof typeof nodeTypes | null { return nodeTypeByName[name] ?? null; }
export const nodeLabels: Record<string, string> = { data_profiler: '数据画像', intent_parser: '需求理解', analysis_planner: '分析规划', plan_validator: '计划校验', evidence_builder: '证据构建', insight_generator: '洞察生成', fact_validator: '事实校验', report_assembler: '报告组装', report_persistence: '报告保存' };
export const ruleLabels: Record<string, string> = {
  FREE_TEXT_GUARD: '解释或建议触发自由文本事实保护', NUMERIC: '包含需要核实的数值表达', ENGLISH_NUMBER: '包含英文数值表达',
  CAUSAL: '包含需要核实的因果表达', UNSUPPORTED_ASSERTION: '包含尚未验证的统计断言', BUSINESS_ASSERTION: '包含尚未验证的业务判断',
  UNSUPPORTED_BUSINESS_CLAIM: '包含尚未验证的经营判断', UNDEFINED_THRESHOLD: '强度判断缺少阈值依据', COMPLETED_CLAIM: '把未验证内容表述为已完成',
  SAME_METRIC_COMPOSITION: '单条洞察引用的指标或统计范围不兼容', ENDPOINT_NOT_INTERVAL_STABILITY: '首末值不能证明期间稳定',
  UNBOUND_POPULATION_SCOPE: '比例的总体范围没有证据绑定',
};
export function valueText(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未采集';
  if (typeof value === 'string') return value.slice(0, 600);
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) return value.filter(v => typeof v === 'string').slice(0, 80).join('、') || '未采集';
  return '不可用';
}
export function metadata(value: unknown): Metadata { return value && typeof value === 'object' && !Array.isArray(value) ? value as Metadata : {}; }
export function timeText(value: unknown): string {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return '未采集';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}
export function durationText(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '未采集';
  return value < 1000 ? `${value.toFixed(1)} ms` : `${(value / 1000).toFixed(2)} s`;
}
export function flattenSpans(spans: TraceSpan[]): { span: TraceSpan; depth: number; warning?: string }[] {
  const ids = new Set(spans.map(s => s.span_id)), seen = new Set<string>();
  const result: { span: TraceSpan; depth: number; warning?: string }[] = [];
  const visit = (span: TraceSpan, depth: number, warning?: string) => {
    if (seen.has(span.span_id)) return;
    seen.add(span.span_id); result.push({ span, depth: Math.min(depth, 8), warning });
    spans.filter(s => s.parent_span_id === span.span_id).forEach(child => visit(child, depth + 1));
  };
  spans.filter(s => !s.parent_span_id || !ids.has(s.parent_span_id)).forEach(s => visit(s, 0, s.parent_span_id ? '父节点未采集' : undefined));
  spans.filter(s => !seen.has(s.span_id)).forEach(s => visit(s, 0, '父子关系异常，按现有记录展示'));
  return result;
}
