# Trace 状态归并

REQ-0123。Trace 页面不再把旧的运行状态和节点状态当成并列选项。

页面只显示五类：success 成功、error 错误、running 运行中、skipped 跳过、suspended 暂停。

库里的原始值不改写。筛选 `error` 会同时命中 `failed`、`partial`、`unavailable`。旧的精确值（例如 `status=partial`）仍然可以查到。

对应关系：

- 成功：complete、succeeded
- 错误：failed、partial、unavailable、error
- 运行中：running、queued
- 跳过：skipped
- 暂停：interrupted、waiting_input、waiting_approval、cancelled

业务生命周期、Bad Case、回归和回放结果使用各自的状态，没有并进这五类。

真实节点按现有名称归类：intent_parser、analysis_planner、insight_generator 为 LLM；plan_validator、fact_validator 为 Condition；data_profiler、evidence_builder、report_assembler、report_persistence 为 Tool。当前流程没有 Router 和 RAG 节点，页面不补造。

用户原问题、token 和费用没有采集，这次没有在列表里填 0 或编造摘要。
