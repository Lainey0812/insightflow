请基于当前 InsightFlow 真实代码，完成 REQ-0059 的 Lifecycle 状态机设计评审。

本轮只读，不修改代码。

1. 逐一核对 Data Profiler、Intent Parser、Analysis Planner、Plan Validator、HITL、Analysis Engine、Evidence Builder、Chart Builder、Insight Generator、Fact Validator、Report Assembler、Report Persistence 的真实执行入口。
2. 为每个节点输出进入条件、正常退出条件、业务结果、异常分支、重试机制、恢复机制和 Trace 埋点位置。
3. 梳理 Session、PlanVersion、Approval、ExecutionResult、ReportGeneration、TraceRun、TraceSpan、LLMCallRecord 的状态与关联。
4. 重点分析 Planner 失败后重试、Intent 澄清恢复、HITL 修订、Engine 部分成功、Report 重试和进程中断恢复。
5. 明确哪些状态已经持久化、哪些需要新增、哪些仅作为 Admin UI 派生状态。
6. 检查现有 TraceRun 状态枚举是否支持目标 Workflow 生命周期；不得直接假设可以新增或修改枚举而不影响现有报告 Trace。
7. 提出最小侵入的状态机与数据契约方案，列出数据库变更、接口变更和兼容风险。

输出《REQ-0059 Lifecycle 状态流转表》和《Trace 数据契约评审报告》，每项结论引用真实代码路径及函数。

完成后停止，等待评审，不进行埋点开发。
