# InsightFlow：Lifecycle Observability MVP — Vertical Slice 01

## 目标

停止扩展生命周期设计文档，基于现有冻结契约，完成第一条真实可运行的 Workflow 节点埋点链路。

优先接入：

Data Profiler → Intent Parser → Analysis Planner → Plan Validator。

## 实施原则

1. 复用现有 TraceRecorder、Root 和 Span 能力，不重新设计追踪系统。
2. 每个节点记录真实开始、结束、耗时、结果及错误。
3. 新 Span 直接归属当前 Workflow Root。
4. Trace 写入必须 fail-open，不影响业务主流程。
5. 不修改 Session 状态权威，不执行 Workflow Switch。
6. 不为尚未执行的节点创建虚假 Span。
7. 复用现有合法状态枚举，不新增状态。
8. 保留旧 Trace 和 Report Run 的兼容读取。

## 执行步骤

第一步：审计上述四个节点现有的真实调用入口，确认是否已有埋点，避免重复记录。

第二步：实现最小 Trace Adapter，并接入四个真实节点。

第三步：为成功、失败、重试、模型超时、Schema 错误及 Trace 数据库不可用编写自动化测试。

第四步：使用真实 CSV 执行一条完整的准备阶段链路，验证四个节点的 Span 及 Root 归属。

第五步：输出真实 Trace 结果、耗时、异常测试结果及尚未覆盖的节点。

## 严格边界

- 不修改 Engine 和 Reporting。
- 不修改 Lifecycle Contract。
- 不实现新的状态机。
- 不做全量 Workflow Writer 重构。
- 不修改业务执行结果。
- 不因埋点异常阻断用户流程。
- 若现有运行路径无法可靠确定 Workflow 归属，则停止该节点接入并报告阻断原因，不通过 Session 猜测 Workflow。

## 完成标准

- 四个节点能够记录真实执行 Span。
- Span 与 Workflow Root 的关联正确。
- 同一节点重试产生独立 attempt。
- Trace 失败不会导致业务失败。
- 现有业务测试无退化。
- 提供至少一条真实运行 Trace 的验证结果。

完成后停止，等待下一阶段验收。
