这一阶段需要解决三个已复现的问题：Root revision 并发覆盖、同 revision 旧回调污染状态，以及旧 Report 未成功提交却将 Trace 标记为 `complete`。

验收标准是：

1. Root 状态更新具有原子性，并发旧请求无法覆盖新状态。
2. 合法重试可以恢复原 Workflow，但迟到回调不能修改当前有效执行。
3. Report Trace 的成功状态必须与实际业务提交结果一致。
4. 保留历史 Span 和 Report Run，不引入第三层 Trace。
5. 原有业务流程和 Lifecycle Read Model 回归测试通过。
