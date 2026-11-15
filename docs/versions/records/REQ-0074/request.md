先做一次只读兼容性审计，确认现有系统中哪些地方仍然隐含 `session_id = workflow_id` 的假设，尤其是：

- Session 唯一 Root 约束。
- PlanVersion、Approval、Execution 和 Report 的归属键。
- “按 Session 查询最新结果”的所有入口。
- Lifecycle Read Model 的聚合依据。
- 前端路由与当前 Session 状态管理。
- TraceRepository 的 CAS 与 Report stale callback 问题。
