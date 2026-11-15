# 整体销售概览指标卡片 — REQ-0097 / V1.4

## 改动

整体销售概况从横向单行表改为默认可见的指标卡片，直接展示保存结果中的指标名称、数值和单位。仅适用于完整、未截断、无分组的单行数值聚合结果；不是按标题或销售关键词猜测。空值显示破折号，零值保留，不补造“元”等单位。

每张卡片可展开同任务、同结果表、同指标的证据。原始结果表由“查看结果数据”展开。其他分组图表和多行表不变。HTML 下载使用相同条件显示卡片，保留可展开原表。没有新模型调用、统计计算或保存报告变更。

## 文件

- frontend/src/reporting/ReportPage.tsx：标量结果卡片及原表展开。
- frontend/src/reporting/report.css：自适应列与窄屏两列样式。
- frontend/src/tests/business-report.test.tsx：标量结果、分组单行隔离、零值/缺失与数据展开。
- backend/app/reporting/export.py：HTML 卡片与原表兼容。
- backend/tests/test_report_presentation.py：导出资格与空值单位验证。

## 真实验证

report_f66380c68d99402d8a4363dd24bcc4f6 展示五个保存指标：记录计数 60 条、销售额合计 125,040、均值 2,084、最大值 4,250、最小值 120。sales-cards.png 为实际浏览器截图。真实下载已确认包含 scalar-metrics、对应指标值和原始结果表展开入口。后端已重载供用户直接测试。

## 自动化

前端 78 项通过；TypeScript/Vite 构建通过。报告展示、API、模块相关后端 53 项通过，有原有 Starlette/httpx 弃用提示。首次最终构建发现新增测试 ByRoleOptions 不接受 exact 参数，移除错误参数后重新运行测试与构建，通过；失败日志单独保留。

这是展示局部更新，本轮未重复运行完整后端或 Admin 回归。上轮完整后端 1587 项通过为历史结果，不冒充本轮结果。

需求已先归档 REQ-0097。before.zip、after.zip 保存五个文件前后版本；旧需求、报告和 Prompt 未改写。
