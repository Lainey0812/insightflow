# Node Instrumentation Matrix

关联REQ-0082；目标契约Lifecycle Observability V1.0，继承Lifecycle V1.2。

## 口径

“当前覆盖”是相对于统一Workflow级契约的成熟度：**已实现**要求真实入口/结束、分支关联、事件/重试和恢复语义均可由源码证明；**部分实现**表示已有局部Span/Call但不具备统一契约；**未实现**表示真实业务功能存在，但没有独立节点Span。它不是业务功能完成度或生产可用率。

本次为静态源码审计，不查询运行数据库、不生成新的真实Trace；“目标”列是将来要求，不是当前采集字段。

## 全节点概览

| node_key | 逻辑节点 | 当前覆盖 | 源码证据 |
|---|---|---|---|
| data_profiler | Data Profiler | 部分实现 | S39、S32、S34 |
| intent_parser | Intent Parser | 部分实现 | S40、S32、S36 |
| analysis_planner | Analysis Planner | 部分实现 | S41、S32 |
| plan_validator | Plan Validator | 部分实现 | S42、S41 |
| hitl | HITL | 未实现 | S43、S44 |
| analysis_engine | Analysis Engine | 未实现 | S45、S46、S56、S47 |
| evidence_builder | Evidence Builder | 部分实现 | S49、S48 |
| chart_builder | Chart Builder | 未实现 | S50、S48 |
| insight_generator | Insight Generator | 部分实现 | S48、S59、S61 |
| fact_validator | Fact Validator | 部分实现 | S51、S48 |
| report_assembler | Report Assembler | 部分实现 | S48 |
| report_persistence | Report Persistence | 部分实现 | S53、S54、S67、S68、S69 |

当前对统一契约无完全实现节点：9个部分、3个未实现。已有准备Trace和报告子节点仍可用，不能将此结论理解为系统没有任何Trace。

## Data Profiler — `data_profiler`

**当前：部分实现。** 源码：[S39、S32、S34](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=data_profiler；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 已授权文件与解析选项固定，真实调用profile/build_profile；尚未取得Dataset版本时不填假版本。 |
| 目标 | 正常结束 | 确定性画像保存并被当前作业检查点接纳；记录真实DatasetRef和摘要，不仅凭NodeRun成功。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、input_file_id、input_hash、profile_options_hash、dataset_id@完成后、dataset_version@完成后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、workflow.callback.rejected |
| 目标 | LLMCallRecord职责 | 无LLM调用，不生成CallRecord。 |
| 目标 | 重试/重复/旧回调/恢复 | 合法准备Retry同Root新Span；旧revision/key拒绝；从已持久画像恢复时只发恢复/复用事件，不造新计算Span。 |
| 现有 | 实施缺口 | 已有准备Span/真实行列数；business_workflow绑定、提交后结束与平铺上下文尚未统一。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 实际DatasetProfile引用、content hash、解析选项hash、row/column count和检查点引用；数据质量告警仍complete。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 解析/结构/存储错误或画像未通过当前作业接纳；保留代码，区分数据业务问题与技术失败。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Intent Parser — `intent_parser`

**当前：部分实现。** 源码：[S40、S32、S36](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=intent_parser；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 固定DatasetProfile、原目标及澄清答案集，真实进入parse；input_guard返回也算实际节点执行。 |
| 目标 | 正常结束 | 合法IntentResult和parse_id已被当前作业保存；clarify与proceed均是节点正常结束，后者要求真实LLM来源。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、dataset_id、dataset_version、profile_hash、goal_hash、answers_hash、parse_id@生成后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、workflow.clarification.required、workflow.clarification.received、workflow.callback.rejected、llm.started、llm.returned |
| 目标 | LLMCallRecord职责 | 真实HTTP请求每次独立CallRecord；空输入guard没有HTTP，不造CallRecord；Call成功不等于Intent合法。 |
| 目标 | 重试/重复/旧回调/恢复 | 内部LLM重试保留同节点Span/operation，新增Call/sequence；用户回答或显式准备Retry是真重入，新Span/node_attempt。 |
| 现有 | 实施缺口 | 已有Span与Call绑定；事件未系统覆盖澄清保存边界；Root仍按Session解析。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 已保存IntentResult.next_action及输入摘要；clarify对应等待输入事件，不是Span等待状态。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 模型调用/JSON/Schema/语义校验失败，或当前回调被拒绝。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Analysis Planner — `analysis_planner`

**当前：部分实现。** 源码：[S41、S32](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=analysis_planner；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | Intent.proceed、画像/能力版本和输入hash固定，真实进入plan；clarify时根本不启动。 |
| 目标 | 正常结束 | 真实候选与来源被当前作业接纳；Plan Validator结果另有独立节点，规划完成不代表批准或执行。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、dataset_id、dataset_version、intent_ref、intent_hash、capability_version、candidate_ref@产生后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、workflow.callback.rejected、llm.started、llm.returned |
| 目标 | LLMCallRecord职责 | 有限HTTP重试同Span新Call；能力描述/Schema精确请求由Registry追溯，不在Trace记录全量输入。 |
| 目标 | 重试/重复/旧回调/恢复 | 同目标显式Retry新Span；C16检查点复用无LLM时不补模型请求；旧Intent/能力/令牌回调拒绝。 |
| 现有 | 实施缺口 | 已有Span/Call；内部Validator仍会嵌套，候选检查点和Span终态边界未统一。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 候选hash、operation/parse_id、业务问题和校验引用；P0/F0或partial覆盖是规划业务结果，不自动把Span变partial。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | HTTP/JSON/Schema/规划协议失败或旧回调未被接纳。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Plan Validator — `plan_validator`

**当前：部分实现。** 源码：[S42、S41](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=plan_validator；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 真实进入确定性validate；每次校验声明validation_role与候选/版本引用。 |
| 目标 | 正常结束 | 完整校验结果产生并在相应业务操作中被接纳；初次保存/修订/批准需关联持久PlanVersion或批准审计。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、dataset_id、dataset_version、candidate_hash、validation_role、validation_version@返回后、plan_version_id@已保存时 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、workflow.approval.required、workflow.callback.rejected |
| 目标 | LLMCallRecord职责 | 无LLM。Planner内部校验仍是本节点，不另建Agent或子Span。 |
| 目标 | 重试/重复/旧回调/恢复 | 真实重复校验均新Span/node_attempt；role区分planner_output/initial_plan_save/plan_revision/approval_check/pre_execution。 |
| 现有 | 实施缺口 | Planner内部和初次保存已有Span，可能嵌套；HITL新HTTP上下文及Engine直接校验尚无统一Span。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | F0/F1/F2、coverage、blocked/executable IDs、unmet requirements和validation_version；blocked仍可complete。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 输入Schema无效、校验器异常或结果无法与当前候选对应；不是把F0当技术异常。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## HITL — `hitl`

**当前：未实现。** 源码：[S43、S44](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=hitl；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 已验证归属的实际审核命令进入服务器操作；长时间等用户不创建running Span；未接纳的外部请求不造Span。 |
| 目标 | 正常结束 | 新PlanVersion/Approval及审计事务已提交，或真实资格判定明确拒绝且无业务写入。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、plan_version_id、plan_id、plan_version、validation_version、dataset_id、dataset_version、command_request_id、approval_id@批准提交后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、workflow.approval.required、workflow.approval.accepted、workflow.approval.denied、workflow.plan.revised、workflow.command.replayed |
| 目标 | LLMCallRecord职责 | 无LLM，自然语言修改仍未接入，不新增AI修订Call。 |
| 目标 | 重试/重复/旧回调/恢复 | 合法修订/批准各是新调用；重复批准只读重放不新Span；旧版本/已执行native计划不得重获许可；等待审核跨重启仍是等待。 |
| 现有 | 实施缺口 | 真实PlanVersion/Approval存在，但没有真实HITL命令Trace Span或审批事件；业务记录不能当作已采集Span。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 批准/修订持久引用或明确拒绝结果；denied是完成了资格判断，业务outcome=denied。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 技术存储/事务错误；用户不批准、约束未验证不伪装技术失败。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Analysis Engine — `analysis_engine`

**当前：未实现。** 源码：[S45、S46、S56、S47](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=analysis_engine；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 新的执行请求已通过归属与批准检查且真实进入数据加载/执行；幂等重放不新Span；execution_id可在claim后补关联。 |
| 目标 | 正常结束 | ExecutionResult与完整任务结果持久化完成；记录真实execution_outcome，不能以Session.COMPLETED推整流程成功。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、dataset_id、dataset_version、plan_version_id、validation_version、approval_id、execution_request_id、execution_id@claim后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、execution.claimed、execution.task.completed、execution.task.failed、execution.task.skipped、execution.completed、workflow.command.replayed |
| 目标 | LLMCallRecord职责 | 无LLM；每个task/step只用Event或ExecutionResult日志，不创建第三层Span。 |
| 目标 | 重试/重复/旧回调/恢复 | 同execution_request_id不重算；Recover保留progress，未完成skipped，不实现任务/step Resume；新作业必须合法授权。 |
| 现有 | 实施缺口 | 已有真实claim、任务日志与结果，但没有Engine Trace Span/Event，也没有新Workflow身份传播。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 所有计划任务success，ExecutionResult.success已提交；空表有真实结果引用也可成功。 |
| 目标 | partial | 真实ExecutionResult.partial_success：至少一个成功且另有failed/skipped；原任务状态及错误保留。 |
| 目标 | failed | 无成功任务或执行技术异常；以任务错误区分business/technical；不抹去已有成功任务。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Evidence Builder — `evidence_builder`

**当前：部分实现。** 源码：[S49、S48](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=evidence_builder；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 报告作业绑定真实ExecutionResult，实际进入build；不从Planner预期计算。 |
| 目标 | 正常结束 | 结构化Evidence产生并绑定任务/结果/统计范围，输出摘要可追溯；0条合法结果也是真实完成。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、plan_version_id、approval_id、dataset_id、dataset_version、report_attempt、evidence_ids@返回后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished |
| 目标 | LLMCallRecord职责 | 无LLM。受控证据snapshot是观测副本，写失败不能改变业务。 |
| 目标 | 重试/重复/旧回调/恢复 | 报告Retry实际重跑时新Span；旧attempt输出不得被新报告采用；未保存的历史证据不靠当前数据重建假快照。 |
| 现有 | 实施缺口 | 已有Report Run内Span及证据投影；尚未直接挂Business Workflow Root或携带完整分支。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | Evidence IDs与output hash、source task/result、分母/范围引用；evidence_count=0仍complete/no_evidence。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 输入引用或统计口径冲突、确定性计算错误；不造总体分母。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Chart Builder — `chart_builder`

**当前：未实现。** 源码：[S50、S48](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=chart_builder；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 真实调用VisualizationBuilder.build；不能因最终报告有图表反推节点已执行/采集。 |
| 目标 | 正常结束 | 受控ChartSpec列表返回，维度/指标/result_ref已核对；回退table或空列表可以complete。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、plan_version_id、report_attempt、data_ref、chart_ids@返回后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished |
| 目标 | LLMCallRecord职责 | 无LLM；不允许任意ECharts JavaScript。 |
| 目标 | 重试/重复/旧回调/恢复 | 报告真实Retry可重入；前端图表切换不启动新分析或伪造后端Span。 |
| 现有 | 实施缺口 | 实际规则构建存在，generate中直接调用，尚无chart_builder Span。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 真实ChartSpec IDs/count、类型、data_ref和output hash；不宣称图表业务已交付。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 字段映射/图表构建技术错误，保留执行结果；不自动发模型。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Insight Generator — `insight_generator`

**当前：部分实现。** 源码：[S48、S59、S61](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=insight_generator；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 已绑定报告作业真实进入LLM请求或明确NO_EVIDENCE skip分支；不能把排队当HTTP发出。 |
| 目标 | 正常结束 | 完整返回且候选Schema合法，或明确完成no-evidence skip；事实安全与最终保存由后续节点负责。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、report_attempt、evidence_refs、operation_id、template_snapshot_id@调用前、call_id@日志登记后、request_snapshot_id@登记后 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、span.skipped、llm.started、llm.returned |
| 目标 | LLMCallRecord职责 | 每个真实HTTP请求尝试一个CallRecord；当前此节点单次请求，Report Retry新节点/new operation；不新增LLM节点。 |
| 目标 | 重试/重复/旧回调/恢复 | ReportRetry新Span；Registry请求日志fail-closed；取消/中断保留Call记录，不复用旧HTTP响应当新调用。 |
| 现有 | 实施缺口 | 已有Report Span/Call/候选计数与NO_EVIDENCE skip；实际operation_id未统一写Span，早期llm.started只代表意图调用。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 实际候选数量/hash、Call/Schema/模板引用；Call.succeeded本身不足，候选Schema也要合法。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | HTTP/超时、Registry或输出Schema异常；不能模板冒充模型成功。 |
| 目标 | skipped | 处理器真实进入NO_EVIDENCE分支，skip_reason=NO_EVIDENCE；不创建HTTP Call。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Fact Validator — `fact_validator`

**当前：部分实现。** 源码：[S51、S48](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=fact_validator；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 候选Schema合法且有Evidence时真实校验，或处理器真实进入NO_EVIDENCE skip。 |
| 目标 | 正常结束 | 合法/拒绝候选与规则结果完整产生；无合法核心洞察应业务拒绝，不生成完整成功报告。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、report_attempt、evidence_refs、candidate_count、accepted_count、rejected_count、rule_ids |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、span.skipped、insight.candidate.validated、insight.candidates.summarized |
| 目标 | LLMCallRecord职责 | 无新LLM调用。模型解释不由另一个Agent反思；引用与数值来自受控证据。 |
| 目标 | 重试/重复/旧回调/恢复 | 实际ReportRetry才新Span；不同指标/范围不可混引；观测callback异常不能改变校验结果。 |
| 现有 | 实施缺口 | 已有计数与candidate.validated/candidates.summarized事件，rule IDs受限；平铺关联/显式业务失败分类尚未统一。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 全部合法候选、引用和rule summary；没有拒绝不等于解释性陈述已严格验证。 |
| 目标 | partial | 保留合法候选且有明确拒绝；核心覆盖允许部分交付并保留局限；candidate/accepted/rejected计数一致。 |
| 目标 | failed | 全部候选不合法或已有证据的核心方向缺合法洞察；区分业务安全拒绝和技术异常。 |
| 目标 | skipped | 真实NO_EVIDENCE skip，不能因为另一个节点失败而补造本节点skip。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Report Assembler — `report_assembler`

**当前：部分实现。** 源码：[S48](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=report_assembler；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 真实组装报告：已经有阶段输出及覆盖/限制判定；即便无证据也可组装unavailable说明。 |
| 目标 | 正常结束 | 合法AnalysisReport候选返回；此时没有交付，不宣称Report已持久化。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、plan_version_id、report_attempt、report_id@分配后、report_status、goal_coverage |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished |
| 目标 | LLMCallRecord职责 | 无LLM；summary/insights来自统一证据流程，不由Presentation另造结论。 |
| 目标 | 重试/重复/旧回调/恢复 | 真实生成unavailable说明时Span complete/business_outcome=unavailable，不标整体成功；报告未提交时不能成为历史交付。 |
| 现有 | 实施缺口 | 已有Report Run内组装Span，但默认SpanHandle没有按report_status=partial映射，当前可能complete。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | 完整候选report_status=complete、目标覆盖及output hash；仍须Persistence才能交付。 |
| 目标 | partial | 真实AnalysisReport.report_status=partial，任务/洞察/局限完整保留。 |
| 目标 | failed | Schema/核心覆盖协议错误或组装异常。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## Report Persistence — `report_persistence`

**当前：部分实现。** 源码：[S53、S54、S67、S68、S69](source-index.md)。

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 稳定身份 | node_key=report_persistence；每次真实重入新span_id/node_attempt，直接Root，无子Span。 |
| 目标 | 真实开始 | 实际进入持久化作业边界，精确候选/当前execution/attempt已固定；C19-A授权、事务、B核验是同一节点内检查点，不额外建Span。 |
| 目标 | 正常结束 | 事务已提交且持久事实证明accepted；C19-B允许后原子写对应running Span.complete与结束事件；观测失败不撤销业务。 |
| 目标 | 必需业务/关联ID | session_id、workflow_id、root_run_id、operation_id、node_key、span_id、node_attempt、business_revision_started、active_key_digest、execution_id、report_attempt、report_id、report_digest、command_request_id、commit_payload_hash、authorized_revision、committed_revision@提交后、authorized_active_key_digest、persistence_span_id@已采集时 |
| 目标 | Span职责 | 一个真实逻辑节点执行范围；事务性节点在业务接纳后结束，纯计算节点以真实输出结束，均不等于整流程成功。 |
| 目标 | Event职责 | span.started、span.finished、report.authorization.allowed、report.authorization.denied、report.commit.accepted、report.commit.rejected、report.commit.reconciled、report.completion.observed、observation.gap_detected |
| 目标 | LLMCallRecord职责 | 无LLM；事务、proof查询和Span完成不引入新Agent/Attempt实体。 |
| 目标 | 重试/重复/旧回调/恢复 | 业务提交后丢回执，先一致读事实；重复A/B只读；旧attempt/key拒绝；已interrupted终态Span不改complete，保留业务交付与gap。 C20已提交仍为unavailable；新native路径不以C19-B伪造完成，未决观测协议作为准入阻断。 |
| 现有 | 实施缺口 | 当前finish accepted保护已有，persistence Span仍按with正常退出自动complete；V1.2 A/B与proof只独立Policy/测试，生产未接入。；C20 unavailable的native观测成功授权不在V1.2 C19-B范围，C2需先专项决议，不得套用。 |

| 标记 | Span状态 | 必须具备的实际证据 |
|---|---|---|
| 目标 | running | 当前合法业务作业真实进入本节点，输入已绑定；Span创建成功不等于业务结果已提交。 |
| 目标 | complete | C19-A许可不够；需Report+Generation.completed+归属+提交元数据一致，B匹配唯一persistence_span_id；report.partial仍可使本Span complete。 |
| 目标 | partial | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | failed | 提交前授权拒绝/已确认回滚/数据库写错误分别记录；不能因丢返回值直接failed；未知提交状态优先interrupted且等待核验。 |
| 目标 | skipped | 不适用；当前业务契约没有该部分/跳过结果。不得为了补齐状态制造此Span终态。 |
| 目标 | interrupted | 确认进程/取消或旧活动令牌使本次节点不能正常完成；保存停止原因。不能靠超时UI计时器推断。 |

## 节点结束的三个边界

**[目标]** 准备节点与HITL/Engine等事务性范围，正常结束需要对应业务检查点/结果被当前作业接纳；当前observed_node结束早于后续Workflow检查点的差距必须披露。纯Reporting计算/校验节点可以在真实阶段输出生成后结束，此时报告还未交付。Report Persistence必须走C19提交证据边界。

**[目标]** “没有被调度”不是skipped。Intent clarify后没有Planner Span；批准blocked时没有Engine Span；Fact Validator抛出核心缺口错误后没有Assembler Span。只有真实进入NO_EVIDENCE处理器才创建Insight/Fact的skipped Span。

**[目标]** HITL等待用Root/业务等待事件表达，不持有一个跨数小时running的假执行Span。每个真实审核命令各自执行；被入口拒绝而未执行业务的请求只可记录受控命令拒绝，不造节点。

**[目标]** 初次校验、Planner内部校验、HITL修订/批准校验、Engine前复核均使用同一稳定plan_validator，validation_role区分；每个实际调用递增node_attempt，不能只保留最后一次。

**[目标]** Engine task/step是该节点的事件和执行结果日志，不新增子Span。C19-A/Transaction/B是Persistence节点内检查点，不新增Agent或Trace层级。
