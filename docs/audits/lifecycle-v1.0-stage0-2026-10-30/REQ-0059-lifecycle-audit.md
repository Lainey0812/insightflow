# InsightFlow Lifecycle V1.0：阶段 0 真实代码审计

审计日期：2026-10-30。任务书标识 REQ-0059；为保留之前同编号需求，本次完整原文另追加归档 **REQ-0063**，关联原 REQ-0059，不覆盖旧版。本文及配套三份文档仅为阶段 0 设计，后续方案均未实施。

## 1. 结论

当前不是“尚无 Root Run”：Trace V0.3.1 已实现一 Session 一 Workflow Root、准备阶段 Span、Intent/Planner 调用关联、澄清及准备重试。缺口是 **Root 仅观察准备阶段，尚未完成 HITL/Engine/Reporting 的生命周期聚合，Admin 仍默认展示报告尝试**。不能再创建第二套 Root 或运行事实表。

最大的状态误读风险：Engine 完成后 Session 可以是 COMPLETED，而报告仍 queued/generating/failed。Session.COMPLETED 不能解释为完整分析任务交付成功。Trace.integrity=observed 也只表示声明范围内的采集情况，不等于全链路完整。

阶段 0 未修改业务代码、Prompt、参数、数据库结构或 UI；未触发审批、执行、模型调用或服务重启。源文件核对及只读元数据见本目录的 source-before.sha256.json、runtime-metadata.json、code-symbols.json。只读查询首次遇到旧 Session 缺少 workflow_kind，按缺失=null 重新采集，没有回填旧数据。

## 2. 实际前台链路与入口

```text
frontend api.create(real_workflow=true)
  → POST /api/v1/sessions
  → FileStore.save → SessionRepository.create
  → WorkflowOrchestrator.trace_created（已有 Root）
  → 发放 Session token → BackgroundTasks.prepare(real_workflow=true)
  → prepare_real → DataProfilerNode.run → IntentParserNode.run
       clarify → 保存意图/问题 → 返回等待
       proceed → AnalysisPlannerNode.run → Planner 内 Validator
               → save_generated_plan → PlanReview.validate_v1 → 保存不可变版本
  → 等待用户审核
  → POST plan-revisions（可选，删除并重新验证）
  → POST approvals → approve_v1 → 保存不可变审批
  → 前端另发 POST /api/v1/executions
  → AnalysisEngineService.execute → ExecutionResult 持久化
  → API enqueue ReportGeneration → BackgroundTasks ReportWorkflow.generate
  → 读取执行/审批快照 → 报告输入校验 → Evidence → Chart → Insight
  → Fact Validator → Report Assembler → ReportRepository.finish
```

审批和执行是两个请求，不是一个不可分割动作；自动化执行只发生在前端明确发起执行后。报告队列在 Engine HTTP 适配层接入；独立直接调用 engine.execute 不会自动生成报告。Engine 结果已落库、HTTP 适配层尚未 enqueue 时存在中断窗口。

代码证据：

- [前台真实请求及审批/执行参数](/Users/lainey/Desktop/vibe-coding/insightflow/frontend/src/api/client.ts:45)
- [Session 创建/Root/BackgroundTasks](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/routes.py:48)
- [真实准备/澄清/检查点重试](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:212)
- [执行与自动报告 enqueue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:19)
- [报告生命周期入口](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:13)

legacy_mock 与 manual_review 仍有独立兼容路径；legacy 的 NodeRun、ExecutionResult、Report 不能当作真实 V1 Engine/Report 记录。独立 /intents/parse、/plans/generate、/plans/validate、导入报告入口没有自然 Session Root，不能凭 dataset_id 伪造归属。

## 3. 业务持久化与事实来源

| 对象/来源 | 实际持久化 | 生命周期和局限 |
|---|---|---|
| SessionState | var/insightflow.sqlite3 / sessions.state | revision、workflow_events、意图/澄清、当前计划/审批引用、执行 ID、报告最新投影；real_v1 的状态变化事件落库。NodeRun 只有结束结果，不是活动节点时钟 |
| DatasetProfile | dataset_profiles(dataset_id,dataset_version) | 真数据画像、文件内容哈希、解析选项和稳定 field_id；不可变版本 |
| PlanVersion | plan_versions(session_id,plan_version) | 创建/删除任务版本只追加，触发器禁止修改删除 |
| ReviewApproval | plan_approvals；plan_constraint_audits | 审批与 Session 在一个业务事务提交；拒绝/冲突目前没有同等持久成功审批记录，不得造一条 approval |
| Execution | executions | record status=running/finished，request_id 全局唯一；批准快照、任务 progress 和最终 ExecutionResult 是事实来源 |
| 完整结果 | execution_results | 与预览分开保存，不能用预览行数推导全部结果 |
| ReportGeneration | report_generations(execution_id) + Session.report_generations | queued/generating/completed/failed/unavailable；同 execution 的最新 attempt 替换旧投影，**不是完整尝试历史表** |
| AnalysisReport | analysis_reports | report_id 对应保存报告；report_status=complete/partial/unavailable 与 goal_coverage=complete/partial/blocked 分开 |
| TraceRun/Span/Event/Snapshot | var/observability/trace.sqlite3 | 已有独立观测 sidecar；fail-open；不是业务授权或计算事实来源 |
| 模板/请求/Call | var/prompt_registry/registry.sqlite3 | 不可变模板/最终请求快照、实际 Call 生命周期、retry 链；请求原文受原权限与保留策略保护 |

持久化依据：[SessionRepository](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/session_repository.py:13)、[审核仓储](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:7)、[执行仓储](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:35)、[报告仓储](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:29)。

仅内存/请求上下文：ContextVar 当前 TraceContext/active Span、perf_counter 计时起点、collector_degraded、最多 256 个 Session 的 workflow_gaps、受限日志计数、BackgroundTasks 队列。它们不构成持久调度队列。SQLite 三库分别提交，不具备跨库原子性。

## 4. Runtime 节点清单与现有 Trace 覆盖

| 稳定逻辑节点 | 真实入口 | 当前覆盖 | 不能误读的业务结果 |
|---|---|---|---|
| data_profiler | prepare_real → DataProfilerNode.run → DataProfilerService.profile | Root Span complete/failed，真实行列数 | 文件质量警告不自动代表失败 |
| intent_parser | prepare_real → IntentParserNode.run → IntentParserService.parse | Root Span + CallRecord；空输入 input_guard 不调用模型 | clarify 是 complete 的业务结果，Root waiting_input |
| analysis_planner | prepare_real → AnalysisPlannerNode.run → AnalysisPlannerService.plan | Root Span + CallRecord；有限结构重试 | Provider succeeded 不代表草案语义/结构成功；F0 不代表模型执行失败 |
| plan_validator | 下节多个调用点 | 仅准备上下文两处有 Span | 返回 F0/blocked 是校验结果，正常调用仍 complete |
| hitl_approval | PlanReviewService.revise_v1/approve_v1 | 有业务记录，暂无动作 Trace；准备末尾仅有 workflow.waiting_approval Event | 等待不是计算；拒绝/冲突不是新的计算失败 |
| analysis_engine | AnalysisEngineService.execute/check_approval/loader/runner | 有真实 ExecutionResult、任务步骤日志；没有 Engine Span | success/partial_success/failed 与仓储 finished 是不同维度 |
| evidence_builder | AnalysisReportService.generate → EvidenceBuilder.build | 已有 Report Run Span/受控证据投影 | 无证据不应调用模型 |
| chart_builder | 同 generate → VisualizationBuilder.build | **真实执行但没有 Span**，在 Insight 之前执行 | 允许表格回退，不伪造图表能力 |
| insight_generator | 同 generate → provider.generate | Report Run Span + 实际 Call，含动态 Schema/Prompt 引用 | 无证据真实分支记录 skipped；当前无内部多轮重试 |
| fact_validator | materialize_candidates | Report Run Span + 候选/规则 Events | 部分候选被拒绝可以 partial；全部拒绝或缺失核心任务会抛错，不能一律 complete |
| report_assembler | generate 中组装 AnalysisReport | Report Run Span | 内容 complete/partial/unavailable 另有目标覆盖，不等于 LLM/Engine 状态 |
| report_persistence | ReportWorkflow.generate → ReportRepository.finish | Report Run Span | 数据实际保存成功后才算完成；异常不得绿灯 |

准备阶段 Span 由 observed_node 包住真实 Node.run 与 real_output，NodeOutput.error 转为 NodeFailure，避免 Node.run 吞异常后误标成功。**不需要修改 Node.run**。见 [观测边界](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:48)。

报告顺序和边界见 [AnalysisReportService.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:39)。目前报告恰有五类主 Span：Evidence、Insight、Fact、Assembler、Persistence；Chart 和报告输入 Validator 缺失。无证据时 Insight/Fact 的 skipped 来源是真实代码分支，不能推广到未观察的历史任务。

## 5. 所有 Plan Validator 调用点

| 调用点/用途 | 当前 Trace | 最小设计要求 |
|---|---|---|
| AnalysisPlannerService.plan 的 self.validator.validate（107） | Planner 子 Span，role=planner_output | 保留 |
| save_generated_plan → review.validate_v1（301） | 独立 Span，role=initial_plan_save | 保留 |
| save_v1 → validate_v1（141） | manual_review 通常没有 Context | 标为 manual_plan_save，不伪造 real_v1 Root |
| revise_v1 → validate_v1（183） | HTTP 没有准备 Context，不采集 | role=plan_revision，关联新计划版本 |
| **review_presentation → validate_v1（222）** | GET 真实校验，当前不采集 | role=review_read，诊断型；不能覆盖主进度，不能靠轮询审阅 API 生成监控数据 |
| approve_v1 → validate_v1（293） | 当前不采集 | role=approval_check；抛业务冲突与校验 F0 区分 |
| Engine.check_approval（60） | execute 前与 claim 事务内均可实际调用 | 分别 engine_precheck / engine_claim，不合并真实次数 |
| reporting.contracts.prepare（40） | 在 Evidence 之前执行，尚无 Span | role=report_input，隶属该 Report Run |
| /plans/validate | 无 Session Context | 独立接口，不强行加入某任务 Root |

目前 validate_v1 固定把 role 写为 initial_plan_save，直接复用到其他 HTTP 请求会产生错误标签，后续应由调用入口明确传递观测用途，不改校验逻辑。源：[PlanReviewService](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:113)、[Engine check_approval](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:20)、[报告输入校验](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/reporting/contracts.py:24)。

## 6. 现有状态、重试与恢复

- Session：CREATED/PROFILING/PARSING_INTENT/PLANNING/VALIDATING → 等待澄清或审核；APPROVED → RUNNING → COMPLETED/FAILED。完成后删除任务允许进入新计划版本审核，故一次 Session 可能有多个执行分支。[transitions](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/transitions.py:5)
- 准备重试：只有 real_v1、FAILED、retryable、未保存审核计划/未执行时允许，依据 profile/intent/planner_result 检查点选恢复位置。澄清后重跑 Intent，Root 不变。
- 内部 LLM 重试：Intent 和 Planner 默认最多 2 次，受同一总超时预算；只对代码 RETRYABLE 错误集合重试，不自动修复 Validator F0；超时不是保证再试一次。当前共享等待已由 REQ-0061 调为 60 秒，不按源码默认 30 秒猜测运行配置。
- HITL：删除生成新不可变版本，清空当前审批引用但不删旧审批；审批的 request_id 幂等，参数不一致/旧版本拒绝。没有独立“用户拒绝计划”业务 API，不应在 Trace 中宣称这个动作已发生。
- Engine：先 replay，再校验/加载，再 claim，claim 内再次校验。重复 request_id 返回原结果或 in_progress/conflict，不再次执行。任务错误由 TaskRunner 隔离；空表允许成功。进程异常后保留已保存任务，其余标 EXECUTION_INTERRUPTED 的 skipped；无自动续跑。
- Reporting：最新 failed attempt 可以 expected_attempt 显式重试；completed/unavailable 当前不产生新 attempt（partial 报告的 generation 也是 completed）。不可为监控开放新重试能力。
- 启动恢复顺序：engine.recover_interrupted → workflow.recover_interrupted → reports.recover_interrupted → traces.recover → CallRecorder 仓储恢复。[main lifespan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/main.py:73)
- 恢复时间不能冒充真实计算结束时间：Engine 恢复的业务 duration 是墙钟估算，可能包含停机；ReportGeneration 和 CallRecord 恢复会写恢复时 finished_at；Trace 活动 Run/Span 写 recovered_at，保持未知 finished_at/duration 空值。设计需标记时间来源，不能直接混用。

## 7. Root/Attempt/Prompt 的当前关联

Root 在 Session 落库后、token 发放与 BackgroundTasks 前登记。原 trace_runs 有 workflow Session 唯一索引、execution_id 可空迁移；Root.workflow_run_id=self。register_root 幂等，Manifest 不可变；prepare_real 的 start/checkpoint/resume 更新 Root。Root 当前仅允许 queued/running/waiting_input/waiting_approval/failed/interrupted，**仓储暂不接受 Root complete/partial**。

当前 Root 更新主要校验目标状态集合与 business_revision，并没有完整的前后转移矩阵/当前分支守卫；读取旧记录后再更新也没有专用的原子比较交换。已有“分配 Span/Event 序号并发测试”不等于完整 Root 聚合并发已验证，需要阶段 1 单独补齐。

人工准备重试新增主节点 Span；内部 Call 的 operation_id/call_sequence/retry_index/retry_of_call_id 保留在同 Span。终态 Span 不可覆盖，Event sequence/Workflow node_attempt 由 SQLite 事务分配。旧 NodeInput.run_id 与 NodeRun.run_id 不是 TraceRun/Span ID；目前二者没有显式绑定字段，不能以名字相似合并。

新 Report Run 的 workflow_run_id 已可引用已有 Root，原 Manifest 保留，旧报告不回填。但是 Root 并不会随其结束聚合状态。ReportGeneration 没有独立 generation_id，当前身份是 **execution_id + attempt**；Report TraceRun 才有独立 run_id。

LLM 模板与最终请求持久化复用原 Registry。Trace 失败 fail-open；**请求快照登记失败现有策略是 fail-closed，不发 HTTP**。两者边界不同，不能为“Trace 不阻断业务”而关闭既有请求安全留档。Root Manifest 是创建时快照，后续重启参数/澄清请求必须从实际 Call RequestSnapshot 查阅，不能修改 Manifest 或用当前配置补旧值。

CallRecord 只有响应哈希，不保证保存完整原始模型输出。Report Trace 有受控 llm_output 投影；其中缺失/截断内容不能宣称可完整还原候选。非流式调用也没有首 token/服务端排队时间，不能从总耗时直接推断模型思考耗时。

## 8. Admin 当前能力与真实数据证据

Admin 只开放 Trace/Prompt（REQ-0062）。Trace 页面调用 /admin/runs 默认 report_generation，不传 kind=workflow；仅手动刷新，无自动轮询/主链路 Progress。Root 查询 API 已存在，不等于 UI 已接入。后台健康接口仍有“报告未连接”的旧文案，与真实执行 API 自动 enqueue 不一致，不可用它判断能力。

本轮只读数据库快照：5 个 Session、2 个 Root、10 个准备 Span、28 条 Event；业务库有 1 个 PlanVersion、**0 审批、0 Execution、0 ReportGeneration、0 AnalysisReport**。1 个旧 Session 的 COMPLETED 不能证明真实 Engine/Report 成功。Registry 6 模板、14 次 Call，6 次关联 Root/Span，8 次无 Root（包含历史/独立诊断）；不反推历史归属。逐项见 runtime-metadata.json；三库快照不是跨库全局事务。

沿用此前真实验收文件：Trace V0.3.1 的两 Session/6 次模型调用证明正常准备、澄清、自然超时与人工重试；90 秒独立重放约 52 秒返回但有错误筛选值。这些是已有证据，不是本轮重跑，也不是全生命周期验收。本轮不触发真实 CSV 工作流；当前库无全链路数据，阶段 1–6 不能据此宣称通过。

## 9. 风险排序与设计入口

1. P0：Session.COMPLETED 掩盖报告失败；Root 仅准备范围，Admin 看不到 Root。
2. P0：跨计划版本/执行/Report Attempt 的迟到回调可能覆盖当前分支；不能只按时间取最新成功。
3. P0：ReportGeneration 旧尝试只留在 fail-open Trace 时不具备可靠业务历史；需最小仓储扩展设计。
4. P1：Validator 各用途未区分；轮询 review GET 会制造大量诊断 Span。
5. P1：持久化边界断电会出现 Engine 已完成但报告未 enqueue；必须标为待生成/可恢复缺口，不能显示报告成功。
6. P1：Trace DB 故障、事件预算 256、进程内 gap 丢失、三库提交窗口、单进程恢复；采集状态必须独立。
7. P1：未确认筛选值语义、原 HITL 阻断、LLM 时延属于既有业务问题，本生命周期改造不修复或掩盖它们。

下一步仅评审：[状态机与节点契约](REQ-0059-lifecycle-state-machine.md)、[Trace 增量契约](REQ-0059-trace-data-contract.md)、[分阶段实施计划](REQ-0059-implementation-plan.md)。
