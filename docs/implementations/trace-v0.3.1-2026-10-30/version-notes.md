# Trace V0.3.1：准备阶段 Root/Span 与真实 Call 关联

依据 REQ-0059 实施第一阶段；需求原文已在修改前归档。没有实施 V0.3.2/0.3.3，没有升级 Prompt 内容或修改模型参数。11 个既有后端源码文件修改、4 个新增 Python 文件，前端/Admin 源码未改。

交付正文 delivery.md，冻结前后源码 before-source.zip / after-source.zip；请求组装 before/after 对照三节点 payload 完全一致；旧 composition-v0.1 模板保留，新登记 composition-v0.2-trace-v0.3.1 表示埋点代码组合变化。

自动化 806 passed，1 个已有依赖弃用提示。专项覆盖 18 个测试实例，包括迁移、并发、重试、澄清、错误、启动恢复、fail-open、权限和真实 Call 关联。所有命令日志保留，包括首次路径错误。

真实前台使用已授权销售 CSV 和同一阿里云模型：2 个新 Session，6 次真实模型调用。A 正常准备等待审核，C 澄清/补充复用 Root，B 自然 Planner 超时，D 人工重试保留失败 Attempt 并新增 Attempt（仍然超时），四个追踪场景通过；不把重试失败宣称成规划成功，没有批准或执行任何分析。API/SQLite 状态交叉核对，前台刷新恢复。证据位于 live-verification，含 4 张真实截图及中间持久状态。

剩余问题：复杂销售 Planner 超时、原 HITL 约束映射阻断均未修复；Root 仅准备阶段，没有全链路最终状态聚合/Progress UI。服务崩溃及内部 LLM 格式重试仅由自动化验证，本轮没有真实注入。提交阶段验收，待用户确认后才进入下一阶段。

保留首次差异清单误将 5 个未纳入基线 ZIP 的既有 JSON fixture 识别为 added 的记录；source-changes-final.json 给出准确同范围清单，未改这些 fixture。没有删除历史需求/报告/数据库/请求快照，也没有初始化 Git。
