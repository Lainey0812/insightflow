# REQ-0059 Lifecycle 状态流转表

评审日期：2026-10-30。本文基于当前真实源码重新核对，不覆盖上一轮设计。需求档案 REQ-0064，关联 REQ-0063/REQ-0059。**本轮仅文档评审；所有“建议”尚未实现。** 当前源码与上一轮阶段 0 哈希一致；这不替代对具体函数及契约的逐项检查。

## 一、当前主链路与状态的意义

真实顺序：上传→Session 落库→登记已有 Workflow Root→后台 Profiler→Intent→Planner（含 Validator）→保存计划时再次 Validator→HITL→独立执行请求→Engine→报告 enqueue→后台 Report。报告内部是输入校验→Evidence→Chart→Insight→Fact→Assembler→Persistence。不是每次都会执行完整链路。

以下进入条件以 real_v1 主链路为范围。服务还可被独立画像、Intent/Plan、导入报告 API 调用；这些调用不必有 Session/Root，不因此伪造其关联。

依据：[create_router.create_session、clarify_intent、retry_preparation、approve_plan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/routes.py:48)，[WorkflowOrchestrator._prepare_real](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:224)，[create_execution_router.execute](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:19)，[AnalysisReportService.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:39)。

“正常退出”在下表指实际调用成功返回，**不等于**用户目标完成、任务全可执行、用户已批准或报告已保存。Node.run 把 AppError/Exception 转为 NodeOutput.error；observed_node 内 real_output/record 再抛 NodeFailure，已有 Trace 才能正确记录节点错误。后续真实来源防护、Session 保存等仍可能在节点 Span 之外失败，不能因 Root failed 反写已完成 Span。

依据：[Node.run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/nodes/base.py:20)，[WorkflowOrchestrator.observed_node/record/real_output](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:48)。

## 二、12 个节点逐项核对

### N01 Data Profiler — `data_profiler`

- **真实入口**：[DataProfilerNode.process](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/nodes/data_profiler.py:25) 经 to_thread 调用 [DataProfilerService.profile](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/data_profiler.py:15)。
- **进入条件/输入**：real_v1 准备处于 PROFILING；ProfileInput 包含已保存 FileInfo 和 ProfileOptions。读取的是 FileStore 内容，不接受随意本地路径。
- **正常退出/业务结果**：解析、画像校验、DatasetRepository.save 完成，返回真实 DatasetProfile；质量问题可随正常结果返回。随后保存 Session.profile/dataset_ref 并进入 PARSING_INTENT。
- **异常分支**：读文件、格式/表头/结构、画像或保存异常经 NodeOutput.error 导致准备失败；不是 Mock 回退。
- **重试/恢复**：不在节点内自动重试；begin_real_retry 在没有已保存 dataset_ref 时回到 PROFILING。有画像检查点则不重跑画像。
- **Trace 位置**：已有 `_prepare_real → observed_node('data_profiler')`，记录真实开始、结束、行列数/版本；独立画像 API 不能据此宣称也已关联 Root。依据：[准备边界](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:237)、[检查点选择](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:328)。

### N02 Intent Parser — `intent_parser`

- **真实入口**：[IntentParserNode.process](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/nodes/intent_parser.py:24)→[IntentParserService.parse](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/intent_parser.py:69)。
- **进入条件/输入**：PARSING_INTENT；真实画像、原 user_query、已保存 clarification_answers。
- **正常退出/业务结果**：IntentArtifact 通过结构及确定性规则；proceed 进入 PLANNING；clarify 保存意图/问题并进入 WAITING_FOR_CLARIFICATION。空输入可走 input_guard、0 次模型调用，节点依然正常完成。
- **异常分支**：输入/上下文错误、调用/超时、JSON/Schema/语义/grounding 错误；达到限次后失败。clarify 不是错误。
- **重试/恢复**：仅原 RETRYABLE 集合内输出错误有限重试，所有尝试共用总 deadline；LLM_TIMEOUT 不在该集合。用户补充后保留历史、更新答复、清 planner_result，再执行 Intent，不重做 Profiler。
- **Trace 位置**：已有 Root Intent Span、parse_id/operation_id 与实际 CallBinding；内部 Call 重试不重复主 Span；澄清后是新 Span。依据：[parse 的 input_guard/重试](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/intent_parser.py:100)、[_prepare_real 的 clarify 分支](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:247)、[begin_real_clarification](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:317)。

### N03 Analysis Planner — `analysis_planner`（Node 名为 `analysis_planner_v1`）

- **真实入口**：[AnalysisPlannerNode.process](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/nodes/planner_v1.py:24)→[AnalysisPlannerService.plan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_planner.py:48)。
- **进入条件/输入**：意图 proceed、画像/意图数据版本匹配；使用真实 Registry 摘要和结构化输出 Schema。
- **正常退出/业务结果**：模型草案解析并经一次技术 Validator 返回 ValidatedAnalysisPlan。F0/partial/blocked 都可正常返回，不能当作调用失败，也不代表可以审批。
- **异常分支**：输入/版本不一致、超时、Provider、JSON/Schema/长度等错误；Node→准备失败，保存错误及可用检查点。
- **重试/恢复**：原 RETRYABLE 是 PLANNER_INVALID_JSON、PLANNER_SCHEMA_INVALID、PLANNER_OUTPUT_TOO_LARGE、LLM_INVALID_OUTPUT、LLM_INCOMPLETE_OUTPUT；共用总 deadline；**不包括 LLM_TIMEOUT，也不包括 Validator 返回的 F0**。用户重试可从 PLANNING 重新调用，或已有 planner_result 时直接恢复 VALIDATING。
- **Trace 位置**：已有 Root Planner Span；内部 Call 引用同一 Span，新人工执行使用新 Span/operation。Validator 是实际子 Span。依据：[plan 重试与 Validator](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_planner.py:63)、[begin_real_retry](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:328)。

### N04 Plan Validator — `plan_validator`

- **真实入口**：[PlanValidator.validate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/planning/validator.py:18)，不是独立 Agent。
- **进入条件/输入**：各真实调用者传 AnalysisPlan、DatasetProfile、Registry；具体用途见下一节。
- **正常退出/业务结果**：返回逐任务 F0/F1/F2、可执行任务及目标覆盖；步骤参数不合法可返回 F0/INVALID_SCHEMA。
- **异常分支**：计划顶层 Schema/枚举/ID 不合法抛 PLAN_SCHEMA_INVALID；与正常 F0 返回不同。其他实际异常也不能伪装校验完成。
- **重试/恢复**：没有自动模型修复；真实保存、读取审核、修订、批准、执行或报告重验时再次调用；每次调用应独立留痕，不覆盖先前验证。
- **Trace 位置**：当前仅 Planner 的 planner_output、准备上下文内 validate_v1 的 initial_plan_save 已采集。其他 HTTP/Engine/报告用途尚未完整绑定。依据：[Planner](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_planner.py:106)、[PlanReviewService.validate_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:113)。

### N05 HITL — `hitl_approval`（逻辑节点，当前没有此 Span）

- **真实入口**：[PlanReviewService.revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:169)、[approve_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:273)，审核页面还调用 [review_presentation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:213)。
- **进入条件/输入**：Session 及当前服务端 PlanVersion、revision；修订/审批请求须绑定准确 ID/版本。等待本身没有持续计算。
- **正常退出/业务结果**：删除任务→新不可变版本、重新校验、清空当前批准引用、回到 AWAITING_APPROVAL；审批成功→不可变 ReviewApproval/ApprovedExecutionSnapshot 与 Session.APPROVED 在同一业务事务提交。
- **异常分支**：旧 revision/计划/数据版本、未确认条件、阻断不确定性、F0 核心覆盖、警告未确认等拒绝；事务回滚、不生成成功审批。自然语言修订返回未实现。没有单独“用户拒绝计划”的业务 API。
- **重试/恢复**：approval_request_id 相同且参数相同返回原有效审批；冲突/审批已被新版本替代则拒绝。删除是新版本，不是恢复旧版。等待重启保留，批准不自动变成 Engine 已执行。
- **Trace 位置**：当前只有准备结束的 workflow.waiting_approval；修订/接受/拒绝/冲突尚无完整动作事件。建议业务提交后短动作 Events；禁止长期 running 审批 Span。依据：[审核仓储事务](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:28)、[已有等待检查点](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:60)。

### N06 Analysis Engine — `analysis_engine`

- **真实入口**：[AnalysisEngineService.execute](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:94)，由 [执行 API](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:19)调用。
- **进入条件/输入**：ExecutionRequest 四个标识；服务端批准快照、数据/计划/校验版本及不确定性核验。实际顺序是 replay→check_approval→DatasetLoader.load→claim（再 check）→TaskRunner→save_task→finish。
- **正常退出/业务结果**：ExecutionResultV1 保存；success、partial_success、failed 分别依任务结果计算。failed 也可能正常返回标准结果，不等于 Python 抛异常；空表任务允许成功。
- **异常分支**：前置拒绝时可能根本没有 execution_id；任务异常由 Runner 隔离；claim 后编排/保存异常可能留下 running 业务记录，待启动恢复。不能把它与 F0 跳过或请求重放混为一谈。
- **重试/恢复**：原 request_id 全局幂等，已有完成结果直接重放、running 返回 in_progress；不自动重跑任务。recover_interrupted 保留已保存任务，未保存任务标 skipped/EXECUTION_INTERRUPTED，再结算 success/partial_success/failed。
- **Trace 位置**：当前无 Engine Span；有真实 Task/Step 日志。建议新 claim 后主 Span，claim 前实际加载/验证为单独诊断；重放没有新计算 Span。依据：[ExecutionRepository.replay/claim](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:26)、[TaskRunner.run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/execution/task_runner.py:87)、[recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:125)。

### N07 Evidence Builder — `evidence_builder`

- **真实入口**：[AnalysisReportService.generate 内 EvidenceBuilder.build](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:54)。
- **进入条件/输入**：ReportGeneration 已 start；批准/执行/画像/计划输入核对通过，读取真实完整结果及统计描述。
- **正常退出/业务结果**：受控 Evidence 集合及追溯引用；可以为空，空证据不是构建异常。
- **异常分支**：构建异常使报告尝试失败；之前报告输入校验失败可能尚未进入 Evidence，不能造其失败 Span。
- **重试/恢复**：不局部自动重试；只能随原 failed 报告的新 attempt 再构建，不重执行 Engine。
- **Trace 位置**：已有 Report Run evidence_builder Span、count 和受控 snapshot；Root 只通过子 Run 关联。依据：[ReportWorkflow.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:28)。

### N08 Chart Builder — `chart_builder`

- **真实入口**：[VisualizationBuilder.build 的实际调用](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:100)，在 Insight 调用之前。
- **进入条件/输入**：execution/descriptions/evidence/tasks/intent 已准备；并非等 LLM 决定图表。
- **正常退出/业务结果**：受控 ChartSpec 列表；空列表或适用的表格回退不自动失败。
- **异常分支**：真实 build 异常进入报告错误处理，不能由最终报告反推曾成功生成图表。
- **重试/恢复**：随允许的新 Report attempt 重建；没有独立图表重试或另一个 LLM。
- **Trace 位置**：**当前缺失**。建议仅紧包既有 build 调用，不移动顺序、不新增 Agent。依据：[VisualizationBuilder.build](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/reporting/visualization.py)。

### N09 Insight Generator — `insight_generator`

- **真实入口**：[AnalysisReportService.generate 的 Provider 调用与 Draft 校验](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:130)。
- **进入条件/输入**：有有效 Evidence；发送受控选择后的证据、范围、动态 Schema，非完整原始数据。
- **正常退出/业务结果**：Provider 返回、InsightDraft 解析成功→候选洞察；不是最终合法洞察。无证据真实分支不调用 LLM。
- **异常分支**：超时/Provider/协议/JSON/Schema/长度错误使报告尝试失败；不生成模板成功结果。
- **重试/恢复**：现有生成函数仅一次 LLM 请求，没有内部修复循环；报告 failed 后由新 attempt 再调，原 Call 保留。
- **Trace 位置**：已有 Report Run Span 和 CallBinding；无证据分支为真实 skipped。Call 协议成功与后续 Fact/业务成功分开。依据：[无证据分支](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:172)、[CompatibleLLMProvider.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/compatible_provider.py:22)。

### N10 Fact Validator — `fact_validator`

- **真实入口**：[materialize_candidates](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/reporting/fact_validation.py:272)，调用位置 [generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:159)。
- **进入条件/输入**：合法 Draft、已选 Evidence、真实结果表和任务映射。
- **正常退出/业务结果**：每个已有证据的 P0 任务均有合法候选；可保留合法部分并返回 rejected 列表，Report 后续 partial；不是“拒绝一条就系统失败”。
- **异常分支**：全部候选被拒绝或某个已有证据的 P0 任务缺合法洞察时，代码会抛错，报告失败；不能将所有拒绝都改成 partial。候选诊断回调异常被隔离。
- **重试/恢复**：不自动让模型改写；随报告允许的新 attempt 重新校验。无证据真实路径为 skipped。
- **Trace 位置**：已有 Fact Span、候选/规则 Events、counts；抛错时 Span failed，即使部分 candidate 已接受。依据：[SpanHandle.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:73)。

### N11 Report Assembler — `report_assembler`

- **真实入口**：[AnalysisReportService.generate 内组装区块](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:177)，没有另一个独立 Agent.run。
- **进入条件/输入**：Evidence、图表、合法洞察、失败任务和限制已知；无证据也会进入以生成 unavailable。
- **正常退出/业务结果**：AnalysisReport 构造成功；report_status=complete/partial/unavailable，goal_coverage=complete/partial/blocked 独立。
- **异常分支**：组装/公开 Schema 校验失败；不能因为模型有响应就说报告成功。
- **重试/恢复**：随 failed Report attempt 重新运行报告，不能只改 summary 掩盖原失败。
- **Trace 位置**：已有 report_assembler Span。**complete 只表示组装完成，不代表 Persistence 已提交**。依据：[ReportWorkflow.generate 保存顺序](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:45)。

### N12 Report Persistence — `report_persistence`

- **真实入口**：[ReportWorkflow.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:52)→[ReportRepository.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65)。
- **进入条件/输入**：本次 attempt 已取得报告；传 report/audit/execution_id/attempt。
- **正常退出/业务结果**：在同事务 INSERT AnalysisReport、更新 ReportGeneration、写 Session 报告投影；generation 为 completed 或 unavailable，不能丢掉 Report 本身的 partial。
- **异常分支**：保存异常会使报告失败，Engine 结果不变；**过期 attempt / 不在活动状态时 finish 当前直接 return，和成功提交一样都返回 None**，现有外围 Span 无法据返回值辨别 no-op，是潜在误报点。
- **重试/恢复**：仅 failed generation + 匹配 expected_attempt 可新建 attempt；旧报告不覆盖。中断生成在启动时改为 failed，可显式重试。
- **Trace 位置**：已有 Persistence Span；建议未来以最小内部提交回执区分 saved/stale，不改业务幂等效果。当前“有 Span complete”不能绝对证明这次调用新增了报告，需查实际 report_id/attempt 落库绑定。

## 三、Validator 不能只放一个“已校验”状态

| 真实调用 | 用途与当前覆盖 | 代码函数 |
|---|---|---|
| Planner 后置校验 | 已有 role=planner_output 子 Span | [AnalysisPlannerService.plan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_planner.py:106) |
| 自动初始计划保存 | 已有初始保存 Span | [WorkflowOrchestrator.save_generated_plan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:292) |
| 人工计划导入 | 通常无 real_v1 Root | [PlanReviewService.save_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:129) |
| 删除任务重验 | 当前缺动作 Context | [revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:183) |
| 审核页面 GET 重验 | 真实计算，不能充当轮询进度 | [review_presentation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:222) |
| 审批前重验 | 不是等同批准成功 | [approve_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:293) |
| Engine precheck 和 claim 内二次检查 | 两次真实调用，不合并记录 | [AnalysisEngineService.check_approval](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:60)、[ExecutionRepository.claim](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:50) |
| 报告输入重验 | Evidence 前，尚无独立 Span | [reporting.contracts.prepare](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/reporting/contracts.py:40) |
| 独立 API | 无 Session 时不造 Root | [create_plan_router.validate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/plans.py:41) |

validate_v1 当前固定标签 initial_plan_save；如果将它原样扩展到所有请求，标签会失真。建议每个调用点显式带 role，review_read 不影响主进度，保持 Validator 算法不变。[validate_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:113)

## 四、八类记录的状态与关联

| 对象 | 当前真实状态/变更 | 持久化与关联 |
|---|---|---|
| Session | CREATED、准备各态、WAITING_FOR_CLARIFICATION、AWAITING_APPROVAL、APPROVED、RUNNING、COMPLETED、FAILED；无 INTERRUPTED/partial 枚举 | sessions.state；revision/workflow_events；current_plan_version、engine_approval、engine_execution_ids、report_generations。**COMPLETED 是 Engine 层结束，不保证报告成功**。[SessionStatus/SessionState](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/enums.py:4)、[ExecutionRepository.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:86) |
| PlanVersion | 没有独立 status；change_type=created/tasks_deleted；内含技术校验结果 | plan_versions(session_id,plan_version) 不可变；不是 Session.plans 的旧 Mock Plan。[PlanVersion](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/plan_review.py:11)、[PlanReviewRepository](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:7) |
| Approval | ReviewApproval.approval_status 只支持 approved；ApprovedExecutionSnapshot 支持 approved/revoked，但当前删除任务是清当前引用而非改旧行 | plan_approvals 的唯一 request_id + 不可变快照/约束审计；拒绝无成功行；旧批准保留。[approve_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:273)、[revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:188) |
| ExecutionResult | execution_status=success/partial_success/failed；Task=success/failed/skipped；仓储 status 另为 running/finished | executions 保存 request/approval/progress/result；execution_results 完整表单独保存；以 plan/dataset/approval 版本绑定。[ExecutionResultV1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/execution.py:145)、[ExecutionRepository](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:12) |
| ReportGeneration | queued→generating→completed/failed/unavailable；failed 可显式新 attempt；completed/unavailable 不再新建 | report_generations 以 execution_id 为键，**只保留该执行最新 attempt**；Session 为其投影，没有独立 generation_id。[ReportRepository.queue/start/finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:35) |
| TraceRun | workflow 与 report_generation 共用枚举，但仓储转移规则不同；Report Run 终态不可重开 | 原 trace_runs；Root 唯一 Session，自指 workflow_run_id，execution_id=null；报告 Run 按 execution_id+attempt 唯一并关联 Root。[TraceRun](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:20)、[TraceRepository.update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60) |
| TraceSpan | running→complete/partial/failed/skipped/interrupted；终态不可覆盖 | trace_spans；parent 只能同 Run；node_attempt 当前按 node_key 分配；不是 NodeInput.run_id。[TraceRepository.reserve_workflow_span/save_span](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:81) |
| LLMCallRecord | running→succeeded/failed/cancelled/interrupted；succeeded 明确只代表 provider_protocol | Registry；operation_id/call_sequence/retry_of_call_id、真实 request/template snapshot、可空 run_id/span_id；原始响应通常只有 hash。[LLMCallRecord](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/prompt_registry.py:39)、[CallRecorder.begin/finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/capture.py:21) |

## 五、六类重点恢复路径

| 场景 | 当前真实流转/历史保留 | 评审结论与依据 |
|---|---|---|
| Planner 失败后人工重试 | PLANNING→FAILED；满足 real_v1/retryable/未保存审核计划/未执行后，按检查点回 VALIDATING、PLANNING、PARSING_INTENT 或 PROFILING；Root 复用，失败 Span 保留 | “重试”不一定再调用 Planner；内部 timeout 也不会自动产生第二次 Call。若曾落 planner_result 但保存失败，可只重验保存。[fail_real/begin_real_retry](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:205)、[start_preparation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:47) |
| Intent 澄清恢复 | clarify 正常结果→WAITING_FOR_CLARIFICATION；补充保存后回 PARSING_INTENT；旧意图/答复保留，新 Intent Span | 未调用 Planner 的阶段不得造其成功/失败；HITL/Engine 不因此自动执行。[begin_real_clarification](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:317) |
| HITL 修订 | 原版本→tasks_deleted 新版本→重新 Validator→AWAITING_APPROVAL；approved_plan_version/engine_approval 清空，旧审计不删 | 新计划未执行，旧报告不能使其生命周期成功；冲突不改变原业务状态。[revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:169)、[transaction](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:28) |
| Engine 部分成功 | 至少一任务 success 且非全部 success→partial_success；仓储 finished、Session.COMPLETED、review_status=completed | 不能按 Session/record finished 显示全部成功；失败/跳过与完整结果保留，图表只用成功任务。[outcome](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:81)、[ExecutionResultV1.outcome](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/execution.py:165) |
| Report 重试 | failed + 匹配 expected_attempt→新 queued attempt→start/generate；同 Root、新 Report Run，旧 Run/Span/Call 保留；最新 generation 行替换 | partial 报告对应 completed generation，**现有 API 不允许“部分成功再优化一次”**。Engine replay 后的 API 适配层仍可 enqueue 原结果报告，不能为此造第二次计算。[queue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:35)、[TraceRecorder.queue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:214)、[execute API](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:22) |
| 进程中断恢复 | 启动按 Engine→准备→Report→Trace→Call 顺序；不是后台自动续跑 | Engine 保留 progress，其余 skipped；准备失败并等待人工检查点重试；Report 改 failed 等重试；Trace 活动态 interrupted、recovered_at；Call interrupted。[main.lifespan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/main.py:77)、[Engine.recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:125)、[TraceRepository.recover](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:173)、[Registry.recover](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/prompt_registry.py:121) |

中断时间特别说明：Trace 恢复不补未知的 finished_at/duration；ReportGeneration/Call 当前会把恢复发现时刻写为 finished_at，Engine 可能记录含停机时间的墙钟耗时。它们不能直接拿来做实测计算时长。没有心跳时，运行时间长也不能据此自动判进程已死。依据：[ReportRepository.recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:97)、[Engine.recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:135)、[TraceRepository.recover](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:173)。

捕获到 CancelledError 等 BaseException 与普通业务失败也不同：prepare_real/report.generate 会标 Trace interrupted 后重抛，Session 或 ReportGeneration 可能暂时仍是活动态，之后才由原启动恢复结算。不能宣称捕获取消当刻业务数据库已经同步 FAILED。依据：[WorkflowOrchestrator.prepare_real](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:212)、[ReportWorkflow.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:72)。

## 六、持久态、建议新增与 UI 派生态

| 分类 | 内容 | 约束/证据 |
|---|---|---|
| 已持久化 | Session 状态/revision/意图历史、版本/审批、Execution/Task/Step、最新 ReportGeneration、AnalysisReport、Run/Span/Event、Call/请求快照 | 使用上节仓储；不要建立第二份事实 |
| 需新增采集、复用旧表 | HITL 动作/等待结束、Engine 主边界、完整 Validator 用途、Chart/input-precheck 等实际 Span/Event | 现有调用点可包边界，无需新 Agent；参 N04–N12 |
| 完整历史需要新增持久化 | ReportGeneration per-attempt 业务历史；当前最新表和 fail-open Trace 不能保证它 | 仅建议原 ReportRepository 增量历史，未实施；见评审报告 |
| 可以先只读计算 | Workflow 语义状态、当前分支、目标/报告/执行的联合结果、采集完整性 | 当前仅 preparation checkpoint，需纯查询聚合，不能调用 review_presentation 重做校验。[checkpoint](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:60)、[review_presentation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:213) |
| 仅 UI/read-model 派生 | pending、分组颜色、logical node 当前显示、等待时长、not_collected/unknown、stale | 不创建 pending Span，不由最终报告反推上游；既有 Span/Run 模型没有 pending。[TraceSpan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:50) |
| 仅内存 | ContextVar、active Span/perf_counter、BackgroundTasks、collector_degraded/workflow_gaps | 重启不保证保留；不能当持久调度器/完整故障历史。[bind_trace](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/context.py:14)、[TraceRecorder](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:156) |

评审意见：现有节点职责与大多数业务状态可复用；不能直接把 Session、Provider Call、Span 和 Workflow 的 success 合并。完整生命周期的最小契约及兼容结论详见 [Trace 数据契约评审报告](Trace-数据契约评审报告.md)。本轮到此只读，不新增埋点。
