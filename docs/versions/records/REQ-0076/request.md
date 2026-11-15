# InsightFlow · Phase 02：Business Workflow 数据契约设计

## 角色与目标

你是一名资深系统架构师，熟悉 FastAPI、数据库建模、事务一致性、Agent Workflow、Trace 和渐进式数据迁移。

请基于 InsightFlow 当前真实源码和数据库结构，设计从 `Session 1:1 Workflow` 迁移到 `Session 1:N Workflow` 的完整数据契约。

本阶段仅进行只读审计和方案设计，不修改业务代码、数据库 Schema、测试或现有数据。

## 一、必须遵守的架构约束

1. 一个 Session 对应一个持续的分析对话空间。
2. 一个 Session 可以包含多个独立 Business Workflow。
3. 每个 Business Workflow 对应一个独立分析目标。
4. 每个 Business Workflow 对应一个 Workflow Root TraceRun。
5. Trace 保持 Root + Node Span 两层，不新增第三层 Trace。
6. 不新增独立 Attempt 实体；允许使用执行尝试标识进行并发隔离。
7. Trace 采集失败不能阻断正常业务执行。
8. 已完成的 Root CAS、旧回调隔离和 Report 提交确认机制必须保留。
9. 历史 PlanVersion、Approval、Execution、Report、Span 和 Report Run 不得丢失。

## 二、审计当前数据模型

逐项检查以下实体的真实 Schema、主键、外键、唯一约束和读写路径：

- Session
- Dataset / DatasetProfile / Manifest
- PlanVersion
- Approval
- Execution / ExecutionResult
- ReportGeneration / Report
- TraceRun / TraceSpan / TraceEvent
- LLMCallRecord

特别检查：

- 哪些业务状态目前只存在于 Session。
- 哪些查询通过 session_id 读取当前计划、审批、执行和报告。
- 哪些幂等键使用 session_id + plan_version。
- 哪些位置假定一个 Session 只有一个 Root。
- 哪些记录缺少足够信息，无法准确关联到特定 Workflow。

## 三、设计目标数据模型

提出 Business Workflow 的最小字段契约，至少评估：

- workflow_id
- session_id
- dataset_version_id 或等价数据快照引用
- origin_message_id
- parent_workflow_id
- current_plan_version
- lifecycle_status / current_phase
- revision
- created_at / updated_at

区分哪些字段应该持久化，哪些应该由 Lifecycle Read Model 派生，避免创建第二套互相冲突的业务状态机。

重点设计：

1. Workflow 与 Session 的关系。
2. Workflow 内独立 PlanVersion 编号。
3. Approval 对 PlanVersion 的精确引用。
4. Execution 对审批快照的精确引用。
5. Report 对 Execution 和 Workflow 的精确引用。
6. TraceRun 对 Business Workflow 的关联。
7. Dataset 版本变化时的隔离规则。

## 四、设计兼容迁移方案

采用 Expand → Backfill → Validate → Switch → Contract 的渐进式迁移方法。

要求说明：

- 每一步的数据库 Schema 变化。
- 历史 Session 如何回填默认 Workflow。
- 如何保留现有主键与历史引用。
- 如何避免迁移过程中数据串线。
- 如何处理回填失败与部分完成。
- 如何验证回填前后业务数据一致。
- 旧 API 如何兼容。
- 旧版本代码回滚的限制。
- 哪些变更不可逆，何时才能执行。

不要假设所有历史记录都能准确归属。对于无法确定归属的数据，必须明确标记并提出处理策略。

## 五、设计 API 与前端迁移

审查现有用户端和 Admin 的 Session 路由、轮询、恢复、审批、执行和报告入口。

提出最小兼容改造方案：

- Session 负责对话和 Workflow 列表。
- Workflow ID 负责定位具体分析任务。
- 审批、执行、报告、Lifecycle 均以 Workflow 为明确业务作用域。
- 不允许多 Workflow 场景下静默使用 Session 最新记录。
- 保留现有单 Workflow 用户的兼容路径。

## 六、必须设计的测试

至少覆盖：

1. 一个 Session 创建两个 Workflow。
2. 两个 Workflow 各自存在 PlanVersion 1。
3. 两个 Workflow 独立审批。
4. 两个 Workflow 独立执行。
5. 两个 Workflow 独立生成报告。
6. 一个 Workflow 失败不影响另一个。
7. 一个 Workflow 修订计划不影响另一个。
8. 旧 Worker 回调不能污染新 Workflow。
9. Trace 缺失不影响 Business Workflow 存在。
10. 历史 Session 数据正确回填。
11. 旧 API 兼容且不产生歧义。
12. Root CAS 和 Report stale callback 保护持续有效。

## 七、交付物

请输出：

1. 当前 ER 模型与目标 ER 模型。
2. 数据契约字段表。
3. 受影响源码文件与 API 清单。
4. 数据库迁移分阶段方案。
5. 历史数据回填及一致性验证方案。
6. 回滚与兼容性风险。
7. 测试矩阵。
8. 待产品确认的关键决策及推荐方案。

每个重要结论注明真实源码路径与行号。

区分：

- 已由源码验证的事实。
- 根据事实推导的风险。
- 建议采用的设计方案。

**完成设计报告后停止，不进行任何代码或数据库修改，等待架构评审。**
