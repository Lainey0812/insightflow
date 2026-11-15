# InsightFlow — Analysis Engine V1 集成开发任务

## 一、任务目标

基于现有 InsightFlow 工程和已经实现的六类计算内核，补齐真实 Analysis Engine 的执行编排能力。

最终实现：

**真实上传文件 → 已验证且批准的 AnalysisPlan → 操作链执行 → ExecutionResult → 持久化**

本阶段不重新实现已有计算内核，不接入 LLM，不修改 HITL 页面或 Report Module 的业务逻辑。

## 二、开发前检查

先检查现有代码，确认：

1. 六类计算操作的函数签名、参数 Schema 和测试情况。
2. 上传文件的实际存储路径、数据集 ID 和版本机制。
3. DatasetProfile 与原始数据文件的关联。
4. Plan Validator 的输入输出及 Capability Registry。
5. HITL 审批状态与计划版本的现有存储方式。
6. ExecutionResult 是否已有 Schema、数据库表或部分实现。

**优先复用现有代码，不要创建第二套重复的执行器或数据模型。**

如果现有 Mock HITL 尚不能提供真实批准记录，允许在测试中构造经过验证的审批快照，但生产执行入口必须拒绝未批准计划。

## 三、核心开发内容

### 任务 A：真实数据加载

实现根据 `dataset_id + dataset_version` 加载用户上传的数据。

要求：

- 支持现有 CSV/XLSX 文件格式。
- 与 Data Profiler 使用一致的数据解析规则。
- 保证读取的是指定版本的数据。
- 处理文件不存在、格式错误、数据版本不匹配等异常。
- 不允许客户端直接传入任意本地文件路径。

### 任务 B：执行入口与权限校验

执行请求应包含：

- `session_id`
- `plan_id`
- `plan_version`
- `execution_request_id`

服务端根据这些标识读取已保存的批准计划。

执行前检查：

- 计划是否已经批准。
- 是否为用户批准的有效版本。
- 数据集版本是否一致。
- Validator 结果是否有效。
- 是否存在允许执行的任务。
- 是否存在阻断性不确定性。

校验失败必须拒绝执行，不得自动改用其他计划版本。

### 任务 C：操作链执行

复用现有六类操作：

- filter
- group_aggregate
- aggregate
- sort
- top_n
- derive

每个任务独立读取数据视图，按 `steps` 顺序执行。

严格按照操作 Schema 传递参数，不允许执行任意 Python、SQL 或动态代码。

每个步骤应记录：

- step_id
- operation
- 输入行数
- 输出行数
- 执行耗时
- 警告或错误

### 任务 D：ExecutionResult

定义或补全标准化执行结果。

至少包含：

- execution_id
- session_id
- dataset_id / dataset_version
- plan_id / plan_version
- 整体执行状态
- task_results
- 执行时间
- 错误与警告信息

每个 TaskExecutionResult 至少包含：

- task_id
- status
- result_id
- columns
- rows 或 result_ref
- row_count
- execution_metadata
- error

完整结果和预览数据必须区分，不能把预览行数误当作真实结果行数。

### 任务 E：任务级错误隔离

支持：

- success
- partial_success
- failed

单个任务失败时，其他独立任务可以继续执行。

每个失败任务必须返回明确错误代码、任务 ID、步骤 ID 和可读错误信息。

空结果不应自动判定为执行失败。

### 任务 F：执行结果持久化

保存：

- 执行记录
- 数据集与计划版本引用
- 各任务执行状态
- 完整计算结果或结果文件引用
- 执行日志与错误信息

保证后续 Report Module 能通过 execution_id 获取真实结果。

对相同 execution_request_id 实现幂等处理。

## 四、集成边界

本阶段允许：

- 新增 Analysis Engine 编排服务。
- 补充 ExecutionResult Schema。
- 新增执行记录和结果持久化。
- 对已有接口进行必要的兼容性适配。
- 新增测试。

本阶段禁止：

- 重写 Data Profiler。
- 重写六类计算内核。
- 重写 Planner 或 HITL。
- 接入新的 LLM 工作流。
- 开发图表或洞察生成。
- 用 Mock 数据冒充真实执行结果。

## 五、验收测试

必须完成以下场景：

1. 从真实上传 CSV/XLSX 加载数据。
2. 使用人工构造且通过 Validator 的批准计划执行。
3. 正确执行 filter → group_aggregate → sort → top_n。
4. 正确执行数值聚合。
5. 正确执行已支持的日期派生。
6. 拒绝未批准计划。
7. 拒绝数据集或计划版本不一致。
8. 拒绝不支持的操作。
9. 单任务失败时保留其他成功结果。
10. 正确处理空结果。
11. 相同请求不会重复产生执行。
12. 执行结果保存后能够重新读取。

计算结果应与独立 Pandas 基准结果一致。

## 六、交付方式

请分两步完成。

**第一步：代码审查与实施计划**

输出：

- 现有能力清单。
- 需要新增和修改的文件。
- 现有 Schema 的兼容性问题。
- 数据存储和版本管理风险。
- 实施顺序。

**第二步：开发与测试**

实施完成后提供：

- 实际修改的文件。
- 核心接口说明。
- 自动化测试结果。
- 一次真实文件执行的 ExecutionResult 示例。
- 尚未解决的问题。

不要仅以“测试通过”作为交付说明，需要展示真实执行链路的验证结果。
