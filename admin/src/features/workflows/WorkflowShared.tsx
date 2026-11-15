import type { BusinessStatus, FailureCategory, FindingCategory, QualityLevel, QualityStage, WorkflowFailure, WorkflowQuality, WorkflowView } from '../../types/workflows';
import { qualityStages } from '../../types/workflows';
import type { Metadata } from '../../types/traces';
import { valueText } from '../traces/presentation';
export const businessLabels: Record<BusinessStatus,string> = { created:'已创建',running:'进行中',waiting_input:'等待补充',waiting_approval:'等待审核',succeeded:'分析已完成',partially_succeeded:'部分完成',failed:'分析失败',interrupted:'执行中断',unknown:'尚无法判断' };
export const findingLabels: Record<FindingCategory,string> = { not_executed:'明确未执行',executed_trace_missing:'已执行，Trace 缺失',observation_incomplete:'观测不完整',inconsistent:'业务与关联不一致',unknown:'尚无法判断' };
export const failureLabels: Record<FailureCategory,string> = { file_input:'文件或解析参数',data_content:'数据内容',model_service:'模型服务',model_output:'模型输出不合规',capacity:'容量限制',plan_blocked:'规划或校验阻断',interrupted:'进程中断',unclassified:'未归类' };
const inputLabels: Record<string,string> = { input_header_row:'表头行',input_sheet_name:'工作表',input_encoding:'编码',input_delimiter:'分隔符',input_file_extension:'文件类型',input_file_size_bytes:'文件大小（字节）',input_query_chars:'需求字数',input_clarification_count:'澄清答复数',input_field_count:'字段数',input_dataset_id:'数据集',input_dataset_version:'数据集版本' };
const sourceLabels: Record<WorkflowFailure['source'],string> = { node:'节点记录',business:'业务状态（无失败节点记录）',report_generation:'报告生成记录（无失败节点记录）' };
export function BusinessBadge({ status }: { status: BusinessStatus }) { return <span className={`wf-business wf-business-${status}`}>{businessLabels[status]}</span>; }
export function CollectionBadge({ value }: { value: WorkflowView['collection'] }) { return <span className={`wf-collection ${value.status === 'observed' ? '' : 'wf-collection-gap'}`}>{value.status === 'observed' ? '已采集' : '采集有缺口'}</span>; }
export function inputEntries(attrs: Metadata) { return Object.entries(attrs).filter(([k]) => k.startsWith('input_')); }
export function InputSummary({ attrs }: { attrs: Metadata }) {
  const entries = inputEntries(attrs);
  if (!entries.length) return <p className="muted">未采集输入摘要（早于本功能的记录或该节点不记录输入）。</p>;
  return <dl className="wf-refs wf-inputs">{entries.map(([k,v]) => <div key={k}><dt>{inputLabels[k] || k}</dt><dd><code>{v === null ? '未指定' : valueText(v)}</code></dd></div>)}</dl>;
}
export function FailureCard({ failure }: { failure: WorkflowFailure }) {
  return <section className="wf-failure" aria-labelledby="failure-heading"><header><h2 id="failure-heading">失败定位</h2><span className={`wf-failure-tag wf-failure-${failure.category}`}>{failureLabels[failure.category]}</span></header>
    <dl className="wf-node-facts"><div><dt>失败位置</dt><dd>{failure.node_name ? <a className="wf-link" href={'#node-'+failure.span_id}>{failure.node_name}</a> : sourceLabels[failure.source]}</dd></div><div><dt>错误代码</dt><dd><code>{failure.code}</code></dd></div></dl>
    <p className="wf-failure-hint">{failure.hint}</p>
    {failure.source === 'node' && <><h3>失败节点输入摘要</h3><InputSummary attrs={failure.inputs}/></>}
    <p className="muted">按错误代码确定性归类，不读取原始数据或模型文本；不自动判定根因。</p></section>;
}
const stageLabels: Record<QualityStage,string> = { understanding:'需求理解',planning:'分析规划',review:'人工审核',execution:'计算执行',report:'报告生成',model:'模型调用' };
const levelLabels: Record<QualityLevel,string> = { normal:'正常',attention:'需关注',unavailable:'未采集' };
export function QualityCard({ quality }: { quality: WorkflowQuality }) {
  const stages = qualityStages.filter(stage => quality.signals.some(s => s.stage === stage));
  return <section className="wf-quality" aria-labelledby="quality-heading"><header><h2 id="quality-heading">质量信号</h2>
    <span className={`wf-quality-total ${quality.attention_count ? 'wf-quality-attention' : ''}`}>{quality.attention_count ? `${quality.attention_count} 项需关注` : '无需关注项'}</span></header>
    <div className="wf-quality-stages">{stages.map(stage => <div key={stage}><h3>{stageLabels[stage]}</h3><ul>{quality.signals.filter(s => s.stage === stage).map(s =>
      <li key={s.key} className={`wf-quality-${s.level}`} title={s.note}><span>{s.label}</span><strong>{s.value === null ? '—' : String(s.value)}</strong><em>{levelLabels[s.level]}</em></li>)}</ul></div>)}</div>
    <p className="muted">{quality.notice}</p></section>;
}
export function Findings({ view }: { view: WorkflowView }) { return <section className="wf-findings" aria-labelledby="findings-heading"><h2 id="findings-heading">观测边界与缺口</h2><p className="muted">{view.collection.notice}</p>{view.collection.findings.length ? <ul>{view.collection.findings.map((f,index) => <li key={index}><strong>{findingLabels[f.category]}</strong><code>{f.node_key ? f.node_key + ' / ' : ''}{f.code}</code><span>{f.evidence_refs.join('，') || '无可用引用'}</span></li>)}</ul> : <p>当前业务事实与已采集记录一致，未发现已知采集缺口。</p>}</section>; }
