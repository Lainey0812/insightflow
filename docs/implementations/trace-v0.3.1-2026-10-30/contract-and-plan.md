# Trace V0.3.1 契约与实施范围

REQ-0059，仅实施第一阶段。保留 FastAPI、BackgroundTasks、业务状态机、Node.run 返回、既有审批/Engine/Report 规则。

- 新增 TraceRun.kind=workflow；Session 成功创建并发放访问凭证后、提交 BackgroundTasks 前登记 Root。Session 与 Root 在原 trace_runs 表通过唯一索引关联，不建立第二套运行事实。
- workflow Run 的 execution_id 可空；旧 report_generation 仍要求真实 execution_id。Root 初始化为 queued，准备执行 running，澄清等待 waiting_input，计划就绪 waiting_approval；真实失败 failed，异常中断 interrupted。阶段一不把准备完成标为全流程 complete。
- 已失败/中断 Root 可由现有人工重试恢复 running；保留所有终态 Span 和 Event。等待耗时不计入节点耗时。Root 是任务状态投影，不是可删除重建的 HTTP Attempt。
- workflow_run_id：Root 引用自己，新的报告 Run 引用 Session 已存在的 Root；旧报告字段为空，不回填。报告原 Manifest 不修改。只增加关联，不聚合 Engine/Report 状态；其生命周期在后续阶段实现。
- Trace SQLite 兼容迁移将 execution_id 改为 nullable，复制保留旧行及子记录；创建 workflow Session 唯一索引。迁移原事务完成并核对外键；不能给 Root 填虚构执行 ID。
- workflow Event 的 sequence 和 Span 的 node_attempt 在数据库事务内分配，避免不同 HTTP/后台上下文重新从 1 开始或并发冲突。稳定 node_key 保留真实父子关系。
- 准备阶段 Span：data_profiler、intent_parser、analysis_planner，以及分别对应 planner_output 与 initial_plan_save 的 plan_validator。F0 是可行性，不自动 failed；clarify 是正常 Intent 输出。
- ContextVar 仅传递当前观测上下文，按异步任务隔离，不引入调度器。Intent/Planner 的实际调用 binding 读取该上下文；CallRecord 原 operation_id/sequence/retry 链保留。
- 错误文案通过错误代码映射为受控说明，不存原始异常、请求或密钥。Trace 故障受控日志/collector_degraded、Root integrity 标记、未采集状态可查；Root 写入完全不可用时不能承诺其缺口也已持久化。
- 历史 Session 无 Root 返回 not_collected；不在历史恢复时补造旧节点。
- 已有 /admin/runs 默认继续列 report_generation，保证未改造 UI 不误展示 Root；可显式 kind=workflow 查询。增加按 Session 查询 Root 和 Run Event 的只读接口，沿用原权限。本轮不开发 Progress UI。
- 模板源指纹包含服务代码，纯埋点会改变 bundle 哈希；新组合版本登记到原 Registry，System/User 指令、Schema 和模型参数不变。保留原快照，不覆写同版本内容。三节点请求组装做前后对照。
- 单进程恢复保留等待态，将活动 Root/Span 标 interrupted，保存 recovered_at、不伪造 finished_at/耗时；恢复后复用 Root。

测试顺序：迁移与历史兼容 → 生命周期/并发/重试 → 真实服务准备与 Call 关联 → fail-open 和敏感信息 → 原有回归 → 请求组装前后对照 → 本机真实前台 CSV 验证。真实模型仍超时时如实记录，不调参/改 Prompt 求通过；未通过的验收场景明确保留。

预期修改：domain/tracing.py、storage/trace_repository.py 与增量迁移；observability/recorder.py 与 workflow/context 辅助模块；workflow/orchestrator.py、api/routes.py、main.py；Intent/Planner 与 PlanReview 的观测边界；api/admin.py；llm/templates.py 的组合元版本；新增专项测试和交付文档。HITL/Engine/Report 业务实现、所有 Prompt 文本和 UI 保持原样。
