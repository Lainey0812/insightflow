用户对 Phase 2-A 设计待决策问题的选择（AskQuestion 原始回答）：

- Q1（新格式 Golden 运行来源）：scripted — 脚本化 Agent 在临时目录生成，不调用 LLM，仅验证查看链路。
- Q2（数据集冻结声明）：not_declared — Phase 2 全部显示 NOT_DECLARED，冻结声明格式另立需求。
- Q3（TC SQLite Trace）：closed — 不开放，只展示 case record 的 plan/steps/result_tables。
- Q4（跨运行汇总指标）：none — Phase 2 不做。
- Q5（endpoint 脱敏与凭证）：drop_read — endpoint 整项删除，仅需只读凭证。
- Q6（API 前缀）：v1 — /api/v1/admin/evaluations。
