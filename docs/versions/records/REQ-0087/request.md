# InsightFlow Phase 03-C2 — End-to-End Trace Closure

## 唯一目标

完成一次真实 Workflow 从准备、审批、Analysis Engine 到 Reporting 的全链路可观测性验证。

本阶段不以部分节点接入、单元测试数量或设计文档完成作为验收通过依据。

## 实施重点

1. 以已登记的 `workflow_id` 和 `root_run_id` 为唯一关联依据，贯通 HITL、Engine 和 Reporting。
2. 复用现有准备阶段和 HITL 埋点，不重复创建节点。
3. Engine Span 必须关联真实 Execution ID、执行结果和业务持久化记录。
4. Reporting Span 必须关联真实 ReportGeneration attempt、Report ID 和持久提交证据。
5. 记录真实开始、结束、耗时、结果引用、异常及重试。
6. Trace 缺失必须明确标记为 collection gap，不得补造未发生的节点。
7. Trace 故障不得改变业务执行结果。
8. 对于缺少必要 Workflow 归属或 fencing 的提交路径，只修复该路径的最小阻断，不扩展为全系统重构。

## 真实验收

使用真实 CSV、真实 LLM 和现有业务 API，完成：

准备 → HITL 审批 → Engine 执行 → Reporting → 报告持久化。

最终必须提交：

- workflow_id 与 root_run_id。
- 实际发生的节点 Span 列表。
- 各节点耗时、状态和结果引用。
- Approval、Execution、ReportGeneration、Report 的业务关联证据。
- LLM 调用记录及关联。
- 异常、重试和 collection gap 的验证结果。
- Trace 故障不影响业务结果的测试证据。
- 完整回归测试结果。

如果某个节点没有实际执行，不得为了使时间线完整而创建对应 Span。

## 验收判定

只有真实全链路能够通过 `workflow_id` 查询，且业务记录与 Trace 关联一致，才标记 Phase 03-C2 为 Completed。

否则保持 In Progress，列出尚未闭合的节点和最小阻断原因。

## 严格边界

不启动 Admin 生命周期时间线开发，不执行 Workflow Switch，不开放多 Workflow，不修改冻结契约，不伪造历史 Trace。

完成后停止，等待验收。
