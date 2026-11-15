# 仅在图形下显示图表解读 — REQ-0098 / V1.5

## 变更

页面仅在当前展示类型为 bar、line、pie 且非标量卡片时显示 ChartInterpretation。标量指标卡、KPI 与纯表格移除该展示块；将图形切换为表格时同步隐藏，切回图形恢复。证据、统计口径和原始结果入口保留。

HTML 仅为图形类型生成离线 SVG，并仅在真实 SVG 非空时附加图表解读。卡片或纯表格不产生解读区，也不会为了保留解读而额外生成图形。

未删除保存的 Insight、Evidence 或历史报告，不修改 Prompt、计算结果或业务流程。只隐藏用户不需要的展示块；完整保存数据仍由现有报告查询接口保留。

## 文件

- frontend/src/reporting/ReportPage.tsx：按实际展示类型限定解读。
- frontend/src/tests/business-report.test.tsx：卡片无解读、图形与表格切换覆盖。
- backend/app/reporting/export.py：离线图形与解读共同控制。
- backend/tests/test_report_presentation.py：纯表格无 SVG/解读、证据保留验证。

## 验证

前端 79 项通过，类型检查及构建通过；报告展示、API 与模块相关后端 54 项通过。已有 Starlette/httpx 弃用提示保留。本轮局部展示更新未重新运行全部后端或 Admin。

真实报告 report_f66380c68d99402d8a4363dd24bcc4f6 浏览器刷新验证：五张销售概览卡片下仅保留证据入口，直接进入下一分析方向；其他三张真实图形保留解读。cards-without-notes.png 保存实际页面。

真实 HTML 下载验证：3 个 SVG、3 个图表解读区；整体销售概况区没有图表解读。后端已重载供用户测试。没有重新执行计算或调用 LLM。

需求原文先归档 REQ-0098；before.zip/after.zip 保存四个文件前后版本。旧归档与报告未覆盖。
