"""Optional offline HTML export. No scripts or arbitrary chart configuration."""
import html
from decimal import Decimal
from .evidence import fmt


def escape(value):
    return html.escape("—" if value is None else str(value), quote=True)



def snapshot(spec, table):
    if not spec.dimension or not spec.metrics:
        return ""
    field = spec.metrics[0]
    rows = [row for row in table.rows if isinstance(row[field], (int, float)) and not isinstance(row[field], bool)]
    rows = sorted(rows, key=lambda row: -row[field])[:spec.display_limit]
    if not rows:
        return ""
    low = min(0, min(row[field] for row in rows))
    high = max(0, max(row[field] for row in rows))
    low_decimal = Decimal(str(low))
    span = Decimal(str(high)) - low_decimal or Decimal(1)
    def position(value):
        return 180 + float((Decimal(str(value)) - low_decimal) / span) * 360
    zero, bars = position(0), []
    for index, row in enumerate(rows):
        value, y = row[field], 12 + index * 38
        x = min(zero, position(value))
        width = abs(position(value) - zero)
        label = str(row[spec.dimension])[:24] if row[spec.dimension] is not None else "缺失分组"
        bars.append(f'<text x="0" y="{y + 18}" font-size="12">{escape(label)}</text><rect x="{x:.3f}" y="{y}" width="{width:.3f}" height="24" rx="3" fill="#7462d8"/><text x="560" y="{y + 18}" font-size="12">{escape(fmt(value))}</text>')
    metric_label = next(c.label for c in table.columns if c.field == field)
    return f'<p><small>离线条形图 · {escape(metric_label)} · 仅展示前 {len(rows)} 个返回分组，完整数值见表格</small></p><svg role="img" aria-label="{escape(spec.title)}" viewBox="0 0 680 {len(rows) * 38 + 20}" style="width:100%;max-height:440px">{"".join(bars)}</svg>'

def render_report_v1(report, presentation=None):
    metrics = ''.join(f'<div class="metric"><small>{escape(m.label)}</small><strong>{escape(m.value)} {escape(m.unit or "")}</strong></div>' for m in report.key_metrics)
    findings = ''.join(f'<article><h3>发现 {index + 1}</h3><p>{escape(i.fact)}</p><p>{escape(i.implication)}</p><p>{escape(i.recommendation)}</p><small>证据：{escape(", ".join(i.evidence_refs))}</small></article>' for index,i in enumerate(report.insights))
    if presentation is not None:
        metrics = ''.join(f'<div class="metric"><small>{escape(m.label)}</small><strong>{escape(m.display_value)}</strong><p>{escape(m.caption)}</p></div>' for m in presentation.key_metrics)
        findings = ''.join(f'<article><h3>发现 {index + 1}：{escape(i.title)}</h3><p>{escape(i.body)}</p><small>证据：{escape(", ".join(i.evidence_refs))}</small></article>' for index, i in enumerate(presentation.findings))
    tables = []
    for chart in report.charts:
        table = report.result_data[chart.data_ref]
        header = ''.join(f'<th>{escape(c.label)}</th>' for c in table.columns)
        rows = ''.join('<tr>' + ''.join(f'<td>{escape(row[c.field])}</td>' for c in table.columns) + '</tr>' for row in table.rows)
        tables.append(f'<article><h3>{escape(chart.title)}</h3><p>{escape(chart.note or "完整返回结果")}</p>{snapshot(chart, table)}<div class="table"><table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table></div></article>')
    evidence = ''.join(f'<details><summary>{escape(e.evidence_id)} · {escape(e.statement)}</summary><p>任务 {escape(e.task_id)} · 结果 {escape(e.data_ref)} · 字段 {escape(e.result_field)}</p><p>范围：{escape(e.scope)}</p><p>口径：{escape(e.calculation)}</p></details>' for e in [*report.evidence, *(presentation.evidence if presentation else [])])
    recommendations = ''.join(f'<li>{escape(r.text)} <small>证据：{escape(", ".join(r.evidence_refs))}</small></li>' for r in report.recommendations)
    limitations = ''.join(f'<li>{escape(item)}</li>' for item in report.limitations)
    failed = ''.join(f'<li>{escape(t.title)}（{escape(t.priority)}）：{escape(t.reason)}</li>' for t in report.uncompleted_tasks)
    if presentation is not None:
        recommendations = ''.join(f'<li>{escape(text)}</li>' for text in presentation.recommendations)
        limitations = ''.join(f'<li>{escape(text)}</li>' for text in presentation.data_notes)
    title = presentation.title if presentation else report.summary.headline
    subtitle = presentation.subtitle if presentation else report.analysis_goal
    overview = presentation.executive_summary if presentation else report.summary.overview
    findings_title = '核心发现与业务解读' if presentation else '主要发现'
    recommendations_title = '建议进一步分析' if presentation else '下一步建议'
    notes_title = '数据说明' if presentation else '数据局限与未完成任务'
    mock = '<p class="notice">测试 Provider 生成的解释内容；不代表真实模型评测结果。</p>' if report.llm and report.llm.is_mock else ''
    coverage = {"complete":"计划内核心任务已有结果", "partial":"目标部分覆盖", "blocked":"核心目标未覆盖"}[report.goal_coverage]
    tables_section = f'<section><h2>结果数据</h2><p>离线版本保留完整返回表格；交互图表请使用预览链接。</p>{"".join(tables)}</section>'
    if presentation:
        tables_section = f'<section><details><summary>查看图表与结果数据</summary><p>离线版本保留完整返回表格；交互图表请使用预览链接。</p>{"".join(tables)}</details></section>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>InsightFlow 分析报告</title>
<style>body{{font:15px/1.8 system-ui,sans-serif;background:#f5f6fa;color:#263047;margin:0;padding:30px 18px}}main{{max-width:1000px;margin:auto}}section,header{{background:white;border:1px solid #e6e8ef;border-radius:14px;padding:26px;margin-bottom:18px}}h1{{font-size:28px}}h2{{font-size:21px}}article{{border-top:1px solid #eee;padding:15px 0}}small{{color:#6c7383}}.metrics{{display:flex;gap:25px;flex-wrap:wrap}}.metric strong{{display:block;font-size:24px}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #eee}}details{{padding:10px 0;border-bottom:1px solid #eee}}.notice{{background:#fff6df;padding:12px}}@media print{{body{{background:white}}section{{break-inside:avoid}}}}</style></head>
<body><main><header><small>INSIGHTFLOW / 业务分析报告</small><h1>{escape(title)}</h1><p>{escape(subtitle)}</p>{"<h2>执行摘要</h2>" if presentation else ""}<p>{escape(overview)}</p><p>{escape(report.dataset_name)} · 上传记录 {report.dataset_row_count} 条 · {escape(coverage)}</p>{mock}<div class="metrics">{metrics}</div></header>
<section><h2>{findings_title}</h2>{findings or '<p>没有可用洞察。</p>'}</section>{tables_section}<section><h2>{recommendations_title}</h2><ul>{recommendations}</ul></section><section><h2>{notes_title}</h2><ul>{limitations}{failed}</ul></section><section><h2>证据与统计口径</h2>{evidence}</section><footer><details><summary>报告来源与版本</summary><small>执行 ID {escape(report.execution_id)} · 计划 v{report.plan_version} · 数据集版本 {escape(report.dataset_version)} · {escape(report.generated_at)}</small></details></footer></main></body></html>'''
