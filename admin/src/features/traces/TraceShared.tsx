import type { Metadata, RunManifest } from '../../types/traces';
import { traceStatus, traceStatusLabels, valueText } from './presentation';
import { PromptRunLinks } from '../prompts/PromptShared';

export function StatusBadge({ status }: { status: string }) {
  const view = traceStatus(status);
  return <span className={`status-badge status-${view}`} title={status === view ? undefined : status}>{traceStatusLabels[view]}</span>;
}
export function KeyValues({ source, fields }: { source: Metadata; fields: Record<string, string> }) {
  return <dl className="trace-keyvalues">{Object.entries(fields).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{valueText(source[key])}</dd></div>)}</dl>;
}
export function CoverageNotice({ degraded, incomplete, scope }: { degraded?: boolean; incomplete?: boolean; scope?: string }) {
  return <div className={`trace-notice ${degraded || incomplete ? 'trace-warning' : ''}`} role="note">
    {degraded || incomplete ? '检测到追踪缺口或采集器降级。' : ''} {scope === 'workflow_preparation' ? '当前 Run 仅覆盖 Workflow 准备阶段' : scope && scope !== 'report_generation' ? '当前 Run 的采集范围未完整确认' : '当前仅覆盖报告生成尝试'}；记录缺失不代表业务没有运行或没有失败。</div>;
}
const hashes = ['services/analysis_report.py', 'workflow/reporting.py', 'reporting/evidence.py', 'reporting/fact_validation.py', 'reporting/claims.py', 'reporting/prompt.py', 'reporting/selection.py', 'reporting/contracts.py', 'reporting/visualization.py', 'domain/analysis_report.py', 'domain/tracing.py', 'observability/recorder.py', 'observability/provenance.py', 'observability/snapshots.py', 'llm/compatible_provider.py'];
export function ManifestView({ manifest }: { manifest?: RunManifest }) {
  return <details className="trace-card manifest-panel"><summary>RunManifest · 本次运行的版本与关联</summary>
    {!manifest && <p>历史记录未采集 RunManifest。</p>}
    <p className="muted">不可变的运行时记录。unknown 表示当时未采集，不使用当前配置填补。</p>
    <PromptRunLinks refs={manifest?.prompt_template_snapshots} />
    <KeyValues source={{ scope: manifest?.capture_scope ?? 'unknown', commit: manifest?.git?.commit ?? 'unknown', dirty: manifest?.git?.dirty ?? 'unknown' }} fields={{ scope: '采集范围', commit: 'Git Commit', dirty: 'Git 工作区有修改' }} />
    <KeyValues source={Object.fromEntries(['dataset','profile','user_goal','intent','approved_plan','execution'].map(k => [k, manifest?.input_sha256?.[k] ?? 'unknown']))} fields={{ dataset: '数据集指纹', profile: '画像指纹', user_goal: '用户目标指纹', intent: 'Intent 指纹', approved_plan: '审批快照指纹', execution: '执行结果指纹' }} />
    <KeyValues source={Object.fromEntries(['session_id','execution_id','approval_id','dataset_id','dataset_version','plan_id','plan_version'].map(k => [k, manifest?.bindings?.[k] ?? 'unknown']))} fields={{ session_id: '会话 ID', execution_id: '执行 ID', approval_id: '审批 ID', dataset_id: '数据集 ID', dataset_version: '数据集版本', plan_id: '计划 ID', plan_version: '计划版本' }} />
    <KeyValues source={Object.fromEntries(['prompt_version','generation_version','schema_version','validation_version','registry_version','prompt_sha256','fact_validator_sha256'].map(k => [k, manifest?.versions?.[k] ?? 'unknown']))} fields={{ prompt_version: 'Prompt 版本', generation_version: '生成策略', schema_version: '报告 Schema', validation_version: 'Validator 版本', registry_version: 'Registry 版本', prompt_sha256: 'Prompt 内容指纹', fact_validator_sha256: '报告事实校验器指纹' }} />
    <KeyValues source={Object.fromEntries(['provider','model','timeout_seconds','enable_thinking','temperature','top_p','usage','endpoint_sha256'].map(k => [k, manifest?.model_config_snapshot?.[k] ?? 'unknown']))} fields={{ provider: '配置 Provider', model: '配置模型', timeout_seconds: '超时（秒）', enable_thinking: '思考配置', temperature: 'temperature', top_p: 'top_p', usage: 'Token 用量', endpoint_sha256: '模型端点指纹' }} />
    <details><summary>实现文件指纹</summary><KeyValues source={Object.fromEntries(hashes.map(k => [k, manifest?.source_sha256?.[k] ?? 'unknown']))} fields={Object.fromEntries(hashes.map(key => [key, key]))} /></details>
    <p className="muted">temperature / top_p 为 unknown 时没有已知采样默认值。源码 SHA 来自运行时磁盘，不替代 Git Commit。受控投影仅保留数值、引用和文本哈希；不保留完整原始内容。</p>
  </details>;
}
