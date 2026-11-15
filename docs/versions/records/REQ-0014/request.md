# InsightFlow — HITL V1 真实审批闭环开发任务书

## 一、开发背景

当前 InsightFlow 已具备：

- Data Profiler：真实数据画像。
- Plan Validator：结构化分析计划校验。
- 六类确定性计算内核。
- Analysis Engine V1：真实文件加载、执行编排、ExecutionResult 持久化及幂等处理。
- HITL：已有 Mock 审核界面及部分状态逻辑。

当前问题：

HITL 尚未与真实 ValidatedAnalysisPlan、Validator 和 Analysis Engine 形成完整闭环。

## 二、开发目标

实现以下链路：

ValidatedAnalysisPlan → HITL 审核 → 用户修改 → Validator 重新校验 → 计划版本保存 → 用户确认 → 服务端审批 → Analysis Engine 执行。

本阶段不依赖 LLM，允许使用人工构造的真实合法 AnalysisPlan 进行测试，但生产审批记录必须来自真实的用户确认行为。

## 三、开发前代码检查

先检查：

1. 现有 HITL 前端组件、状态管理及 Mock 数据来源。
2. Plan Validator 的输入输出 Schema。
3. AnalysisPlan 的持久化方式及版本字段。
4. Analysis Engine 的审批校验接口和执行请求结构。
5. session_id、dataset_id、dataset_version 的关联机制。
6. 现有 API 路由、数据库结构和测试。

优先复用已有代码，不要另建第二套 HITL 系统。

如果发现公共 Schema 不兼容，先输出兼容性问题及调整方案。

## 四、HITL 页面

展示真实计划中的每个 AnalysisTask。

每个任务至少展示：

- 任务标题。
- 业务分析问题。
- 优先级：P0 / P1 / P2。
- 优先级理由。
- 可行性：F2 / F1 / F0。
- 不可执行原因。
- 分析方法摘要。

用户可以：

1. 查看分析计划。
2. 删除任务。
3. 查看修改后的校验结果。
4. 确认计划并执行。

F0 任务必须清晰显示阻断原因，不能通过前端隐藏阻断状态。

F1 任务只有在其前置转换被当前系统支持、已纳入操作链并通过校验后，才能列入可执行任务。

## 五、删除任务与重新校验

用户删除任务时：

1. 前端发送修改请求。
2. 后端读取当前最新计划版本。
3. 创建新的计划草稿版本。
4. 删除指定任务。
5. 重新调用 Plan Validator。
6. 更新 coverage_status、executable_task_ids、blocked_task_ids 和 unmet_core_requirements。
7. 保存新的计划版本。
8. 返回新的 ValidatedAnalysisPlan。

不得只在前端数组中删除任务，而不更新服务端计划。

删除 P0 任务后，如果核心分析目标无法满足，必须显示业务目标覆盖不足，并在 coverage_status=blocked 时禁止批准。

不允许静默改变用户的 analysis_goal。

## 六、计划版本管理

计划版本必须不可变。

至少记录：

- plan_id
- plan_version
- dataset_id
- dataset_version
- validation_version
- created_at
- change_type
- change_summary

每次有效修改生成新版本。

旧版本可供审计查看，但不能覆盖最新计划。

并发修改必须进行版本冲突检查，防止两个请求覆盖彼此的结果。

## 七、服务端审批

用户点击“确认并执行”时，后端必须验证：

- 当前计划属于对应 session。
- 数据集版本一致。
- 当前计划是最新有效版本。
- Validator 校验结果有效。
- 没有阻断性不确定性。
- coverage_status 不为 blocked。
- 至少存在一个可执行任务。
- 用户已确认 partial coverage 等重要限制。

通过后生成不可变审批记录。

审批记录至少包含：

- approval_id
- session_id
- plan_id
- plan_version
- validation_version
- dataset_id
- dataset_version
- approved_at
- approval_status
- acknowledged_warnings

不得仅依靠前端传入的 approved=true 判断是否允许执行。

## 八、Analysis Engine 集成

审批成功后，前端通过现有接口提交：

POST /api/v1/executions

请求中使用已批准计划对应的：

- session_id
- plan_id
- plan_version
- execution_request_id

Analysis Engine 从服务端读取批准快照。

不允许前端提交一份任意 AnalysisPlan 绕过审批。

执行成功后保存 execution_id，并建立与 approval_id、plan_version 的关联。

## 九、API 设计

优先兼容现有路由。

建议能力包括：

- GET：读取当前真实 ValidatedAnalysisPlan。
- POST：删除指定任务并重新校验。
- GET：读取计划版本历史。
- POST：确认并批准计划。
- GET：读取审批记录。

具体路径遵循现有项目规范，不强制新增重复接口。

## 十、状态管理

至少区分：

- awaiting_review
- validating
- awaiting_approval
- approved
- executing
- completed
- execution_failed

计划修改后，之前的审批不得继续授权新版本执行。

执行失败不应自动撤销原始审批记录，但重试必须遵循现有 Engine 幂等与版本校验机制。

## 十一、异常与边界

必须处理：

1. 删除不存在的任务。
2. 删除最后一个可执行任务。
3. 删除 P0 导致 coverage blocked。
4. F0 任务被错误提交执行。
5. 计划版本冲突。
6. 数据集版本不一致。
7. 未确认 partial coverage。
8. 重复审批请求。
9. 审批后计划被修改。
10. 未授权 session 访问。
11. Validator 重新校验失败。
12. Engine 执行失败。

所有错误返回明确错误码和可读信息。

## 十二、测试要求

### 单元测试

覆盖任务删除、版本生成、审批规则、coverage 检查、版本冲突及状态转换。

### 集成测试

至少验证：

- 真实计划读取。
- 删除任务后重新校验。
- 新计划版本持久化。
- 审批快照持久化。
- 旧版本无法绕过最新审批。
- 批准计划能够被 Analysis Engine 执行。
- 未批准计划被拒绝。

### 端到端测试

使用真实上传的 sales.csv 和人工构造的有效 AnalysisPlan：

1. 上传数据。
2. 保存计划。
3. 调用 Validator。
4. 在 HITL 页面查看计划。
5. 删除一项任务。
6. 检查新版本及校验结果。
7. 用户确认最新版本。
8. 创建服务端审批。
9. 调用真实 Analysis Engine。
10. 读取并展示真实 ExecutionResult。

## 十三、验收标准

- HITL 不再使用 Mock 任务作为生产审核数据。
- 页面展示的任务和服务端计划完全一致。
- 删除任务能够触发真实重新校验。
- 计划版本不可变、可追溯。
- 审批绑定准确的计划及数据集版本。
- 未批准计划无法执行。
- 最新已批准计划能够调用真实 Engine。
- 所有已有 Analysis Engine 测试保持通过。
- 不破坏 Data Profiler 和 Plan Validator 的既有功能。

## 十四、开发交付要求

请分两步执行：

**第一步：审查现有代码并给出实施计划。**

列出复用模块、需要修改的文件、接口兼容风险、数据库迁移需求。

**第二步：实现并验证。**

完成后输出：

- 修改文件清单。
- API 与 Schema 变更。
- 测试结果。
- 一次真实 HITL 审批到 Engine 执行的完整验证记录。
- 尚未完成的问题。

本阶段不要扩展至 LLM 自然语言修订、Report 自动生成或复杂 Agent 编排。
