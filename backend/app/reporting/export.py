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

def scalar_cards(chart, table):
    """Render a complete, ungrouped numeric result row without computing metrics."""
    if not (chart.chart_type == 'table' and chart.dimension is None and not table.truncated
            and table.total_result_rows == 1 and len(table.rows) == 1 and chart.metrics
            and all(c.role == 'metric' and c.field in chart.metrics for c in table.columns)
            and all(any(c.field == name for c in table.columns)
                    and (table.rows[0].get(name) is None or type(table.rows[0].get(name)) in {int, float})
                    for name in chart.metrics)):
        return ''
    columns = {c.field: c for c in table.columns}
    return '<div class="metrics scalar-metrics">' + ''.join(
        f'<div class="metric"><small>{escape(columns[name].label)}</small><strong>{escape("—" if table.rows[0][name] is None else fmt(table.rows[0][name]))} {escape(columns[name].unit or "")}</strong></div>'
        for name in chart.metrics) + '</div>'


def saved_samples(report, task_id):
    """Only a validated, linked native Engine record supplies joint sample facts."""
    from app.domain.execution import SampleStatistics
    meta = report.execution_metadata.get(task_id, {})
    execution = meta.get('execution_metadata') or {}
    ref = meta.get('result_id')
    if (report.execution_source != 'engine' or meta.get('status') != 'success'
            or ref not in report.result_data or report.result_data[ref].result_id != ref
            or not execution.get('steps') or not execution.get('sample_statistics')):
        return None
    try:
        sample = SampleStatistics.model_validate(execution['sample_statistics'])
    except ValueError:
        return None
    return sample if sample.input_row_count == meta.get('effective_row_count') else None


def approved_basis_details(report, task_id):
    meta = report.execution_metadata.get(task_id, {})
    basis = (meta.get('execution_metadata') or {}).get('analysis_basis')
    if report.execution_source != 'engine' or not basis or basis.get('plan_version') != report.plan_version:
        return ''
    grains = {'unknown':'业务粒度未声明','record':'每行一条记录','detail':'每行一条明细，同一实体可能多行','entity':'每行一个实体，批准时已核验标识非空且唯一'}
    items = ''.join(f'<li>{escape(m["label"])}（{escape(m["function"])}）：{escape(m["basis"])}</li>' for m in basis.get('metrics', []))
    return f'<details><summary>审批绑定的指标定义</summary><p>上传数据粒度：{escape(grains.get(basis.get("row_grain"), "业务粒度未声明"))}</p><ul>{items}</ul><p>绑定计划第 {report.plan_version} 版；不依据字段名称补充币种、税费或退款定义。</p></details>'


def sample_details(report, task_id):
    sample = saved_samples(report, task_id)
    if sample is None:
        return '<p><small>此执行未保存联合完整性统计，不能从逐列缺失数推算缺失记录数。</small></p>'
    fields = '、'.join(field.label for field in sample.key_fields)
    completeness = (f'<p>统计关键字段：{escape(fields)}。完整记录 {sample.complete_row_count} 条；至少一个关键字段缺失 {sample.missing_row_count} 条（按行去重）。</p>'
                    if sample.key_fields else '<p>本方向仅计数记录，没有字段依赖，关键字段完整性统计不适用。</p>')
    basis = {'rows':'逐行计数，不代表去重业务实体数', 'non_null_values':'按来源字段非空记录参与计算',
             'distinct_non_null_values':'来源字段先排除缺失，再按不同值计数；参与记录数不是去重结果数'}
    metrics = ''.join(f'<li>{escape(metric.label)}（{escape(metric.function)}）：{basis[metric.basis]}；参与记录 {metric.participating_count} 条。</li>' for metric in sample.metrics.values())
    return f'<details><summary>样本与指标口径</summary><p>本方向聚合前 {sample.input_row_count} 条记录；Top N 返回分组不会改变此聚合输入口径。</p>{completeness}<ul>{metrics}</ul><p>缺失统计不会自动清洗或删除记录；各指标依照已批准函数处理缺失。字段完整不代表数值准确，也不自动确认业务实体、币种或税费范围。</p></details>'


def render_report_v1(report, presentation=None):
    metrics = ''.join(f'<div class="metric"><small>{escape(m.label)}</small><strong>{escape(m.value)} {escape(m.unit or "")}</strong></div>' for m in report.key_metrics)
    findings = ''.join(f'<article><h3>发现 {index + 1}：{escape(i.finding)}</h3><p>{escape(i.implication)}</p><details><summary>事实核对详情</summary><p>{escape(i.fact)}</p></details><small>证据：{escape(", ".join(i.evidence_refs))}</small></article>' for index,i in enumerate(report.insights))
    if presentation is not None:
        metrics = ''.join(f'<div class="metric"><small>{escape(m.label)}</small><strong>{escape(m.display_value)}</strong><p>{escape(m.caption)}</p></div>' for m in presentation.key_metrics)
        findings = ''.join(f'<article><h3>发现 {index + 1}：{escape(i.title)}</h3><p>{escape(i.body)}</p><small>证据：{escape(", ".join(i.evidence_refs))}</small></article>' for index, i in enumerate(presentation.findings))
    tables = []
    for chart in report.charts:
        table = report.result_data[chart.data_ref]
        header = ''.join(f'<th>{escape(c.label)}</th>' for c in table.columns)
        rows = ''.join('<tr>' + ''.join(f'<td>{escape(row[c.field])}</td>' for c in table.columns) + '</tr>' for row in table.rows)
        matching = []
        by_id = {e.evidence_id: e for e in report.evidence}
        for insight in report.insights:
            refs = [by_id.get(key) for key in insight.evidence_refs]
            if refs and all(e and e.task_id == chart.task_id and e.data_ref == chart.data_ref
                            and e.result_field in chart.metrics for e in refs):
                matching.append(f'<p><strong>{escape(insight.finding)}</strong></p><p>{escape(insight.implication)}</p><small>证据：{escape(", ".join(insight.evidence_refs))}</small>')
        commentary = ''.join(matching) or '<p>该图表暂无与此指标直接对应的已保存解读，可查看结果数据与统计口径。不会据此推断差异原因。</p>'
        meta = report.execution_metadata.get(chart.task_id, {})
        count = meta.get('effective_row_count')
        count_ok = (report.execution_source == 'engine' and meta.get('status') == 'success'
                    and meta.get('result_id') == chart.data_ref and (meta.get('execution_metadata') or {}).get('steps')
                    and type(count) is int and 0 <= count <= report.dataset_row_count)
        sample = f'<p>本方向纳入记录：{count if count_ok else "未统计"}；指标有效样本量：{meta.get("valid_sample_count") if meta.get("valid_sample_count") is not None else "按指标分别统计或未提供"}。</p>'
        cards = scalar_cards(chart, table)
        result_table = f'<div class="table"><table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table></div>'
        if cards:
            result_table = f'<details><summary>查看结果数据</summary>{result_table}</details>'
        graphic = snapshot(chart, table) if chart.chart_type in {'bar', 'line', 'pie'} else ''
        interpretation = f'<aside><h4>图表解读</h4>{commentary}</aside>' if graphic else ''
        tables.append(f'<article><h3>{escape(chart.title)}</h3>{sample}{approved_basis_details(report, chart.task_id)}{sample_details(report, chart.task_id)}<p>{escape(chart.note or "完整返回结果")}</p>{cards or graphic}{interpretation}{result_table}</article>')

    evidence = ''.join(f'<details><summary>{escape(e.evidence_id)} · {escape(e.statement)}</summary><p>任务 {escape(e.task_id)} · 结果 {escape(e.data_ref)} · 字段 {escape(e.result_field)}</p><p>范围：{escape(e.scope)}</p><p>口径：{escape(e.calculation)}</p></details>' for e in [*report.evidence, *(presentation.evidence if presentation else [])])
    recommendations = ''.join(f'<li>{escape(r.text)} <small>证据：{escape(", ".join(r.evidence_refs))}</small></li>' for r in report.recommendations)
    limitations = ''.join(f'<li>{escape(item)}</li>' for item in report.limitations)
    failed = ''.join(f'<li>{escape(t.title)}（{escape(t.priority)}）：{escape(t.reason)}</li>' for t in report.uncompleted_tasks)
    if presentation is not None:
        recommendations = ''.join(f'<li>{escape(text)}</li>' for text in dict.fromkeys(presentation.recommendations))
        limitations = ''.join(f'<li>{escape(text)}</li>' for text in presentation.data_notes)
    title = presentation.title if presentation else report.summary.headline
    subtitle = report.analysis_goal
    overview = presentation.executive_summary if presentation else report.summary.overview
    findings_title = '核心发现与业务解读' if presentation else '主要发现'
    recommendations_title = '建议进一步分析' if presentation else '下一步建议'
    notes_title = '数据局限与证据'
    mock = '<p class="notice">测试 Provider 生成的解释内容；不代表真实模型评测结果。</p>' if report.llm and report.llm.is_mock else ''
    coverage = {"complete":"计划内核心任务已有结果", "partial":"目标部分覆盖", "blocked":"核心目标未覆盖"}[report.goal_coverage]
    tables_section = f'<section><h2>各分析方向</h2><p>离线版本保留完整返回表格；交互图表请使用预览链接。</p>{"".join(tables)}</section>'
    scope_items = []
    for task_id, meta in report.execution_metadata.items():
        lines = meta.get('approved_scope', [])
        if lines:
            label = report.task_metadata[task_id].title if task_id in report.task_metadata else '分析方向'
            items = ''.join(f'<li>{escape(line.replace("拟用统计口径：", "统计口径："))}</li>' for line in dict.fromkeys(lines))
            scope_items.append(f'<details><summary>{escape(label)} · 查看范围与算法</summary><ul>{items}</ul></details>')
    scope_section = '<section><h2>分析范围与统计口径</h2><p>上传记录数不等于各指标的有效样本量；筛选条件、分组方式和计算方法以各分析方向为准。</p>' + (''.join(scope_items) or '<p>该历史报告未保存完整的已批准统计口径，请查看图表证据及原始计算结果。</p>') + '</section>'
    # A filtered row count must come from a successful, linked Engine result.
    task_ids = list(report.task_metadata)
    included = '分方向统计' if len(task_ids) > 1 else '未统计'
    if len(task_ids) == 1:
        meta = report.execution_metadata.get(task_ids[0], {})
        count = meta.get('effective_row_count')
        result_id = meta.get('result_id')
        if (report.execution_source == 'engine' and meta.get('status') == 'success'
                and result_id in report.result_data and report.result_data[result_id].result_id == result_id
                and (meta.get('execution_metadata') or {}).get('steps')
                and type(count) is int and 0 <= count <= report.dataset_row_count):
            included = f'{count:,}'
    single_sample = saved_samples(report, task_ids[0]) if len(task_ids) == 1 else None
    per_direction = len(task_ids) > 1 and all(saved_samples(report, tid) for tid in task_ids)
    complete = ('不适用' if single_sample.complete_row_count is None else f'{single_sample.complete_row_count:,}') if single_sample else '分方向统计' if per_direction else '未统计'
    missing = ('不适用' if single_sample.missing_row_count is None else f'{single_sample.missing_row_count:,}') if single_sample else '分方向统计' if per_direction else '未统计'
    cards = [('上传记录数', f'{report.dataset_row_count:,}', '已读取数据行，不含表头'),
             ('本次纳入记录数', included, '多个方向不合并为一个统计范围'),
             ('关键字段完整记录数', complete, '按各方向聚合输入字段统计；旧执行可能未采集'),
             ('关键字段缺失记录数', missing, '至少一个关键字段缺失，按行去重')]
    overview_cards = ''.join(f'<div class="metric"><small>{escape(label)}</small><strong>{escape(value)}</strong><p>{escape(note)}</p></div>' for label, value, note in cards)
    quality = presentation.dataset_overview if presentation else None
    quality_note = (f'上传范围共 {quality.field_count} 个字段，缺失单元格 {quality.missing_cell_count} 个，疑似重复记录 {quality.duplicate_row_count} 条。未自动清洗或删除。'
                    if quality else '该报告未提供上传范围的完整数据质量画像。')
    overview_section = f'<section><h2>数据概况</h2><div class="metrics">{overview_cards}</div><p>{escape(quality_note)} 完整性不代表准确性；各指标有效样本量以对应计算口径为准。</p></section>'
    linked = set()
    for chart in report.charts:
        for insight in report.insights:
            refs = [next((e for e in report.evidence if e.evidence_id == key), None) for key in insight.evidence_refs]
            if refs and all(e and e.task_id == chart.task_id and e.data_ref == chart.data_ref and e.result_field in chart.metrics for e in refs):
                linked.add(insight.insight_id)
    additional = ''.join(f'<article><h3>{escape(i.finding)}</h3><p>{escape(i.implication)}</p><small>证据：{escape(", ".join(i.evidence_refs))}</small></article>' for i in report.insights if i.insight_id not in linked)
    legacy = findings if presentation and presentation.presentation_version == 'business-report-v1' else ''
    additional_section = (f'<details><summary>补充发现与历史解读</summary>{additional}{legacy}</details>' if additional or legacy else '')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>InsightFlow 分析报告</title>
<style>body{{font:15px/1.8 system-ui,sans-serif;background:#f5f6fa;color:#263047;margin:0;padding:30px 18px}}main{{max-width:1000px;margin:auto}}section,header{{background:white;border:1px solid #e6e8ef;border-radius:14px;padding:26px;margin-bottom:18px}}h1{{font-size:28px}}h2{{font-size:21px}}article{{border-top:1px solid #eee;padding:15px 0}}small{{color:#6c7383}}.metrics{{display:flex;gap:25px;flex-wrap:wrap}}.metric{{flex:1;min-width:150px;border:1px solid #e6e3ef;border-radius:8px;padding:16px}}.metric strong{{display:block;font-size:24px}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #eee}}details{{padding:10px 0;border-bottom:1px solid #eee}}.notice{{background:#fff6df;padding:12px}}@media print{{body{{background:white}}section{{break-inside:avoid}}}}</style></head>
<body><main><header><small>INSIGHTFLOW / 业务分析报告</small><h1>{escape(title)}</h1><p>分析目标：{escape(subtitle)}</p><p>数据来源：{escape(report.dataset_name)} · {escape(coverage)}</p>{mock}</header>
{overview_section}<section><h2>执行摘要</h2><p>{escape(overview)}</p><details><summary>查看关键业务指标</summary><div class="metrics">{metrics}</div></details></section>{tables_section}{additional_section}<section><h2>整体总结与下一步建议</h2><p>{escape(coverage)}；以上结论仅适用于本次已保存的分析范围。</p><h3>下一步建议</h3><ul>{recommendations}</ul></section>{scope_section}<section><h2>{notes_title}</h2><ul>{limitations}{failed}</ul><details><summary>查看全部证据与统计口径</summary>{evidence}</details></section><footer><details><summary>报告来源与版本</summary><small>执行 ID {escape(report.execution_id)} · 计划 v{report.plan_version} · 数据集版本 {escape(report.dataset_version)} · {escape(report.generated_at)}</small></details></footer></main></body></html>'''
