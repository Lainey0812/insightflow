import { useEffect, useState } from 'react';
import { readAdminConfig } from '../../config/env';
import type { Metadata, TraceEvent, TraceSpan } from '../../types/traces';
import type { WorkflowObservation } from '../../types/workflows';
import { StatusBadge } from '../traces/TraceShared';
import { durationText, timeText, traceStatus, valueText } from '../traces/presentation';
import { InputSummary } from './WorkflowShared';
import { CopyJson } from './NodeChrome';

const fileKeys = ['input_file_extension', 'input_file_size_bytes'] as const;
const optionKeys = ['header_row', 'sheet_name', 'encoding', 'delimiter'] as const;
const overviewKeys = ['row_count', 'column_count', 'total_cell_count', 'missing_cell_count', 'missing_cell_rate', 'duplicate_row_count', 'duplicate_row_rate', 'file_format', 'sheet_name', 'profiler_version'] as const;
const labels: Record<string, string> = {
  input_file_extension: '文件类型', input_file_size_bytes: '文件大小（字节）', file_name: '文件名', file_format: '文件格式', content_sha256: '内容校验',
  dataset_id: '数据集', dataset_version: '数据集版本', header_row: '表头行', sheet_name: '工作表', encoding: '编码', delimiter: '分隔符',
  row_count: '行数', column_count: '字段数', total_cell_count: '单元格数', missing_cell_count: '缺失单元格', missing_cell_rate: '缺失率',
  duplicate_row_count: '重复行', duplicate_row_rate: '重复率', profiler_version: '画像版本',
};

function numberOf(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
function record(value: unknown): Metadata | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Metadata : null;
}
function shown(value: unknown): string {
  return value === null ? '未指定' : valueText(value);
}
function Facts({ source }: { source: Metadata }) {
  const entries = Object.entries(source).filter(([, value]) => value !== undefined);
  if (!entries.length) return null;
  return <dl className="wf-refs">{entries.map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd><code>{shown(value)}</code></dd></div>)}</dl>;
}
function pick(source: Metadata, keys: readonly string[]): Metadata {
  return Object.fromEntries(keys.filter(key => Object.prototype.hasOwnProperty.call(source, key)).map(key => [key, source[key]]));
}
function stackText(node: TraceSpan, events: TraceEvent[]): string {
  const attrs = node.attributes || {};
  for (const key of ['error_stack', 'stack', 'traceback', 'stacktrace']) {
    if (typeof attrs[key] === 'string' && attrs[key]) return String(attrs[key]);
  }
  for (const event of events) {
    const payload = event.payload || {};
    for (const key of ['error_stack', 'stack', 'traceback', 'stacktrace']) {
      if (typeof payload[key] === 'string' && payload[key]) return String(payload[key]);
    }
  }
  return '';
}
function withoutSamples(profile: Metadata): Metadata {
  const copy = JSON.parse(JSON.stringify(profile)) as Metadata;
  if (Array.isArray(copy.fields)) {
    copy.fields = copy.fields.map(field => {
      const item = record(field);
      if (!item) return field;
      const next = { ...item };
      delete next.samples;
      return next;
    });
  }
  return copy;
}
function fieldsOf(profile: Metadata): Metadata[] {
  return Array.isArray(profile.fields) ? profile.fields.filter((item): item is Metadata => !!record(item)) : [];
}
function issuesOf(profile: Metadata): Metadata[] | null {
  return Array.isArray(profile.quality_issues) ? profile.quality_issues.filter((item): item is Metadata => !!record(item)) : null;
}

export function ProfilerNodeDetail({ node, trace }: { node: TraceSpan; trace: WorkflowObservation }) {
  const attrs = node.attributes || {};
  const failed = traceStatus(node.status) === 'error' || Boolean(node.error_code);
  const events = trace.events.filter(event => event.span_id === node.span_id);
  const stack = stackText(node, events);
  const datasetId = typeof attrs.dataset_id === 'string' ? attrs.dataset_id : '';
  const version = typeof attrs.dataset_version === 'string' ? attrs.dataset_version : '';
  const [profile, setProfile] = useState<Metadata | null>(null);
  const [note, setNote] = useState(datasetId && version ? '正在读取数据集画像…' : '节点没有保存数据集标识，无法读取画像。');
  const [tab, setTab] = useState('input');
  useEffect(() => {
    if (!datasetId || !version) return undefined;
    const controller = new AbortController();
    const base = readAdminConfig().apiBaseUrl.replace(/\/admin\/?$/, '').replace(/\/+$/, '');
    fetch(`${base}/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(version)}/profile`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => { if (!response.ok) throw new Error(String(response.status)); return response.json() as Promise<Metadata>; })
      .then(value => {
        if (controller.signal.aborted) return;
        if (!value || value.dataset_id !== datasetId || value.dataset_version !== version) { setNote('数据集画像结构不正确。'); return; }
        setProfile(value);
        setNote('');
      })
      .catch(() => { if (!controller.signal.aborted) setNote('数据集画像没有读到。节点上仍保留已保存的计数。'); });
    return () => controller.abort();
  }, [datasetId, version]);
  const options = record(profile?.options) || {};
  const rows = numberOf(profile?.row_count) ?? numberOf(attrs.row_count);
  const columns = numberOf(profile?.column_count) ?? numberOf(attrs.column_count);
  const issues = profile ? issuesOf(profile) : null;
  const issueCount = issues ? issues.length : numberOf(attrs.quality_issue_count);
  const files: Metadata = { ...pick(attrs, fileKeys) };
  for (const key of ['file_name', 'file_format', 'content_sha256'] as const) if (profile && Object.prototype.hasOwnProperty.call(profile, key)) files[key] = profile[key];
  const identifiers: Metadata = {};
  if (datasetId) identifiers.dataset_id = datasetId;
  if (version) identifiers.dataset_version = version;
  const config = Object.keys(options).length ? pick(options, optionKeys) : pick(attrs, ['input_header_row', 'input_sheet_name', 'input_encoding', 'input_delimiter']);
  const configLabels = Object.fromEntries(Object.entries(config).map(([key, value]) => [key.replace(/^input_/, ''), value]));
  const overview = profile ? pick(profile, overviewKeys) : pick(attrs, overviewKeys);
  const fields = profile ? fieldsOf(profile) : [];
  const output = profile ? withoutSamples(profile) : null;
  const brief = node.error_message || (typeof attrs.error_message === 'string' ? attrs.error_message : '');
  return <aside className="wf-node-detail" aria-label="节点详情">
    <header className="wf-detail-head">
      <h2>数据画像</h2>
      <StatusBadge status={node.status} />
      <span>{durationText(node.duration_ms)}</span>
      {rows != null && <span>行数 {rows}</span>}
      {columns != null && <span>字段数 {columns}</span>}
      {issueCount != null && <span>质量信号 {issueCount}</span>}
    </header>
    <code className="wf-id">{node.span_id}</code>
    <p className="muted">{timeText(node.started_at)} – {timeText(node.finished_at)}{node.node_attempt ? ` · 第 ${node.node_attempt} 次` : ''}</p>
    {failed && <section className="wf-profiler-error">
      <p><code>{node.error_code || '未采集'}</code></p>
      <p>{brief || '没有已保存的错误说明。'}</p>
      <details>
        <summary>错误详情</summary>
        {stack ? <pre className="wf-json" tabIndex={0}>{stack}</pre> : <p className="muted">没有更多已保存的错误详情。</p>}
      </details>
    </section>}
    <div className="trace-tabs" role="tablist" aria-label="节点内容">
      {[['input', 'Input'], ['output', 'Output']].map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={`trace-tab ${tab === id ? 'trace-tab-active' : ''}`} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    <div role="tabpanel">
      {tab === 'input' && <section>
        <h3>文件元数据</h3>
        {Object.keys(files).length ? <Facts source={files} /> : <InputSummary attrs={{}} />}
        <h3>数据集标识</h3>
        {Object.keys(identifiers).length ? <Facts source={identifiers} /> : <p className="muted">未采集数据集标识。</p>}
        <h3>解析与画像配置</h3>
        {Object.keys(configLabels).length ? <Facts source={configLabels} /> : <p className="muted">未采集解析与画像配置。</p>}
      </section>}
      {tab === 'output' && <section>
        <h3>数据集概览</h3>
        {Object.keys(overview).length ? <Facts source={overview} /> : <p className="muted">未采集数据集概览。</p>}
        {note && <p className="muted">{note}</p>}
        {profile && <>
          <h3>字段 Schema 与统计</h3>
          {fields.length ? <div className="wf-field-scroll"><table className="wf-fields"><thead><tr><th>字段</th><th>标识</th><th>位置</th><th>物理类型</th><th>逻辑类型</th><th>缺失</th><th>缺失率</th><th>非空</th><th>唯一值</th></tr></thead><tbody>
            {fields.map((field, index) => <tr key={String(field.field_id || index)}><td>{valueText(field.display_name || field.original_name)}</td><td>{valueText(field.field_id)}</td><td>{valueText(field.position)}</td><td>{valueText(field.physical_type)}</td><td>{valueText(field.logical_type)}</td><td>{valueText(field.missing_count)}</td><td>{valueText(field.missing_rate)}</td><td>{valueText(field.non_missing_count)}</td><td>{valueText(field.unique_count)}</td></tr>)}
          </tbody></table></div> : <p className="muted">这次画像没有字段。</p>}
          <h3>数据质量信号</h3>
          {issues == null ? <p className="muted">已保存画像里没有质量信号字段。</p> : issues.length ? <ul className="wf-issues">{issues.map((issue, index) => <li key={index}><code>{valueText(issue.code)}</code> <span>{valueText(issue.severity)}</span><p>{valueText(issue.message)}</p><p>影响 {valueText(issue.affected_count)}{Array.isArray(issue.field_ids) && issue.field_ids.length ? ` · ${issue.field_ids.filter(item => typeof item === 'string').join('、')}` : ''}</p>{Array.isArray(issue.example_row_numbers) && issue.example_row_numbers.length ? <p>示例行 {issue.example_row_numbers.filter(item => typeof item === 'number').join('、')}</p> : null}</li>)} </ul> : <p className="muted">这次画像没有质量信号。</p>}
          <details>
            <summary>结构化输出 JSON</summary>
            {output && <CopyJson text={JSON.stringify(output, null, 2)} />}
            <pre className="wf-json" tabIndex={0}>{JSON.stringify(output, null, 2)}</pre>
          </details>
        </>}
      </section>}
    </div>
  </aside>;
}
