# planner-node-detail-v1

REQ-0134。只调整 Analysis Planner 的右侧详情。左侧 Workflow 与左右栏布局保持不变。

字段核对：

- 已存在且原先只埋在 Prompt & Model 原文里：请求快照中的 intent、core_requirements、profile 字段、quality_issues、capabilities。响应快照只有 tasks。Session 的 planner_result 含 plan、validation_results、coverage、executable/blocked、unmet_core_requirements、approval_required。LLM 调用已有 Call ID、模板快照、状态、延迟、请求和响应。
- 已存在但历史 span 未写入：plan_id、plan_version、task_count、F0/F1/F2 计数。新的 analysis_planner span 现在写入这些计数。旧 span 不回填。详情在只有一个 analysis_planner span，或 span.plan_id 与已保存计划一致时，附上 session.planner_result。
- 模型草案没有可行性。F0/F1/F2 来自本节点返回里的技术校验，界面标明不是用户审批，也不代替后续计划校验节点。approval_required 固定为需要审批。
- 没有独立的“所需字段”或“分析方法”字段。所需字段取步骤参数里的 field / dimensions / conditions.field。分析方法取 step.operation。价值分级沿用 P0 核心、P1 重要补充、P2 补充。
- 完全缺失，本次不补：独立风险检测器、用户审批结论、后续 plan_validator 节点的结论。不为展示改 PlannerDraft、AnalysisPlan、Prompt 或 Validator。
- 历史调用的 temperature、top_p、max_tokens、token 仍显示未采集。快照过期时不重建。

真实节点 wf_d37a472ad4de4d28b5c2df9646c84914 的分析规划为成功，耗时 12.78 s，span_651404344bf240b49db3052da438755e。默认 Output。4 个任务，P0 两个、P1 一个、P2 一个，可行性均为 F2 / READY。覆盖完整，可执行 4，受阻 0，没有未满足核心需求，没有待确认事项。Input 有分析模式、业务目标、四类空约束、1 条核心需求 C01、10 个字段、0 条质量信号、6 个规划操作。LLM 1 次成功调用，模板版本含 planner-v1.2，请求和响应已保留，没有重试。该历史调用的 token 与三项采样参数为未采集。切换到需求理解后仍是 Input / Output / LLM；计划校验仍是规则节点的 Input / Output。回到分析规划后 span 不变。左右栏约 755px 和 503px。

验证：Admin 类型检查通过；workflows、failure-diagnosis、quality-signals 共 21 项通过。后端 workflow observability 详情测试通过，匹配的分析规划节点带有已保存计划且 approval_required 为 true，其他节点没有这份计划。
