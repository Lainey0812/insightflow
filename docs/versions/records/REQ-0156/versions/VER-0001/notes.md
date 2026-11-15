# Prompt历史版本表格 V1.1

2026-11-16，REQ-0156，关联REQ-0155。

仅调整Admin工作台的“历史版本”Tab，改为语义化表格。每行展示版本号、来源/状态、登记时间、变更说明和操作。哈希摘要在版本号下展示，Commit在时间下展示；长版本与说明保留完整title和版本详情入口。标记真正当前运行时与调试草稿，不将最新登记当成发布。保留原有分页与空状态。

操作包含查看完整Prompt内容、带入编辑、完整版本详情。查看内容在当前行下方展开跨5列区域，懒加载原始快照，支持收起、加载和错误状态。小屏使用横向滚动，正常桌面宽度五列与操作可见。历史数据不修改、不删除，不新增接口或数据库改动；旧独立历史页原本已是表格，继续兼容。

验证：Prompt相关20例测试通过，TypeScript与Admin构建通过。构建仍有既有大块警告。浏览器用真实13个Intent版本验证表格及当前运行时标识、展开/收起已保存Prompt内容。截图history-table.png、history-expanded.png；未调用模型或改变业务数据。本轮是局部展示改动，没有重跑整个后端或宣称既有Trace回归失败已修复。

修改文件：admin/src/pages/PromptWorkbenchPage.tsx、admin/src/styles.css、admin/src/tests/prompt-workbench.test.tsx。前后源码快照与验证日志一并保留。
