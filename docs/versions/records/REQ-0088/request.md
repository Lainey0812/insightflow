# InsightFlow Phase 03-D：Admin Workflow Observability MVP

## 目标

基于 Phase 03-C2 已验证的真实 Workflow Trace，开发 Admin 端 Workflow 运行监控与生命周期时间线。

第一版仅支持只读查询和问题追溯，不提供业务控制操作。

## 实施范围

### 1. Workflow 列表

展示：

- Workflow ID
- Session ID
- 业务生命周期状态
- 开始时间、更新时间
- 总耗时（有可靠数据时）
- Trace 采集完整性
- 失败或异常标记

支持按 Workflow ID、Session ID、状态搜索和分页。

### 2. Workflow 详情

展示 Workflow、Root、PlanVersion、Approval、Execution、Report 的真实关联。

业务状态从 Business DB 获取，不能由 Span 状态反推。

### 3. 生命周期时间线

按真实开始时间展示实际发生的 Node Span。

每个节点显示：

- node_key
- node_attempt
- status
- started_at / ended_at
- duration
- reason_code
- result_ref
- 关联 LLM 调用数量

支持展开查看异常、事件和重试记录。

### 4. Collection Gap

区分：

- 节点未执行
- 节点执行但 Trace 缺失
- 观测结果不完整
- 业务事实存在但关联不一致
- 尚无法判断

不得通过预设节点列表伪造历史执行记录。

### 5. API

优先复用现有 Admin Trace 查询接口。

如果缺少 Workflow 聚合读取能力，新增最小只读 API。

要求：

- Workflow ID 精确查询
- 分页和稳定排序
- 跨 Business DB / Trace DB 关联
- 权限校验
- 敏感数据脱敏
- Trace DB 不可用时业务详情仍可读取

## 验收

使用 Phase 03-C2 已验证的真实 Workflow 作为固定回归样本。

必须能够：

1. 从 Workflow 列表进入详情。
2. 查询对应 Root 和真实 Span。
3. 展示 14 个实际 Span 和 3 条真实 LLM 调用。
4. 展示真实耗时、执行结果、报告引用。
5. 展示异常、重试及采集缺口。
6. Trace 缺失时仍展示正确业务结果。
7. 不修改任何业务状态或 Trace 历史记录。
8. 通过后端、Frontend、Admin 回归测试。

## 严格边界

不修改 Workflow 状态权威，不执行 Switch，不开发业务重试或恢复操作，不新增虚构 Trace，不启动统计 Dashboard。

完成后提供真实页面截图、API 返回示例、测试结果和数据关联证据，等待验收。
