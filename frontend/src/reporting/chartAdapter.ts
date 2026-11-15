import type { EChartsOption } from 'echarts';
import type { Cell, ChartSpec, ChartType, ResultTable } from '../types/report';

export function displayValue(value: Cell): string {
  return value === null ? '—' : typeof value === 'boolean' ? (value ? '是' : '否') : typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 6 }) : value;
}
export function compareValues(a: Cell, b: Cell): number {
  if (a === null) return b === null ? 0 : 1;
  if (b === null) return -1;
  return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'zh-CN', { numeric: true });
}
export function chartRows(spec: ChartSpec, table: ResultTable) {
  const rows = [...table.rows];
  if (spec.order === 'value_desc' && spec.metrics[0]) rows.sort((a, b) => {
    const av = a[spec.metrics[0]], bv = b[spec.metrics[0]];
    if (av === null) return bv === null ? 0 : 1;
    if (bv === null) return -1;
    return compareValues(bv, av);
  });
  if (spec.order === 'dimension_asc' && spec.dimension) {
    const dimension = spec.dimension;
    const kind = table.columns.find(c => c.field === dimension)?.logical_type;
    rows.sort((a, b) => {
      if (a[dimension] !== null && b[dimension] !== null && (kind === 'date' || kind === 'datetime')) return Date.parse(String(a[dimension])) - Date.parse(String(b[dimension]));
      return compareValues(a[dimension], b[dimension]);
    });
    return rows.filter(row => row[dimension] !== null); // Missing time groups remain in table.
  }
  return rows.slice(0, spec.display_limit);
}

export function toEChartsOption(spec: ChartSpec, table: ResultTable, type: ChartType): EChartsOption {
  if (!spec.supported_chart_types.includes(type)) throw new Error('不兼容的图表类型。');
  if (type === 'table' || type === 'kpi') return {};
  if (!spec.dimension || !spec.metrics.length) throw new Error('图表缺少维度或指标。');
  const rows = chartRows(spec, table);
  const labels = rows.map(row => row[spec.dimension!] === null ? '缺失分组' : String(row[spec.dimension!]));
  const name = (field: string) => table.columns.find(c => c.field === field)?.label ?? field;
  const base = { animation: false, color: ['#7462d8', '#39a9a0', '#e9b25b', '#8da0d5', '#d48bb3'],
    tooltip: { trigger: type === 'pie' ? 'item' : 'axis', renderMode: 'richText', confine: true },
    aria: { enabled: true }, legend: { bottom: 0 }, textStyle: { fontFamily: 'system-ui, sans-serif' } };
  if (type === 'pie') return { ...base, tooltip: { trigger: 'item', renderMode: 'richText', confine: true },
    series: [{ name: name(spec.metrics[0]), type: 'pie', radius: ['35%', '65%'],
      data: rows.map((row, index) => ({ name: labels[index], value: row[spec.metrics[0]] as number })), label: { formatter: '{b}' } }] } as EChartsOption;
  const series = spec.metrics.map(field => ({ name: name(field), type,
    data: rows.map(row => row[field] as number | null), ...(type === 'bar' ? { barMaxWidth: 32 } : { connectNulls: false, smooth: false }) }));
  if (type === 'bar') return { ...base, grid: { left: 150, right: 36, top: 20, bottom: 52 },
    xAxis: { type: 'value' }, yAxis: { type: 'category', data: labels, inverse: true,
      axisLabel: { width: 135, overflow: 'truncate' } }, series } as EChartsOption;
  return { ...base, grid: { left: 60, right: 28, top: 24, bottom: 65 }, xAxis: { type: 'category', data: labels, boundaryGap: false },
    yAxis: { type: 'value' }, series } as EChartsOption;
}
