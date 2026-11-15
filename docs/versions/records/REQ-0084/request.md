# InsightFlow — Workflow Identity Bootstrap V1

## 目标

为现有 Session 单流程准备路径建立可靠的 Business Workflow 身份登记和显式传播，使 Data Profiler、Intent Parser、Analysis Planner、Plan Validator 能够关联唯一 Workflow Root。

这是一个最小阻断修复，不是 Workflow 状态权威切换。

## 实施要求

1. 审计现有 Session 创建、准备流程入口、Business Workflow Schema、Root ID 预留、Trace Link 以及四节点埋点代码。
2. 优先复用现有 Phase 02 的 Workflow 创建和幂等机制，不重复实现第二套身份系统。
3. 在业务数据库中原子登记 Workflow、不可变 root_run_id 和创建幂等键。
4. 只允许现有单流程路径创建或解析一个 Workflow；对冲突、多候选、归属不一致的情况显式拒绝，不做静默选择。
5. 在准备流程上下文中显式传递 workflow_id、root_run_id，不通过 Session 查询推断 Root。
6. 复用已有 TraceRecorder，避免重复 Span；新 Span 必须直接归属对应 Root。
7. Trace Root 物理创建失败时保持业务 fail-open，并允许之后幂等修复。
8. 保留 SessionState 业务权威，不接入 Workflow Policy Validator 的生产写入授权，不执行 Switch。
9. 不改 Engine、Reporting、HITL 或 Admin。
10. 不为历史数据伪造 Workflow 执行记录。

## 测试

覆盖首次创建、同请求重放、不同幂等键冲突、并发创建、Root 物理缺失、Trace 数据库不可用、身份不匹配、已有 Span 复用，以及原有 Session 准备流程回归。

必须通过真实 CSV 准备流程验证，证明四节点使用的是明确登记的 Workflow 身份，而不是 Session 推断。

## 完成标准

- 业务数据库中存在真实登记的 Workflow。
- workflow_id 和 root_run_id 不可变。
- Trace 关联能够正确恢复。
- 四节点没有重复 Span。
- Session 原有行为不退化。
- 至少一条真实准备流程产生可核验的 Trace。

完成后停止，提交代码差异、测试结果、真实业务记录与 Trace 关联证据。
