REQ-0052 / prompt-registry-v1.0-readonly-admin，2026-10-29。

复用 V0.1 单库与契约，新增独立只读查询服务、列表/历史/详情/Diff/调用摘要 API，以及五类 Admin 路由、复制、分页、额外授权原文读取、Report Trace/Inspector 模板跳转。最新登记与实际运行时 pin 分别展示，不回填历史。

后端原有文件仅 main.py（传已有 pin）与 api/admin.py（挂只读接口）调整；未修改原模板库、捕获、Source 校验、三个节点、Prompt、Validator/HITL/Engine/Report 业务逻辑。没有新库/迁移、依赖升级或模型调用。

最终测试：Backend 770 passed，Admin 59 passed，原 frontend 52 passed；两前端类型检查/构建通过。原 3 条路由测试因全局提示加入 Prompt 仍断言旧文案失败，更新为准确文案，其他原行为断言保留。早期日志、截图与最终结果都另存。

浏览器使用独立 localhost:4175 与隔离 API8011，3 个真实当前模板（每节点仅1版）与2条本地脚本响应调用。验证授权、三节点正文、筛选、单版本无虚假Diff、调用摘要与raw额外授权、刷新原文隐藏、历史缺失unavailable。截图及真实隔离API响应已保留，外部LLM调用0，不冒充用户生产历史或模型质量评测。双版本准确性由明确测试夹具的API原文重建/组件测试验证，未为截图虚构旧版。

本目录保存前后源码 ZIP/SHA、审计、修改清单、API例、截图、浏览器记录、日志和操作说明。默认用户库在审计时尚无Registry文件，未向其写入测试数据；临时验证服务和标签已关闭，原5174及用户标签保留。

历史文件档案不自动导入Registry，旧Run缺失不补当前Prompt；没有发布系统，变量类型Schema未登记显示unavailable；仍采用现有管理员只读+raw双凭证，未宣称RBAC/加密；大量历史/大包Diff性能仍需后续验证。后端需启动/重启加载新API。
