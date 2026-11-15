# InsightFlow Lifecycle V1.0 阶段 0：审计与设计

完整用户任务书原样登记 REQ-0063，关联 REQ-0059；任务书要求的四份文件仍使用 REQ-0059 前缀，旧 REQ-0059 需求和 Trace V0.3.1 交付均未覆盖。

本次只读审计当前代码、现有 SQLite 持久元数据和历史验收材料，输出 lifecycle-audit、lifecycle-state-machine、trace-data-contract、implementation-plan 四份文档。真实现状：Root/准备节点/Call 关联已完成；缺完整 Root 聚合、HITL/Engine 埋点、部分报告节点和 Admin 主链路展示。报告尝试业务记录当前只有最新投影，设计提出原 Repository 内的最小历史扩展，待评审。

设计区分业务生命周期、Trace 采集完整性与 UI 展示；逐节点包含 trigger/input/success/business_outcome/failure/retry/resume/trace_boundary/related_records；明确 Root 合法 reopen、跨版本分支选择、Engine claim 前后和 replay、Report partial/unavailable/failure、Fact 拒绝与系统异常的区别。

只读元数据统计：5 Session、2 Root、10 Span、28 Event、14 Call；当前业务库 0 Approval/Execution/ReportGeneration/AnalysisReport，不宣称本次已完成真实全链路验收。之前真实准备阶段和 90 秒诊断结果作为已有证据，不冒充本轮运行。旧 Session 缺失字段按 null 保留；只读采集首次 KeyError 未改变数据。

校验：248 个源码文件前后哈希一致；四份文档存在；26 个本地链接目标均可访问；未修改业务源码/Prompt/模型参数/UI，未迁移数据库、未重启服务、未调用模型或业务节点。未运行新业务测试，文档区分既有测试证据与后续阶段验收计划。

新增文件仅限本审计目录和正常需求版本档案导航/台账；设计完成后停止，不进入阶段 1。需评审聚合 partial 语义、Root reopen、报告 attempt 历史和 claim 边界方案。
