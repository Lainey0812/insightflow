# 报告阅读体验 V1.2 — REQ-0095

## 原因与范围

报告已保存洞察，但业务展示默认折叠图表，洞察与图表分离。Presentation.subtitle 将全部统计口径拼成长行。本轮改动只涉及阅读与离线导出，不修改数据、LLM Prompt、计算结果或审批。

## 设计

沿用报告原有白色、淡紫灰视觉体系（#ffffff、#f8f6fc、#e6e3ef、#625080、#30364b）。沿用系统字体和现有标题层级。统计口径按真实任务分组，桌面两列、窄屏单列；逐任务展开读取批准口径。图表默认可见，下方使用淡紫边界区分已保存解读，证据仍可展开。

报告数据源、上传记录数始终展示；上传数不冒充过滤后样本数。没有历史口径时明确标记缺失。未推断未保存的筛选范围。

## 解读匹配

只使用 AnalysisReport.insights。每个引用必须存在，且所有引用的 task_id、data_ref、result_field 必须属于当前图表的任务、结果表和指标集合。缺失、跨结果或其他指标的洞察不绑定到该图表。不调用模型，不计算新指标。匹配不了时显示“暂无与此指标直接对应的已保存解读”，原核心发现继续保留。

页面与 HTML 导出采用相同匹配条件，导出图表与解读默认可见。下载仍由用户选择。公开 Schema、已保存 Presentation 与 AnalysisReport 不变。历史 Presentation.findings 的独立规则发现不当作新生成的图表洞察。

## 文件

- frontend/src/reporting/ReportPage.tsx：分组口径、默认可见图表、严格匹配的已保存解读。
- frontend/src/reporting/report.css：口径及解读区域的响应式样式。
- frontend/src/tests/business-report.test.tsx、report.test.tsx：新展示顺序、默认可见图表、缺失引用与指标绑定。
- backend/app/reporting/export.py：离线口径和图表解读，与页面采用同样的数据绑定规则。
- backend/tests/test_report_presentation.py：离线展示及非法引用隔离验证。

## 验证

- 前端 72/72；类型检查及构建通过。
- 后端报告模块、展示与 API 51/51；已有 Starlette httpx 弃用警告保留。
- 真实报告 report_f66380c68d99402d8a4363dd24bcc4f6：浏览器刷新后可读；60 条上传记录，4 个分析方向均展示真实结果及对应的保存洞察，未重新执行或调用 LLM。
- scope.png、chart.png 为真实页面截图。首次测试有 2 个旧展示断言失败，保留 frontend-initial.log；更新契约断言后通过，未修改计算预期。
- 本轮未运行全部后端或 Admin 回归；Admin 与业务执行实现未修改。

## 限制

这是展示改进，不是洞察质量优化。现有泛化解释、重复发现、长小数、混合量纲同轴图表仍需后续专项处理。跨任务综合洞察不会被硬塞进某张单任务图表；仍可在核心发现阅读。HTML 为静态图与结果表，预览提供交互。

## 保留

需求先登记 REQ-0095；before-ui.zip 保存本轮前端原文，after.zip 保存本轮六个文件。旧版本需求、报告与历史输出没有覆盖。
