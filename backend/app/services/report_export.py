import html
import json

from app.domain.models import Report


def render_report(report: Report) -> str:
    """Standalone offline HTML with SVG snapshots, exact values and ECharts options."""
    sections = []
    for section in report.sections:
        result = section.result
        maximum = max(result.values) or 1
        bars, rows = [], []
        for index, (label, value) in enumerate(zip(result.labels, result.values)):
            label = html.escape(label)
            y = 16 + index * 44
            width = value / maximum * 380
            bars.append(f'<text x="0" y="{y + 18}" font-size="12">{label}</text>'
                        f'<rect x="110" y="{y}" width="{width:.2f}" height="26" rx="5" fill="#7766d9"/>'
                        f'<text x="{120 + width:.2f}" y="{y + 18}" font-size="12">{value:,.0f}</text>')
            rows.append(f"<tr><td>{label}</td><td>¥{value:,.0f}</td></tr>")
        sections.append(f"""<section><h2>{html.escape(section.title)}</h2>
          <p>{html.escape(section.insight)}</p>
          <svg role="img" aria-label="{html.escape(section.title, quote=True)}" viewBox="0 0 610 {len(result.values)*44+24}">
          {''.join(bars)}</svg>
          <table><thead><tr><th>分组</th><th>销售额（元）</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
          <p class="evidence">数据依据：{html.escape(section.evidence)}</p></section>""")
    # Escape '<' so user-provided strings can never break out of the JSON script tag.
    payload = json.dumps(report.model_dump(), ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>{html.escape(report.title)}</title><style>
      body{{font:15px/1.75 system-ui,sans-serif;background:#f7f8fc;color:#263047;margin:0;padding:40px 20px}}
      main{{max-width:880px;margin:auto}}header,section{{background:white;border:1px solid #e8eaf0;border-radius:16px;padding:28px;margin-bottom:20px}}
      h1{{font-size:28px}}h2{{font-size:19px}}.badge{{color:#8a5e15;background:#fff3d9;padding:8px 14px;border-radius:8px}}
      .evidence,footer{{color:#6a7487;font-size:13px}}svg{{width:100%;max-height:380px;fill:#596376}}table{{width:100%;border-collapse:collapse}}
      th,td{{text-align:left;padding:8px;border-bottom:1px solid #eee}}footer{{padding:12px}}@media print{{body{{background:white;padding:0}}section{{break-inside:avoid}}}}
      </style></head><body><main><header><small>INSIGHTFLOW / ANALYSIS REPORT</small>
      <h1>{html.escape(report.title)}</h1><p class="badge">Mock 示例，非上传文件分析结果。不得用于真实业务决策。</p>
      <p>计划版本 v{report.provenance.plan_version} · 数据集 {html.escape(report.provenance.dataset)}</p></header>
      {''.join(sections)}<footer>由 InsightFlow 生成 · 包含离线 SVG 图表及内嵌 ECharts 配置和计算结果</footer>
      <script type="application/json" id="report-data">{payload}</script></main></body></html>"""
