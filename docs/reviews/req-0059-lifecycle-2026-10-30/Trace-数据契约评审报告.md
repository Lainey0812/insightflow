# Trace 数据契约评审报告

对象：REQ-0059 InsightFlow Lifecycle V1.0。日期：2026-10-30。需求档案 REQ-0064，关联之前设计 REQ-0063；之前四份设计与旧 REQ-0059 不覆盖。

**评审结论：可复用已有 Root/准备阶段/报告 Trace/Registry；不能直接批准“改共享状态枚举即可覆盖完整 Workflow”的实现。建议保持枚举原值，按 kind 分开仓储转移约束，先增加纯只读生命周期视图。后续埋点、迁移和 UI 都需另行评审后实施。本轮没有任何业务代码/数据库变更。**

逐节点真实入口、进入/退出/结果/异常/重试/恢复/埋点位置详见 [REQ-0059 Lifecycle 状态流转表](REQ-0059-Lifecycle-状态流转表.md)。以下所有“拟议”均不是现有实现。

## 1. 枚举能表达，不等于仓储和消费端已支持

### 1.1 实际三层兼容性

| 层 | 真实代码 | 结论 |
|---|---|---|
| Python TraceRun.status | queued/running/waiting_input/waiting_approval/complete/partial/unavailable/failed/interrupted | 已有 9 值；无需为了语义 created/succeeded/partially_succeeded 新增 3 个存储枚举。[TraceRun](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:20) |
| TraceRepository.update_run 的 workflow 分支 | 只允许 queued/running/waiting_input/waiting_approval/failed/interrupted | **Root 写 complete/partial 被拒绝**；现有分支也不是完整的前后状态矩阵。[update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60) |
| 同函数的 report_generation 分支 | queued→queued/running/interrupted；running→running/complete/partial/failed/unavailable/interrupted；终态直接不更新 | 需原样保留；不能因为 Root 支持 reopen 而让报告失败 Run 被改写成成功。[update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:72) |
| Admin 类型与标签 | RunStatus 只有原报告 7 值；execution_id?:string 没声明 null；statusLabels 无两个等待态 | 不改消费端就把 Root 列入旧 UI，会出现类型/标签/关联问题。[RunStatus/TraceRun](/Users/lainey/Desktop/vibe-coding/insightflow/admin/src/types/traces.ts:1)、[statusLabels](/Users/lainey/Desktop/vibe-coding/insightflow/admin/src/features/traces/presentation.ts:3) |
| Admin API | status 查询已接受等待态，但 kind 默认 report_generation；详情 business_source 查 ReportGeneration | API 能按 kind=workflow 查根，不代表详情具备 Workflow 聚合语义。[create_admin_router.runs/run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/admin.py:100) |

`TraceRun.valid_kind` 目前约束的是报告必须 execution_id、Root 不能有 execution_id 且必须自指；没有为 kind 定义一整套状态转换。不能只改该 model validator 就宣称解决持久化转换。[valid_kind](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:42)

### 1.2 推荐语义映射（新只读视图，不更名旧存储值）

| 目标 Workflow 语义 | 对应原 TraceRun 原值 | 是否可直接作为当前 Root 终态写入 |
|---|---|---|
| created | queued | 已支持 |
| running | running | 已支持，但只覆盖准备检查点 |
| waiting_input | waiting_input | 已支持 |
| waiting_approval | waiting_approval | 已支持 |
| succeeded | complete | 枚举有，Root 仓储当前拒绝 |
| partially_succeeded | partial | 枚举有，Root 仓储当前拒绝 |
| failed | failed | 已支持；后续合法重试会重开 |
| interrupted | interrupted | 已支持；不得与 Session.FAILED/error_code 混同 |

依据：[observability.workflow.start_preparation/checkpoint/interrupt](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:47)、[TraceRepository.update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60)。`unavailable` 保留为报告 Run/内容语义，不能单凭它确定整个 Workflow failed。`rejected` 属动作结果，`pending/unknown/stale` 属视图，不加入共享 Run 枚举。

## 2. 对上一轮设计的复核意见

| 设计点 | 评审意见/最小调整 | 源码依据 |
|---|---|---|
| 一 Session 一 Root | 保留现有实现；不再建新 Root 表或新业务任务 ID | [register_root](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:11)、[workflow_session_unique](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_migrations.py:25) |
| 统一 succeeded 枚举 | 仅视图做别名；旧原值 complete/partial 继续给报告使用 | [TraceRun](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:30) |
| 持久化 lifecycle_checkpoint 为前置要求 | **可推迟**。最小初版先纯查询投影；只有需要事件推进/性能缓存时再加可选字段，避免新增一套可漂移状态 | [Session/报告事务](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:83)、[当前 checkpoint](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:60) |
| Engine 成功但报告失败→部分成功 | 建议采纳，必须同时显式 report_failed/未交付报告，不能只显示黄灯“部分成功”隐藏失败 | [ExecutionRepository.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:86)、[ReportWorkflow.generate 错误处理](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:64) |
| Root 可 reopen | 只允许由原业务接受的重试/修订触发；报告子 Run 仍终态只读；Root 旧结算须追加事件 | [begin_real_retry](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:328)、[revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:169)、[ReportRepository.queue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:35) |
| Engine 主 Span 从服务入口直接开 | 需分清请求与计算。前置 replay/rejection 不产生新计算 Span；claim 前已发生的实际 load/validate 作为诊断，不能重排执行 | [AnalysisEngineService.execute](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:94) |
| Report Persistence complete=保存成功 | 需要内部实际提交回执或事后严格绑定核验；当前 None 也可能 stale no-op | [ReportRepository.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65) |
| 用同一 node_attempt 比所有重试 | 不成立。计数按 node_key 和 Run 分配，父 key 含父 attempt；Report 新 Run 的局部 attempt 不能当全 Workflow 次数 | [SpanHandle.__init__](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:57)、[reserve_workflow_span](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:81) |

## 3. 最小只读 Lifecycle 视图

建议新增一个只读查询 DTO，读取原 Session/审核/执行/报告事实，不复制业务记录，不调用 Validator/LLM/Engine。字段可分三组：

| 视图字段（拟议） | 来源/语义 | 不允许做的事 |
|---|---|---|
| business_lifecycle.status、activity、reason_codes | 按当前已接受分支联合推导；状态为八语义之一，资料不全可 null | 直接 `session.status` 或 `run.status` 赋值 |
| business_lifecycle.source_refs | Session revision、真实 dataset/plan/approval/execution/report attempt/report_id 引用 | 为缺失对象生成假 ID |
| collection.availability/integrity/capture_scope | 已有 Root/Span/Event、采集缺口及版本 | 以 Trace 无记录断定未执行 |
| progress 节点 | 实际 Span/Event/业务记录关联；明确 state_source 与 history_refs | 根据最后报告给所有上游补绿 |
| consistency/stale/source_revision | 同业务库快照、跨库时间、可判定的绑定冲突 | 声称三库是一个原子快照 |

依据：[SessionRepository.mutate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/session_repository.py:33)、[PlanReviewRepository.transaction](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:28)、[ExecutionRepository](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:40)、[ReportRepository._write_generation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:83)、[TraceRepository](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60)。

查询必须先按当前 dataset+plan_id/version+有效审批引用定位分支，再按实际 accepted execution 和该 execution 最新已接受 report attempt 取结果。完成后的修订会产生新计划；旧执行/旧报告是历史，不能用“最近一次成功”的时间戳判新版本完成。依据：[current_guard/revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:158)、[ExecutionRepository.claim/approved_snapshot](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:40)、[ReportWorkflow.generate 使用执行批准快照](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:34)。

有直接保存的 ExecutionResult 而无 Engine Span 时，可以显示真实“计算结果成功/部分成功”，同时显示“节点过程未采集”，不能生成不存在的 span_id、起止时间或把最终报告反推成所有节点均已采集成功。依据：[ExecutionResultV1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/execution.py:145)、[TraceSpan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:50)。

### 聚合决策表（拟议，按当前分支判断）

| 真实事实组合 | 语义状态 | 必须保留的说明/依据 |
|---|---|---|
| 已创建未开始 | created | 不造 Profiler Span；[create_session](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/routes.py:69) |
| 准备实际进行中；执行 running；或最新报告 queued/generating | running | activity 区分阶段；APPROVED 未发执行请求时 activity=approved_not_started，而非 Engine running。[execute API](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:19) |
| Intent clarify 已保存并暂停 | waiting_input | Intent 本身可 complete；[interpreted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/orchestrator.py:255) |
| 当前计划待审核 | waiting_approval | 即使 F0 核心/条件阻断也展示真实阻断，不造系统异常；[review_presentation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:241) |
| Engine success + 最新报告 completed + Report complete + goal_coverage complete，版本均一致 | succeeded | 必须有保存的报告，不以 Assembler Span 替代；[ReportRepository.finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65) |
| Engine partial_success；或 Report partial/目标部分未覆盖，仍有实际成果 | partially_succeeded | 同时呈现原执行状态、报告状态与未满足目标；[AnalysisReportService.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_report.py:65) |
| Engine 有可用结果但最新报告 failed/unavailable | partially_succeeded | 明示报告失败/无证据，保留原错误和原重试资格；[ReportWorkflow.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:64) |
| 准备失败；Engine 全任务失败且无成功成果 | failed | 报告无证据分支正常结束也不能抹去 Engine 失败；[AnalysisEngineService.outcome](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:81) |
| 已有明确中断/恢复错误，尚无后续合法恢复或已验证完整交付 | interrupted | 旧成果可继续显示；恢复动作之后重新聚合，不永久冻结；[恢复入口顺序](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/main.py:77) |
| Engine 完成而报告尚未 enqueue | running + needs_attention | 显示“计算已保存，报告未启动”；原执行 API 重放可能补 enqueue，但查询不得主动调用它。[execute API](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:22) |
| 版本/数据缺失或业务 running 与真实失败观测冲突 | null + unknown/inconsistent | 不判成功，也不虚构业务终态；原 claim 后异常未终结记录可待启动恢复。[execute/recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:94) |

同一分支已接受的新活动工作优先于它的历史失败；已完成的新业务记录优先于漏 finish 的陈旧 Trace。仅缺 Trace 不降低真实业务成功，只改变 collection。中断恢复 Engine 若有 partial 结果，尚未继续时显示 interrupted 与结果可用；其后报告真实恢复完成可聚合为部分成功。这是建议的产品语义，需评审确认，不改原 ExecutionResult。依据：[Engine.recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:125)、[TraceRepository.recover](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:173)。

## 4. 持久化变更：什么确实需要，什么可以不加

| 项目 | 最小方案/数据库影响 | 兼容要求与实际依据 |
|---|---|---|
| Workflow Root | **零新表**；复用原 Session 唯一索引和 nullable execution_id 迁移 | 该迁移已实现，不重复建平行系统。[migrate_workflow_roots](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_migrations.py:4) |
| 初版 lifecycle 查询 | **零业务表/状态枚举变更**；纯 read-model | 不污染 Session、审批、结果或报告。[现有业务记录](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/models.py:137) |
| Root 最终状态推进 | 后续实现时仅扩展 workflow 分支的转移矩阵，保留原 9 值；状态与追加 Event 在同一 Trace 事务更新 | `BEGIN IMMEDIATE`/CAS 与实际 business revision、分支引用守卫；报告分支不放宽。[update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60) |
| Root 缓存 checkpoint | 可选延后；若加则可选 JSON 字段，不必另建工作流事实表 | model extra=forbid，要升级显式模型；旧值保持 null，不填当前配置。[TraceModel/RunManifest](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:5) |
| HITL/Engine/Chart/Validator 采集 | 复用 trace_spans/trace_events，受控属性增加 role/业务引用/动作结果即可 | 扩展 SAFE_KEYS/Schema，不记录完整请求或凭证；实际边界详见状态表。[safe](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:42) |
| 报告 per-attempt 业务历史 | **若要求 Trace 故障下仍完整追溯，则需要原 ReportRepository 内增加历史表**，以 (execution_id,attempt) 唯一；latest 表/原 API 继续保留 | queue/start/finish 同业务事务同步写历史；终态不覆写；更早缺失历史 unavailable。当前 `INSERT OR REPLACE` 确认只保留最新。[ReportRepository._write_generation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:83) |
| Report Persistence 回执 | 只需内部接口明确 committed/stale 的兼容返回，未必需新表 | 外层不得将 stale no-op 标新保存成功；不改原幂等效果。[finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65) |

ReportGeneration 没有独立 generation_id，推荐复合引用，Report TraceRun.run_id 仍是另一个对象；不能为了设计图好看生成假的“已有 ID”。历史表是同一 Repository 的版本历史，不是新调度器或第二份 Workflow；若不加，就必须明确完整业务 attempt 历史不保证，不能用 Trace 的存在替代保证。[ReportGeneration](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/models.py:125)、[TraceRecorder.queue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:214)

本轮不执行任何迁移。将来迁移须备份权限受限存储、事务回滚验证、保留旧 Run/Manifest/Report 原内容，旧 report_generation 行缺字段按旧契约读取，不重算历史哈希。根 Manifest 不可变，不能把 capture_scope=workflow_preparation 静默改为全生命周期。[TraceRepository.update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:65)

## 5. 生命周期与真实尝试的边界

1. **Root**：Session 创建成功后登记，跨请求查原 Root；现有 `start_preparation` 已能在重试时清最近结束信息。建议完整 Root 可在合法动作后重开，但旧结算追加 Event，不改历史 Span。[register_root/start_preparation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/workflow.py:11)
2. **Node Attempt**：每次真正执行独立 Span；node_key+局部 node_attempt、role、真实 parent/Report Run 一起识别，不按数组位置或同名合并。NodeInput.run_id 另有含义，不能直接当 Trace ID。[SpanHandle](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:57)、[NodeInput](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/node_contracts.py:10)
3. **Call Attempt**：同 operation 内 call_sequence/retry_index，retry_of 指向前一次；人工重试新 operation、可无 retry_of_call_id，靠 Span 历史关联。LLM 状态不能直接充当节点状态。[CallRecorder.begin](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/capture.py:21)
4. **Engine**：replay 和 claim 竞态的 loser 不新开计算 Span；先前真正发生的 precheck/load 可以有诊断，不能因未 claim 就抹去真实读取，也不能伪称第二次执行。[AnalysisEngineService.execute](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:94)
5. **Reporting**：保留其自己的 Run；跨 Run 不伪造 parent_span_id，使用 workflow_run_id+execution_id+attempt 归属 Root；子 Run retry 新建，不 reopen 旧失败 Run。[TraceRecorder.queue](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:214)、[save_span 外键归属](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:95)

## 6. 接口最小变更提议

| 接口 | 现状/建议 | 兼容措施 |
|---|---|---|
| GET /admin/runs | 继续默认 report_generation；已有 kind=workflow 可查原 Root | 不把默认结果偷偷改为“全部用户任务”，旧列表/对比保持 |
| GET /admin/workflows/{session_id} | 保留现有 availability/run/observation_gap，增量加入上面的只读 lifecycle/collection | 缺 Root 返回原 not_collected，业务状态可独立展示；不在 GET 创建 Root |
| GET /admin/workflows（拟议） | 从真实 real_v1 Session 关联业务对象和可空 Root，一任务一行 | 分页/过滤/鉴权复用，旧 Mock/导入不得冒充真实任务 |
| Progress（拟议） | 可作为 workflow detail 的受控投影；数据过大时再单独 endpoint | 不为“小功能”同时建两份进度存储；只读聚合已存 Span/引用 |
| 原 spans/events/llm-calls、Prompt 详情 | 保留 | 敏感完整请求走原授权入口，默认只摘要 |
| Report attempt history（若采纳历史表） | 原执行/报告 namespace 的只读历史查询 | 原最新 status API 不变；报告重试 POST 的资格/幂等不变 |

现状依据：[create_admin_router.runs/workflow_root/run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/admin.py:100)、[create_execution_router.report_status/generate_report](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/executions.py:37)。业务请求不增加由客户端提交的 Root 状态、批准标志或本地路径；现有 ExecutionRequest 仍只有四个标识。[ExecutionRequest](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/execution.py:107)

Admin 后续应显式切 Workflow 视图、等待态类型与标签；当前 Trace 页只手动刷新、不传 kind=workflow，不能把“已有 API”说成“已经完整显示”。只开放 Trace/Prompt 的目录限制继续保留。[TracesPage](/Users/lainey/Desktop/vibe-coding/insightflow/admin/src/pages/TracesPage.tsx:24)、[navigationGroups](/Users/lainey/Desktop/vibe-coding/insightflow/admin/src/app/navigation.ts:21)

## 7. 兼容风险与必须保持的边界

| 风险 | 后果与约束 | 证据 |
|---|---|---|
| 改共享状态字面值 | 旧 Report Run/过滤/标签/测试/对比不兼容；本方案不改值 | [TraceRun](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:30)、[Admin RunStatus](/Users/lainey/Desktop/vibe-coding/insightflow/admin/src/types/traces.ts:1) |
| 新计划/旧报告迟到覆盖 | 把旧目标当当前完成；必须校验 branch refs，Root revision 不是跨库原子保证 | [revise_v1](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:169)、[ReportWorkflow.generate](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/workflow/reporting.py:34) |
| 枚举覆盖但转移不受控 | Root 当前只检查目标集合；SELECT/UPDATE 没有专用 CAS；仅修改枚举无效 | [update_run](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:60) |
| 三库提交窗口 | 业务已提交、Trace 未写/旧缓存仍在；返回 stale/incomplete，不做 exactly-once 遥测承诺 | [TraceRecorder.call](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:170)、[业务仓储事务](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65) |
| 源码组合指纹变化 | 埋点也可能触发模板版本冲突；应登记新的组合元版本并对照最终请求，不修改 Prompt 内容或伪造哈希 | [TemplateSource.build/binding](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/templates.py:111) |
| 把所有故障都 fail-open | 原请求快照不可保存时，本来应阻止发送；不能为了监控可用性关闭安全留档 | [CallRecorder.begin/finish](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/capture.py:21) |
| 把恢复时刻当计算完成时刻 | 进程停机时间误计为节点耗时；保留 time_basis/未知值，不改原业务算法数值 | [Engine.recover_interrupted](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/analysis_engine.py:125)、[TraceRepository.recover](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_repository.py:173) |
| 轮询 review GET | 每次都真实重验，可能大量 Span；不能把它当纯读进度 API | [review_presentation](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/services/plan_review.py:213) |
| pending 与未采集混淆 | 伪造执行进度；有缺口时显示 not_collected/unknown，pending 只是有明确当前分支依据的派生 | [TraceSpan](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:50)、[workflow_root](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/api/admin.py:118) |
| 事件限额/内存 gap | Root 跨多次重试达到 256 上限，或重启丢进程内 gap；不能宣称无缺口 | [TraceContext.event/TraceRecorder.workflow_gap](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/observability/recorder.py:98) |
| 终态业务/错误本身不等于语义正确 | 技术 F2 不验证所有筛选字面值；Lifecycle 不修复/掩盖原计划质量 | [PlanValidator.validate/_task](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/planning/validator.py:18) |

## 8. 实施前的条件与停止点

建议批准的仅是设计方向：复用原事实；保留存储枚举值；按 kind 明确转移；当前分支纯聚合；独立采集完整性；Root 合法 reopen、报告 attempt 只追加。

仍需确认的产品/契约选择：

1. “计算可用但报告失败”采用 partially_succeeded，并强制同时展示 report_failed；不是完整报告交付成功。
2. ReportGeneration per-attempt 历史是否列入本轮后续实施；若不列入，接受其可追溯性上限。
3. Persistence stale no-op 的提交回执，以及 Engine claim 前后分开边界作为实施门槛。

后续自动化最少覆盖：旧报告原枚举/Manifest不变、Root complete/partial 和 reopen、并发/旧 revision/旧分支回调、上述六恢复路径、Fact 部分/全拒、合法空结果、跨库缺口、权限与敏感摘要。真实 CSV 验收必须另行运行，不能以既有测试日志或静态审查冒充真实运行。

本轮仅做源码/文档核对和静态引用校验；**没有运行模型、执行迁移、改变配置、修改代码或开发埋点，完成后停止等待评审。**
