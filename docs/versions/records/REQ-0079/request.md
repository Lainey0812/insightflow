# InsightFlow Phase 03-A.1：Lifecycle Contract V1.1

## 任务目标

基于当前 `Lifecycle Contract V1.0` 和实际源码，修订并冻结 V1.1 契约，为后续 Workflow Policy Validator 和 Lifecycle Read Model V2 提供可执行的设计依据。

本阶段只允许文档修改、源码只读审计及必要的设计验证，不允许修改业务代码、数据库或 API。

## 一、修订五项 P0 问题

### 1. Control Status 与 Business Lifecycle

明确 `COMPLETED` 仅表示 Engine 执行结束，不等于完整报告交付。

补充 Engine 完成后，Report 未开始、排队、生成、失败、成功交付的命令授权矩阵。

禁止仅凭 Session/Workflow `COMPLETED` 判断整个分析成功。

### 2. Partial Success 与 Reporting

保留现有 Business Lifecycle 枚举。

明确 `execution_outcome`、`delivery_status` 与 `business_lifecycle` 是不同维度。

补充 Engine 部分成功、Report 正在生成、Report 失败及 Report 部分交付的组合判定规则。

不得因 Reporting 进入 running 而隐藏已经发生的任务失败。

### 3. 已完成 Workflow 的修订边界

V1.1 默认禁止 `Root.complete → running`。

如未来需要支持完成后修订，必须另行定义业务分支、PlanVersion、审批、执行和历史报告保留规则。

独立新分析目标创建新 Workflow，不复用已完成 Root。

检查现有 `COMPLETED → AWAITING_APPROVAL` 兼容路径，明确它是 legacy 行为还是目标行为，不得直接删除旧兼容能力。

### 4. Recover、Retry、Resume

分别定义三种操作的语义、资格和状态变化。

当前 Engine 的进程中断处理只声明支持 Recover，不宣称已实现任务级断点 Resume。

补充中断后的任务结果保留、重复执行防护及报告恢复规则。

### 5. Workflow Fencing

定义所有异步业务写入必须验证的 Workflow 归属、当前分支、revision、active key、精确业务引用及幂等键。

明确哪些字段在各阶段必须存在，避免使用不合理的全字段非空校验。

明确旧 Worker、旧 Planner 回调、旧 Execution、旧 Report attempt 的拒绝条件。

## 二、补充三项 P1 约束

1. 新 Trace Node Span 必须直接归属于 Workflow Root，历史嵌套 Span 保持兼容读取。
2. ReportGeneration `unavailable` 不提供当前不支持的重试操作。
3. 区分 Trace 采集失败和 Prompt Registry 请求日志失败，不混用故障语义。

## 三、输出契约

V1.1 至少包含：

- 完整状态与活动定义。
- 状态转换矩阵。
- 命令授权矩阵。
- Engine / Report 结果组合判定矩阵。
- Recover / Retry / Resume 矩阵。
- Workflow Fencing 规则。
- Trace Root / Span 转换约束。
- Legacy 兼容与迁移边界。
- 可直接转化为自动化测试的验收案例。

所有规则必须标记为：

- `现有`
- `结构已具备`
- `目标`

不能将尚未实现的能力描述为已上线。

## 四、验收要求

完成后执行文档一致性检查，并逐项回答：

1. 是否存在同一业务事实对应相互矛盾的生命周期结论？
2. 是否存在允许执行命令却没有合法状态转换的情况？
3. 是否存在状态允许转换但缺少持久业务证据的情况？
4. 是否可能因迟到回调覆盖新 Workflow 的结果？
5. 是否错误地将 Engine 成功视为完整报告交付？
6. 是否存在不受支持的 Resume 或 Retry 操作？
7. 是否会破坏历史 Session、Root 或 Report Run 的兼容性？

## 五、交付要求

输出 V1.1 完整文档、V1.0 → V1.1 变更清单、尚未解决的问题及下一阶段实施建议。

**完成后停止，不自动开始 Workflow Policy Validator 开发或状态权威切换。**
