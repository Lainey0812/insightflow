# Prompt Snapshot Foundation V0.1 — phase1 audit and proposal

用户需求 REQ-0049；本记录为第一阶段交付，不代表已实施或用户已同意。

重新检查三个服务、完整 Prompt 组合、重试文字、动态 Schema、Trace/NodeInput 标识、Report 入队时机和 Git。当前非 Git 仓库，无 Commit 可恢复；保留真实观察，不初始化 Git。

方案与先前只读 Registry 提案分开：新运行使用完整静态模板包，Snapshot/请求前 Binding 作为权威依据 fail-closed，Trace 仍 best-effort。提出独立 SQLite 内容/版本/调用绑定/Report attempt 固定表，不复制业务执行记录；Intent/Planner 复用现有调用标识，Report 接入已有 Manifest/Span，不伪造未存在的上游 Run。

拟定数据契约、稳定哈希、冲突/并发/重启与历史恢复分类、改动文件、原/新请求逐字比对和故障测试计划。详见 audit-and-plan.md、PromptSnapshot.proposal.schema.json。

本次只保存需求、审计与源码基线（109 个文件）以及静态观察，没有修改应用、创建快照表、迁移数据库或调用模型；没有冒用先前测试成绩。待用户确认四项兼容/故障边界后才实施。
