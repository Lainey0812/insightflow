# REQ-0064 下一阶段：Lifecycle Read Model

基于已完成的两份评审报告，开始 InsightFlow Lifecycle 的第一阶段实施。

本阶段仅实现只读生命周期聚合，不修改现有业务状态机、TraceRun 状态转换、Prompt、模型参数和分析算法。

### 目标

为 Admin 提供一个可信的 Workflow Lifecycle 查询结果，能够根据真实 Session、PlanVersion、Approval、ExecutionResult、ReportGeneration 和 Trace 记录，展示当前分析任务的业务生命周期、执行活动、报告交付状态和 Trace 采集完整性。

### 实施要求

1. 复用现有 Session 唯一 Workflow Root，不新建 Root 表。
2. 实现纯只读 Lifecycle Aggregator，禁止调用会重新校验或修改业务状态的服务。
3. 以当前 Dataset、PlanVersion、有效 Approval 和 Execution 作为分支关联依据，不使用“最近成功时间”推断当前结果。
4. 输出 business_lifecycle、activity、reason_codes、source_refs、collection、consistency 等受控字段。
5. 对 Engine success + Report failed，展示 partially_succeeded，同时明确 report_failed 和 report_not_delivered。
6. 区分业务成功与 Trace 未采集，禁止伪造 Span。
7. 对缺失数据、旧分支回调、跨库不一致，返回 unknown/inconsistent，不推断成功。
8. 保持现有 Admin Runs、Report Trace 和 Prompt Registry API 兼容。
9. 增加针对澄清、HITL、Engine partial_success、报告失败、报告重试、旧版本和 Trace 缺失的测试。
10. 本阶段不新增 ReportGeneration 历史表，不修改 Root 状态转换，不开发 Admin Progress UI。

### 交付物

- Lifecycle Read Model 数据契约
- 聚合服务
- 只读查询 API
- 单元及集成测试
- 兼容性验证报告
- 尚不能可靠推断的状态清单

完成后停止，等待评审，不自动进入下一阶段。
