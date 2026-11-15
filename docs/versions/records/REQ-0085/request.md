# InsightFlow — Lifecycle Instrumentation Vertical Slice 02

## 目标

基于 REQ-0084 已完成的 Workflow Identity Bootstrap，将现有四节点准备阶段的 Trace 扩展至 HITL、Analysis Engine 和 Reporting。

最终让同一个 Workflow Root 覆盖：

Data Profiler → Intent Parser → Analysis Planner → Plan Validator → HITL → Analysis Engine → Reporting。

## 一、实施前检查

只读检查现有 HITL、Engine、Reporting 的业务入口、持久化提交点和 Trace 能力。

确认：

- workflow_id 和 root_run_id 能够从准备阶段传递至后续操作。
- Approval、Execution、ReportGeneration 和 Report 的业务归属可精确验证。
- C19-A/C19-B 可以在真实提交路径中正确使用。
- 现有 Span 不会被重复包装。

发现身份不明确或业务提交缺少必要 fencing 时，停止该路径的接入，报告最小阻断原因。

## 二、HITL 埋点

记录真实审批、拒绝及计划修订操作。

要求：

- 用户等待期间不创建长期运行 Span。
- 审批结果必须关联实际 PlanVersion 和 Approval。
- 审批失败、版本冲突、重复请求能够区分。
- Trace 写入失败不改变审批结果。

## 三、Analysis Engine 埋点

在真实 Execution claim 后记录节点执行。

要求：

- 关联 workflow_id、root_run_id、execution_id、plan_version_id。
- 区分节点执行状态与业务执行结果。
- 支持 success、partial_success、failed 等实际结果。
- 中断和重试不得覆盖历史 Span。
- 不实现尚未支持的 Engine Resume。

## 四、Reporting 埋点

覆盖报告生成、校验、组装与持久化的真实执行节点。

要求：

- 关联 execution_id、report_attempt 和真实业务记录。
- 遵守 C19-A → 业务事务 → C19-B。
- 仅在持久提交成功后记录 Report Persistence 完成。
- 旧 attempt、旧 revision 不得错误完成当前 Span。
- 保留历史独立 Report Run，不伪造旧记录。

## 五、测试与真实验收

使用真实 CSV 和已配置的 LLM，完成一次：

准备 → 审批 → 执行 → 报告生成 → 报告持久化。

验收：

1. 所有真实执行节点关联同一个 Workflow Root。
2. 不存在重复 Span 或虚构节点。
3. 每个 Span 具有真实耗时、结果及必要的错误信息。
4. 业务成功但 Trace 失败时，业务结果保持正确。
5. Engine 部分成功、报告失败、重复审批、旧回调均有对应测试。
6. 旧 Session API 与历史 Trace 兼容。
7. 后端、Frontend、Admin 原有测试不退化。

## 六、严格边界

- 不切换 Session 状态权威。
- 不开放多 Workflow 并发执行。
- 不实施全系统 Workflow Switch。
- 不重构无关模块。
- 不为了埋点修改业务成功标准。
- 不因 Trace 故障阻断业务。

## 七、交付

提交代码差异、测试结果、真实业务记录与 Trace 关联证据，以及未完成的节点和阻断项。

完成后停止，等待验收。
