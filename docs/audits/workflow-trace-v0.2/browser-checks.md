# Trace V0.2 浏览器验收记录

2026-10-28，Codex In-app Browser，Admin 5174 → 同源代理 → 本地验收后端 8000。

当前后端指向原 `var/workflow-trace-v01-verification-02`，原 V0.1 失败 Run 保留；新 Run 通过真实 ReportWorkflow 追加。没有向前端提供 Mock fallback 或直接 seed Trace 行。

| 项目 | 实际观察 |
| --- | --- |
| 未授权 | 首次进入 /traces 显示管理员只读访问，后端拒绝数据读取 |
| 只读访问 | 使用独立本地验收凭证，成功交换 Cookie，列表读取 SQLite 中的实际记录 |
| 刷新 | 列表、详情刷新均保持只读访问并重新加载，无需把凭证放进 URL/localStorage |
| 成功 | run_138b68217f9c4b9ca26cd2522b33ecf8 显示 complete，五个阶段成功，整体 3.46s |
| 部分成功 | run_8f390ea052734511bc3b493618e5d0cc 显示 partial，整体 3.57s，有明确部分成功提示 |
| 失败定位 | 原 run_c9c69038b6b44b55b37edafbeb43c264 默认选中事实校验，REPORT_UNVERIFIED_FACT，3/0/3 候选/合法/拒绝 |
| Inspector | 显示实际 Evidence IDs、implication、FREE_TEXT_GUARD/CAUSAL/NUMERIC 等命中，六条当前节点事件；原始候选文本明确不可用 |
| 重试 | run_da8e8959c09f44ecbf534ee2a3113f43 的上一尝试链接确实进入 run_2a66c1c2b62e4b3c83519c2a9d4fc82a |
| 状态过滤 | 使用选择器应用 failed，列表只保留失败 Run |
| 组合过滤 | URL 指定 failed + fact_validator + report-insights-v1.1.9 + 06:30–06:50 UTC，结果仅原 V0.1 一条；刷新后保持 |
| 分页 | limit=1 点击下一页，URL offset=1，实际显示对应第二条记录 |
| 空结果 | version=uncollected-version 显示“没有匹配的运行记录” |
| 退出权限 | 退出只读访问后不再显示数据，显示需要凭证；重新验证后恢复 |
| 日志 | 最终捕获 warn/error 为 [] |

日期控件的浏览器自动 fill 操作被工具拒绝，因此没有宣称通过该方式完成原生日期选择。组合日期通过 URL 与刷新验证；本地时间转换、秒数保留和倒置范围由组件自动化测试验证。

截图：run-explorer-full.jpg、failed-inspector.jpg、partial-run.jpg。截图不包含凭证输入或 Cookie。API/数据库核对见 database-api-check.json。
