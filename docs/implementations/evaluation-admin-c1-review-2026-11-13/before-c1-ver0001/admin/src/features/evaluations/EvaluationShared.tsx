import { Link } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { TraceError } from '../traces/AccessPanel';
import type {
  Attribution, CaseState, DatasetType, DiscoveryWarning, E2EVerdict, ExecutionStatus, IntegrityStatus, Provenance, Rate,
  Relation, RunStatus, RunType, TrustLabel, Verdict,
} from '../../types/evaluations';

type Tone = 'ok' | 'bad' | 'warn' | 'neutral' | 'info';

export const NOT_RECORDED = '未记录';

export const runTypeLabels: Record<RunType, string> = { golden: 'Golden', tc_regression: 'TC 回归' };
export const datasetTypeLabels: Record<DatasetType, string> = { golden: 'Golden', tc: 'TC 典型用例' };
export const lifecycleLabels: Record<RunStatus, string> = { FINISHED: '运行已结束', INCOMPLETE: '运行未完成' };
export const integrityLabels: Record<IntegrityStatus, string> = {
  VERIFIED: '证据已校验', INVALID: '证据校验失败', INCOMPLETE: '证据不完整', UNVERIFIED: '未校验',
};
export const integrityExplanations: Record<IntegrityStatus, string> = {
  VERIFIED: '最终 manifest 列出的文件都在运行目录内，哈希与记录一致。',
  INVALID: '存在 manifest，但有文件缺失、被改动、无法读取或越出运行目录。',
  INCOMPLETE: '运行没有写完最终 manifest，结果只代表已记录的部分。',
  UNVERIFIED: '历史运行格式没有 manifest，记录按原样展示，无法校验是否被改动。未校验不等于证据损坏。',
};
export const executionLabels: Record<ExecutionStatus, string> = {
  PENDING: '待执行', RUNNING: '执行中', WAITING_APPROVAL: '等待审批', COMPLETED: '执行完成', BLOCKED: '受阻',
  FAILED: '执行失败', TIMEOUT: '超时', CANCELLED: '已取消',
};
export const verdictLabels: Record<E2EVerdict, string> = {
  PASS: '通过', FAIL: '未通过', NOT_EVALUATED: '未评测', EVALUATOR_ERROR: '评测器异常', INFRA_ERROR: '基础设施错误',
};
export const gateLabels: Record<string, string> = {
  infrastructure: '基础设施', task_condition: '任务条件', required_evaluator: '必选评测器', all_gates: '全部门槛',
};
export const attributionLabels: Record<Attribution, string> = {
  none: '无失败', agent_execution: 'Agent 执行', business_quality: '业务约束', evaluator_error: '评测器异常',
  evaluation_infrastructure: '评测基础设施', undetermined: '无法判定', evidence_integrity: '证据完整性', not_executed: '未执行',
};
export const caseStateLabels: Record<CaseState, string> = { present: '已记录', missing: '缺失', not_started: '未开始', unreadable: '无法读取' };
export const provenanceLabels: Record<Provenance, string> = { recorded: '运行器记录', legacy_projection: '历史格式投影' };
export const relationLabels: Record<Relation, string> = {
  hash_match: '哈希一致', hash_mismatch: '哈希不同', weak_path: '仅目录关联，未校验哈希',
};
export const relationExplanations: Record<Relation, string> = {
  hash_match: '运行记录的数据集哈希与当前文件一致。',
  hash_mismatch: '运行记录的是另一份内容的哈希，说明运行时使用的数据集版本不同；不代表数据损坏。',
  weak_path: '运行没有记录数据集哈希，只能按所在目录关联，无法确认使用的是哪一版内容。',
};
export const trustLabelText: Record<TrustLabel, string> = {
  verified: '可信', partial_verified: '局部统计', unverified: '不可信：历史记录无法校验', incomplete: '仅覆盖已记录 Case', none: '不报告',
};

const lifecycleTone: Record<RunStatus, Tone> = { FINISHED: 'neutral', INCOMPLETE: 'warn' };
const integrityTone: Record<IntegrityStatus, Tone> = { VERIFIED: 'ok', INVALID: 'bad', INCOMPLETE: 'warn', UNVERIFIED: 'info' };
const executionTone: Record<ExecutionStatus, Tone> = {
  PENDING: 'neutral', RUNNING: 'neutral', WAITING_APPROVAL: 'warn', COMPLETED: 'ok', BLOCKED: 'warn', FAILED: 'bad', TIMEOUT: 'bad', CANCELLED: 'neutral',
};
const verdictTone: Record<E2EVerdict, Tone> = { PASS: 'ok', FAIL: 'bad', NOT_EVALUATED: 'neutral', EVALUATOR_ERROR: 'warn', INFRA_ERROR: 'warn' };
const relationTone: Record<Relation, Tone> = { hash_match: 'ok', hash_mismatch: 'warn', weak_path: 'neutral' };
const trustTone: Record<TrustLabel, Tone> = { verified: 'ok', partial_verified: 'warn', unverified: 'info', incomplete: 'warn', none: 'bad' };

function Badge({ tone, kind, children }: { tone: Tone; kind: string; children: string }) {
  return <span className={`ev-badge ev-${tone}`} data-kind={kind}>{children}</span>;
}
function Missing({ text = NOT_RECORDED }: { text?: string }) {
  return <span className="ev-missing">{text}</span>;
}

export function LifecycleBadge({ status }: { status: RunStatus }) {
  return <Badge tone={lifecycleTone[status]} kind="lifecycle">{lifecycleLabels[status]}</Badge>;
}
export function IntegrityBadge({ status }: { status: IntegrityStatus | null }) {
  return status ? <Badge tone={integrityTone[status]} kind="integrity">{integrityLabels[status]}</Badge> : <Missing />;
}
export function ExecutionBadge({ status }: { status: ExecutionStatus | null }) {
  return status ? <Badge tone={executionTone[status]} kind="execution">{executionLabels[status]}</Badge> : <Missing text="无法确定" />;
}
export function E2EBadge({ verdict }: { verdict: E2EVerdict | null }) {
  return verdict ? <Badge tone={verdictTone[verdict]} kind="e2e">{'E2E ' + verdictLabels[verdict]}</Badge> : <Missing text="无 E2E 结果" />;
}
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <Badge tone={verdictTone[verdict]} kind="evaluator">{verdictLabels[verdict]}</Badge>;
}
export function RelationBadge({ relation }: { relation: Relation }) {
  return <Badge tone={relationTone[relation]} kind="relation">{relationLabels[relation]}</Badge>;
}
export function TrustBadge({ trust }: { trust: TrustLabel }) {
  return <Badge tone={trustTone[trust]} kind="trust">{trustLabelText[trust]}</Badge>;
}
export function FreezeBadge() {
  return <Badge tone="neutral" kind="freeze">未声明冻结</Badge>;
}
export function Recorded({ value }: { value: string | null | undefined }) {
  return value ? <>{value}</> : <Missing />;
}
export function ShortHash({ value }: { value: string | null | undefined }) {
  return value ? <code className="wf-subid" title={value}>{value.slice(0, 12)}…</code> : <Missing />;
}

export function rateText(value: Rate | null): string {
  if (!value) return '不报告';
  if (value.denominator === 0 || value.rate === null) return '无法计算（分母为 0）';
  return (value.rate * 100).toFixed(1) + '%';
}
export function RateValue({ label, value, trust }: { label: string; value: Rate | null; trust: TrustLabel }) {
  return <div className="ev-metric" aria-label={label}>
    <span className="ev-metric-label">{label}</span>
    <strong>{rateText(value)}</strong>
    <span className="ev-metric-ratio">{value ? `${value.numerator} / ${value.denominator}` : '无分子分母'}</span>
    <TrustBadge trust={trust} />
  </div>;
}

// Repository-relative references are shown; anything that looks like a host path is withheld.
export function safeRef(value: string | null | undefined): string | null {
  if (!value) return null;
  if (/^(\/|~|[A-Za-z]:[\\/]|\\\\)/.test(value) || value.split(/[\\/]/).includes('..')) return null;
  return value;
}
export function safeText(value: string | null | undefined): string {
  return (value || '').replace(/(?:\/Users|\/home|\/private|\/var\/folders|[A-Za-z]:\\)[^\s'"]*/g, '[本地路径已隐藏]')
    .replace(/https?:\/\/\S+/g, '[地址已隐藏]');
}

export function DiscoveryWarnings({ warnings }: { warnings: DiscoveryWarning[] }) {
  if (!warnings.length) return null;
  return <section className="trace-notice trace-warning" aria-label="发现提示"><strong>发现提示（{warnings.length}）</strong>
    <ul className="ev-warning-list">{warnings.map((w, i) => <li key={w.code + (w.entry || '') + i}>
      <code>{w.code}</code>{w.code === 'duplicate_dataset_id' || w.code === 'duplicate_run_id' ? <b> ID 冲突：所有同名来源都已排除，不会任选其一。</b> : null}
      {w.entry ? <span> · {safeText(w.entry)}</span> : null}{w.detail ? <span className="muted"> · {safeText(w.detail)}</span> : null}
    </li>)}</ul></section>;
}

export function Pager({ page, pageSize, total, label, onPage }: { page: number; pageSize: number; total: number; label: string; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const start = total ? (page - 1) * pageSize + 1 : 0;
  return <nav className="wf-pagination" aria-label={label + '分页'}>
    <span>{start}–{Math.min(page * pageSize, total)} / {total} · 第 {page} / {pages} 页</span>
    <button className="secondary-button" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</button>
    <button className="secondary-button" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button>
  </nav>;
}

const conflictTitles: Record<string, string> = {
  EVALUATION_RUN_ID_CONFLICT: '运行 ID 冲突，无法唯一定位',
  EVALUATION_RUN_UNREADABLE: '运行目录存在但无法读取',
  EVALUATION_DATASET_ID_CONFLICT: '数据集 ID 冲突',
};
const conflictBodies: Record<string, string> = {
  EVALUATION_RUN_ID_CONFLICT: '多个配置目录中存在同一运行 ID，或目录名与记录不符。页面不会任选其一展示。',
  EVALUATION_RUN_UNREADABLE: '运行记录损坏或缺少必要文件，无法读取。页面不把它显示为空结果或成功。',
  EVALUATION_DATASET_ID_CONFLICT: '同一数据集 ID 对应多个来源，无法合并为一个版本。页面不会任选其一展示。',
};

export function EvaluationError({ error, resource, retry, back }: {
  error: unknown; resource: string; retry: () => void; back: { to: string; label: string };
}) {
  if (!(error instanceof ApiError) || error.status === 403 || error.status === 503) return <TraceError error={error} resource={resource} retry={retry} />;
  const backLink = <Link className="secondary-button" to={back.to}>{back.label}</Link>;
  if (error.status === 404) return <section className="trace-message" role="alert">
    <h2>{resource}不存在</h2><p>索引中没有这个 ID。它可能不在配置的评测目录中，或 ID 有误。</p>{backLink}</section>;
  if (error.status === 409) {
    const code = error.serverCode || '';
    const hashes = Array.isArray(error.details?.dataset_hashes) ? error.details.dataset_hashes.filter((h): h is string => typeof h === 'string') : [];
    const sources = Array.isArray(error.details?.sources) ? error.details.sources.filter((s): s is string => typeof s === 'string') : [];
    return <section className="trace-message" role="alert">
      <h2>{conflictTitles[code] || resource + '状态冲突'}</h2>
      <p>{conflictBodies[code] || '服务返回冲突，无法唯一确定要展示的记录。'}</p>
      {hashes.length > 0 && <p>冲突来源 {Math.max(sources.length, hashes.length)} 个，内容哈希：{hashes.map(h => <code key={h} className="wf-subid" title={h}>{h.slice(0, 12)}…</code>)}</p>}
      {sources.map(safeRef).filter(Boolean).map(s => <code key={s} className="wf-subid">{s}</code>)}
      {backLink}</section>;
  }
  if (error.status === 422) return <section className="trace-message" role="alert">
    <h2>请求参数无效</h2><p>ID 格式或筛选参数不符合接口要求，服务拒绝了请求。请清除筛选或返回列表。</p>{backLink}</section>;
  if (error.code === 'INVALID_RESPONSE') return <section className="trace-message" role="alert">
    <h2>接口返回结构不正确</h2><p>{resource}的响应与前端契约不一致，页面不展示可能错误的数据。</p><button className="secondary-button" onClick={retry}>重新加载</button></section>;
  return <section className="trace-message" role="alert">
    <h2>无法加载{resource}</h2><p>{error.status ? `服务返回 ${error.status}。` : ''}请求失败，未将失败当作空数据。请稍后重试。</p>
    <button className="secondary-button" onClick={retry}>重新加载</button></section>;
}
