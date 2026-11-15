# InsightFlow — Workflow V1 真实主链路集成任务书

## 一、目标

将已实现的 Data Profiler、Intent Parser V1.3.3、Analysis Planner V1、Plan Validator、HITL 和 Analysis Engine 串联为真实可用的分析流程。

本轮终点为持久化 ExecutionResult，不接入新的 Report Insight Generator。

## 二、集成原则

1. 复用现有服务、API、Schema 和 Repository。
2. 不重写已通过测试的 Engine、Validator 或 HITL。
3. 不引入新的 Agent 编排框架。
4. 使用明确的 Workflow 状态机管理流程。
5. 所有关键阶段持久化，支持刷新恢复。
6. 不允许 Mock Planner、Mock Engine 或 Mock 执行结果进入真实主流程。
7. LLM 失败、业务澄清、计划不可执行必须作为明确状态返回。
8. 不允许跳过 HITL 审批直接执行。

## 三、主流程

用户上传 CSV/XLSX 并输入自然语言问题后：

1. 获取真实 DatasetProfile。
2. 调用真实 Intent Parser。
3. 如 next_action=clarify，暂停流程，返回澄清问题。
4. 如允许继续，调用真实 Analysis Planner。
5. 调用现有 Plan Validator。
6. 保存计划及校验结果。
7. 进入 HITL，展示任务、优先级、可执行性、缺失要求及风险。
8. 用户审核后批准。
9. 服务端核验审批绑定的 dataset、plan、validation 版本。
10. 调用真实 Analysis Engine。
11. 保存 ExecutionResult 并允许查询任务结果。

## 四、状态管理

优先复用现有 Workflow 状态和持久化机制。

至少能够区分：

- profiling
- parsing_intent
- clarification_required
- planning
- validating
- awaiting_approval
- executing
- completed
- failed

若已有状态模型不同，请先给出映射，不要擅自创建第二套状态系统。

## 五、澄清与不确定性

当 Intent Parser 要求澄清时：

- 不得继续生成计划。
- 保存已有意图和问题。
- 支持用户补充信息后继续。

当 Planner 产生 F0 核心任务时：

- 保留该任务。
- 明确显示无法执行的原因。
- 不得伪造完整覆盖。

当存在未解决的核心统计口径、筛选范围或禁止性约束时：

- 不得静默假设。
- 不得将待确认要求当作已确认。
- 按现有审批规则阻止不安全的执行。

## 六、HITL 与执行

使用已有真实 HITL 审批接口。

要求：

- 删除任务后重新校验。
- 计划版本不可变。
- 旧审批不能批准新计划。
- 执行必须绑定已批准快照。
- 重复请求遵循现有幂等机制。
- 单个任务失败不得伪造成全部成功。

不在本轮增加 LLM 自然语言修改计划功能。

## 七、前端集成

将当前用户主入口的 Mock 分析流程替换为真实后端服务。

至少支持：

- 上传文件。
- 输入分析需求。
- 查看澄清问题。
- 查看生成的分析计划。
- 查看每项任务的 P0/P1/P2、F0/F1/F2。
- 查看未满足的核心要求。
- 删除任务并重新校验。
- 批准可执行计划。
- 查看真实执行状态与计算结果。
- 页面刷新后恢复当前流程。

不得通过前端模拟审批或模拟统计结果。

## 八、端到端测试

至少覆盖：

1. 明确需求，正常执行。
2. 需要澄清，暂停后继续。
3. 单一统计任务。
4. 多筛选、多步骤聚合。
5. 排除条件。
6. 排序与 Top N。
7. F0 核心任务。
8. F1 需要派生步骤。
9. 未确认统计口径。
10. 删除任务后重新校验。
11. 旧版本审批失效。
12. 重复执行请求。
13. 单任务失败。
14. LLM 超时或调用失败。
15. 刷新页面恢复。
16. 服务重启后恢复。

必须至少使用一个真实 CSV/XLSX 文件完成浏览器端到端测试，并核对 Pandas 计算结果。

## 九、验收要求

- 真实模型参与 Intent 和 Planner。
- 真实 Validator 负责可行性判断。
- 真实 HITL 负责批准。
- 真实 Engine 执行计算。
- 结果与上传数据一致。
- 不存在未经批准的执行。
- 不存在 Mock 结果冒充真实分析。
- 澄清、失败和部分覆盖均可见。
- 刷新后流程状态可恢复。
- 原有自动化测试不得退化。

## 十、交付

请提供：

- 实际 Workflow 状态图。
- API 与数据流说明。
- 修改文件清单。
- 自动化测试结果。
- 浏览器端到端测试记录。
- 真实数据执行结果。
- 剩余风险和 Bad Case。

本轮不修改 Report Insight Generator，也不新增多 Agent 架构。
