# InsightFlow Phase 03-C1：Lifecycle Observability Contract V1.0

## 目标

基于已冻结的 Lifecycle Contract V1.2（REQ-0081/VER-0001）和实际源码，为 InsightFlow 全流程设计可执行的 Workflow 级埋点契约。

本阶段仅进行源码只读审计、设计文档编写及静态契约检查，不修改运行代码、数据库、API 或生产 Trace 行为。

## 任务一：审计现有埋点能力

逐一检查：

- Workflow Root 创建与状态更新。
- TraceSpan 创建、结束及终态限制。
- TraceEvent 的写入与顺序。
- LLMCallRecord 与业务操作的关联。
- Engine、Reporting 当前埋点覆盖。
- Legacy Report Run 的兼容关系。
- Workflow ID、Root ID、业务分支及 revision 的传播路径。

对每个节点标记：已实现、部分实现、未实现。

## 任务二：定义统一节点契约

覆盖 Data Profiler、Intent Parser、Analysis Planner、Plan Validator、HITL、Analysis Engine、Evidence Builder、Chart Builder、Insight Generator、Fact Validator、Report Assembler、Report Persistence。

每个节点必须明确：

1. 稳定 node_key。
2. 真实开始条件。
3. 正常结束条件。
4. 状态映射规则。
5. 成功、部分成功、失败、跳过、中断的业务证据。
6. 必须关联的业务 ID。
7. Span、Event、LLMCallRecord 的职责划分。
8. 重试、重复提交、旧回调和进程恢复行为。

不能为了补齐流程图而生成未实际执行的 Span。

## 任务三：定义状态和事件字典

Span 状态沿用已有合法枚举，不擅自增加新状态。

为澄清、审批、计划修订、执行 claim、任务失败、报告排队、报告提交、旧回调拒绝、恢复和观测缺失定义稳定 Event 名称及最小字段。

明确业务失败与技术失败的区别。

## 任务四：定义 Trace 身份与层级

- 一个 Business Workflow 预留一个不可变 root_run_id。
- 新 Node Span 直接挂 Workflow Root。
- 每次真实节点重入使用新的 span_id 和 node_attempt。
- Event 不构成新的 Trace 层级。
- LLMCallRecord 独立记录每次真实 HTTP 请求。
- Legacy Report Run 保留历史兼容，不改写旧记录。
- Trace 失败不能改变已提交业务结论。

## 任务五：落实 C19-A / C19-B

Report Persistence 必须区分：

- 提交前的授权检查。
- 原子业务提交。
- 提交后的持久事实核验。
- Trace 完成写入。

验证崩溃发生在提交前、提交中、提交后、Trace 写入前时，均不会伪造报告成功。

## 任务六：定义验收矩阵

至少覆盖：

- 所有节点的合法状态和非法转换。
- 同 Workflow 节点重试与不同 Workflow 隔离。
- 部分成功、F0 blocked、无证据和 skipped。
- 旧 revision、旧 active key、旧 report attempt。
- Trace 数据库不可用。
- 业务提交成功但 Trace 写入失败。
- Legacy Report Run 兼容。
- Registry fail-closed 与 Trace fail-open 的差异。

## 交付

输出：

1. Lifecycle Observability Contract V1.0。
2. Node Instrumentation Matrix。
3. Event Dictionary。
4. Trace Identity & Correlation Contract。
5. Recovery & Failure Matrix。
6. Implementation Gap Report。
7. Phase 03-C2 实施建议和准入条件。

## 严格边界

不得修改 Lifecycle Contract V1.2，不得开始 Workflow Switch，不得将设计中的埋点描述为已实现，不得伪造历史 Trace。

完成文档与检查后停止，等待架构评审。
