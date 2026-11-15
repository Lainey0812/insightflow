# InsightFlow Lifecycle V1.0：Trace 增量数据契约（待评审）

任务书 REQ-0059 / 本次档案 REQ-0063。**本文件为设计，未执行迁移、未新增 API/表/模型。** 现有契约和缺口见 [审计](REQ-0059-lifecycle-audit.md)，状态推导见 [状态机](REQ-0059-lifecycle-state-machine.md)。

## 1. 复用对象与 ID

```text
Session.id                         唯一用户任务事实
  └─ TraceRun(kind=workflow)        原 trace_runs，Session 唯一索引，已有
       ├─ TraceSpan                每次真实执行独立 span_id
       │    └─ LLMCallRecord       原 Registry，内部调用/重试链
       ├─ TraceEvent               真实生命周期动作/状态检查点
       └─ Report TraceRun          原报告 Run，workflow_run_id 关联（已有）
             ├─ 报告节点 Span
             └─ report_generation_ref=(execution_id, attempt)

原业务库：PlanVersion → ReviewApproval/ApprovedSnapshot → Execution → ReportGeneration → AnalysisReport
```

不创建 WorkflowSession/WorkflowExecution 等第二套业务表。Root.run_id 不等于 NodeInput.run_id、NodeRun.run_id、ExecutionResult.execution_id 或 Report TraceRun.run_id。报告尝试没有现成 generation_id，优先使用真实复合身份 execution_id+attempt；UI 可以格式化成复合键，但不能谎称数据库已有独立 ID。

## 2. 现有 TraceRun 最小扩展

| 字段/约束 | 当前实际 | 提议 |
|---|---|---|
| kind、workflow_run_id | workflow/report_generation、自指或报告关联已存在 | 保留，不重新迁移一套 Root |
| execution_id | Root 为空，报告必须真实 ID | 不给 Root 绑定假执行；当前执行引用放投影中 |
| status | 枚举已有 complete/partial，但 Root 仓储只接受准备状态 | 按评审的转换表允许完整生命周期及合法 reopen；报告 Run 仍保持终态不可重开 |
| business_revision | 已有 Session 检查点版本 | 保留，拒绝更旧版本的当前投影写入 |
| lifecycle_checkpoint（可选新增） | 无 | 最小可重建投影：语义状态、activity/reason、当前业务引用、projection_revision、computed_at、consistency；无原文 |
| started_at/finished_at | 准备首次开始/最近失败点 | Root 表示任务墙钟生命周期；reopen 清最近结算值，旧结算保留在追加 Event |
| duration_ms | Root 暂为空 | 保留为空优先；UI 另算 elapsed/wait/active_time，不能把等待算计算，不强行把重叠子 Span 求和 |
| manifest | 创建时不可变 | 永不改写；新增 Schema 版本可扩展支持，不改旧 JSON/哈希 |
| integrity | observed/incomplete | 保留；全流程 coverage 另算，不把原准备 observed 当全链路完整 |

Checkpoint 为观测缓存，不接受客户端“成功/批准”标志，也不参与 Engine/HITL 授权。内容建议：

- lifecycle_status（查询语义）及 raw_trace_status 映射；明确 current/latest_attempt，不替代历史。
- business_refs：session_id/revision、intent.parse_id、dataset_id/version、plan_id/version、approval_id、execution_id、report_attempt、report_id；尚未发生的引用为 null。
- source_consistency=consistent/unknown/inconsistent；来源读取时刻及未满足条件代码。
- stage_outcomes：Intent.next_action、技术覆盖、Execution.execution_status、ReportGeneration.status、Report.report_status/goal_coverage 的原值，不提前转换成统一“成功”。
- projection_revision：Trace 仓储事务内递增，仅在投影确实改变时；业务源 revision 与投影 revision 分开。

当前 Root Manifest.capture_scope=workflow_preparation 不允许静默改成 full_workflow；创建时能力声明只描述当时，运行升级后的各节点依据真实 Span 的采集版本/用途与可用记录说明覆盖情况。后续模型配置以实际 RequestSnapshot 为准，不能拿 Root 创建时 30 秒/旧模型配置填补后续调用。

## 3. TraceSpan / Attempt

每个真实执行继续生成独立 span_id，status 仍为 running/complete/partial/failed/skipped/interrupted；没有 pending Span。

建议最小可选扩展/受控属性：

| 字段 | 含义 |
|---|---|
| logical_node_id | 稳定逻辑节点，和 UI 11 主节点映射；旧记录缺失则根据真实 name/role 明确标 derived_identity，未知保留 unknown |
| validation_role / execution_scope | planner_output/initial_plan_save/plan_revision/review_read/approval_check/engine_precheck/engine_claim/report_input 等用途 |
| progress_eligible | 诊断读取校验不改变主节点进度；不意味着它未执行 |
| business_refs | 对应真实计划/审批/执行/报告复合引用，不接受任意原始内容 |
| business_outcome | clarify、blocked、partial_success、partially_accepted、replayed、rejected 等原业务结果；不覆盖 Span 执行状态 |
| instrumentation_version / time_basis | 哪版边界采集；observed_elapsed / recovered_unknown / business_recorded 等明确来源 |
| legacy_node_run_id | 准备节点可绑定实际 NodeOutput.run_id；不为 Engine/Report 强造 NodeRun |

继续由数据库事务分配 node_attempt。既有 child node_key 包含父节点 attempt（如 analysis_planner#1/plan_validator），不能改写历史键或以列表顺序重新编号。新写入可按 logical_node_id+role+实际父范围分配；查询保留原 node_attempt，显示父 Attempt，不把跨 Report Run 的第 1 次调用硬编号为同一主节点的“第 1 次总运行”。

调用层级：内部 CallRecord 的 call_sequence/retry_index 只在其 operation_id 内比较；人工重试是新 Span/新 operation_id；Report retry 是新子 Run/attempt，同 Root。旧失败/partial Span 永久只读，不能因后续成功覆盖。

Report 主节点实际落在 Report Run，不把这些 Span 再复制一份到 Root。跨 Run 没有虚构 parent_span_id：保留本 Run 合法父子，通过 workflow_run_id 聚合展示。原比较接口保持报告 Run 范围，完整 Workflow 对比能力不在本轮暗中扩展。

## 4. TraceEvent 与生命周期动作

复用原 trace_events 和唯一 (run_id,sequence)。Root 状态投影与 lifecycle_changed Event 在同一 Trace SQLite 事务内追加/更新；事务失败只影响观测，不回滚业务事务。业务先提交，观测事件只能说明已经接受的动作；不能在业务事务未提交时标 approval.accepted/report.saved。

| 提议事件族 | 真实来源/最小引用 |
|---|---|
| workflow.lifecycle_changed / resumed / reconciled | 业务检查点/只读重建；旧新状态、reason、Session revision、当前分支引用、观测时间；reconciled 不是节点执行事件 |
| workflow.waiting_input / waiting_approval | 真实保存意图/计划后；wait_started，不开长 Span；结束依据真实恢复动作 |
| hitl.plan_revised | revise_v1 事务提交后，新旧 plan_version、移除 task_id（受限列表）、旧审批失效引用 |
| hitl.approval_accepted / rejected / conflict / replayed | 现有 approve_v1 的真实返回/异常分支；成功才有真实 approval_id；replayed 不创造第二份审批 |
| engine.request_replayed / in_progress / rejected | 原 replay/资格/claim 分支，非计算执行；拒绝不产生成功 Execution |
| engine.claimed / task_recorded / finished | 原仓储提交后；真实 execution_id/task_id/status/结果引用；不重复复制完整结果 |
| report.queued / attempt_started / attempt_finished | 原 ReportRepository 的真实 attempt；新旧引用、业务状态与内容覆盖分开 |
| trace.observation_gap | 可写时的真实观测故障/预算触达；存储不可写时明确只能受控日志或进程内信号 |

没有现有业务动作的“用户主动拒绝计划”不新增 endpoint，也不伪造该事件。权限验证前的非法请求不绑定其他人的 Root，不记录凭证；运行主体无法确认时 actor=unknown。

当前每 Run 256 Event 的预算是阶段 0 已识别的限制。完整生命周期需在评审后给 Root 使用可配置且有上限的较大预算，报告 Run 保持旧预算；事件分页、限长与缺口披露保留。不要因轮询生成 lifecycle_changed、Span 或事件，每个未改变的投影不写库。

## 5. Engine 的 claim/replay 边界

现有执行顺序必须保留：replay → check_approval → DatasetLoader.load → claim（内部再次 check）→ TaskRunner → save_task → finish。仅加观测钩子，不重排加载、锁、校验或计算。

- 已存在请求 replay/in_progress/conflict：记录真实请求动作，**不新建 Analysis Engine 计算 Span、不产生任务执行记录**。
- preflight 的 Validator/数据加载确实执行时，保存 Root 下 scope=engine_preflight 的诊断 Span；不能假装 claim 后才发生。相同请求竞态的失败 claim 可能已有真实前置读取，允许显示这段诊断，不视为第二次计算。
- 只有新 claim 接受后建立 analysis_engine 主 Span；其子诊断引用真实 TaskRunner/StepExecutionLog、save_task、finish。前置读取耗时与计算 Span 分开，Inspector 说明边界。
- check_approval 在 claim 事务内再执行时有单独 engine_claim Validator Span，不把两次合为一次。
- 并发相同 request 的 loser 不创建成功 Engine Span。claim 完成但 Trace 创建失败：计算继续，标未采集，不补造事后开始时间。
- Engine 返回 ExecutionResult.execution_status=partial_success 对应 node partial；全任务失败对应 failed 的业务结果但不是吞掉 HTTP 异常。具体 node business_outcome/error_code 与技术异常分开。

## 6. ReportGeneration 尝试历史的最小兼容方案

已存在 latest ReportGeneration 与 Report TraceRun，各职责不同。Trace fail-open 不能替代可靠的业务 attempt 历史。建议阶段 5 在**原 ReportRepository** 增加 report_generation_attempts，复用 ReportGeneration 模型，以 (execution_id,attempt) 唯一：

1. queue/start/finish 在同一个业务事务写原 latest 投影和对应 attempt 记录；不创建第二个报告调度器，不改变 expected_attempt、重试资格、输出 Schema。
2. 每个 attempt 独立，活动态可更新，终态不覆盖；旧报告 ID 保留。最新表仍是现有接口的事实入口，历史表是同一 Repository 的版本历史，不由 Trace 回写业务。
3. 升级时最多登记现有最新 record 的已知状态，标来源 migrated_current_record；不是补造开始/失败事件。更早 attempt 没有记录则 unavailable，不能从当前配置/后来报告重建。
4. 若评审认为暂不加业务历史表，必须降级交付声明：历史 Report attempt 仅在 Trace 存在时可追溯，不能保证 Trace 故障下的完整业务尝试历史。两种方案需明确选择，本设计推荐第 1 种。
5. Report TraceRun 继续使用 (execution_id,attempt) 唯一，增加/暴露该 generation_ref 即可，不发明 generation_id。已有 workflow_run_id 关联保留。

Report 输入 precheck/Validator 和 ChartBuilder 在真实调用点新增 Span。Persistence 需确认 reports.finish 实际提交本 attempt，过期 no-op 不记新的 saved；这是明确提交结果的兼容观测，不改变幂等返回的业务效果。

## 7. Root 并发、重试和恢复

- Root 继续使用 workflow_session_unique 原索引。同 Session 的准备重试、澄清、审批、报告重试查原 Root，不按 HTTP 请求建新 Run。
- 跨 HTTP/后台请求重新按 Session 查关联，用原 ContextVar 的 with/finally 作用域或显式参数传到同步服务。不要依赖请求已经结束的内存 active Span，也不引入 Runtime。
- Root 更新必须带实际业务 revision/分支快照校验；在更新前重新核对当前分支。旧 report attempt 或旧计划的完成事件保留，但不能覆盖新分支状态。原 Session revision 单调守卫保留；Trace 内 projection_revision 防 UI 接收更旧视图。
- Root 可在原业务允许的重试/修订后 reopen，旧结算追加 Event，旧失败 Span/子 Report Run 不重开。无合法业务恢复动作时，仅 reconciliation 更新状态解释，不能调用节点。
- 启动恢复保持原 Engine→Workflow→Report→Trace→Call 顺序，并在业务恢复后重建 Root 当前投影；只给实际未结束 Span 标 interrupted，不造 finished_at/duration。已结算业务可被正确投影，不能因遗留 running Trace 把真实已完成结果变失败。
- 业务记录/Trace 写入之间没有分布式事务，不能承诺 exactly-once 全部遥测。允许已存在 Root 的投影校正，不补造节点记录。
- 历史无 Root 或登记失败的 Session：默认不自动补注册。业务投影仍可查看，run_id=null、collection=not_collected；如未来要显式补登记，必须标 started_late，真实记录从那一刻起，不追认早先未采集节点。

## 8. 只读 Admin 查询提议

不改原 /admin/runs 默认 report_generation，兼容旧报告列表/对比。Admin UI 以后显式改用新 Workflow 视图；当前仅开放 Trace/Prompt 的导航限制继续保留。

| 提议 API | 复用/行为 |
|---|---|
| GET /admin/workflows | 从现有 real_v1 Session/业务表构造主列表，关联 Root；一任务一行，run_id 可空，分页/过滤；不生成运行记录 |
| GET /admin/workflows/{session_id} | 兼容已有 availability/run/observation_gap 字段，增量加入 lifecycle 投影和 collection；Session 不存在时明确不存在 |
| GET /admin/workflows/{session_id}/progress | 当前分支的主逻辑节点、全部 Span/Report 子 Run 引用、Attempt 历史摘要；节点状态来源明确 |
| GET /admin/runs/{run_id}/spans/events 等既有接口 | 保留报告与 Root 真实诊断数据，不更换权限，不给缺失字段填当前值 |
| Report attempt 历史查询 | 阶段 5 可在原执行/报告 namespace 增加只读历史查询；复用保护机制，暴露复合键 |

推荐 Workflow 响应分为 business_lifecycle、collection、progress 三部分。节点含 logical_node_id、display_status、state_source=span/business_event/derived_pending/not_collected、current_span_id、attempt_refs、business_outcome；没有记录的 span_id=null。不把一个仅有最终结果的历史节点标为“已采集成功”。

业务状态和采集不完整可以同时成立，例如 succeeded + incomplete；界面同时展示，不用一项抹去另一项。API 错误显示当前数据不可用，保留带 stale 标记的上次内容，不能擅自把节点改成 failed/skipped。

## 9. 版本、权限与迁移

- 当前原模型 extra=forbid，新字段必须先做可选、旧 JSON 默认 unknown；旧 Report Manifest 内容/哈希不改。无必要不改业务公开契约。
- Node/Run 的新引用在本库做合法归属检查；跨业务库/Registry 无原生外键，查询时核对 Session、版本及引用。非法跨 Run parent/Event 仍拒绝。
- Prompt 内容与模型参数保持不变。由于 TemplateSource 源指纹包括服务/组合代码，阶段性埋点会改变代码组合哈希：每阶段登记明确的新组合版本，保留旧快照，做同输入最终 payload/Schema/参数前后对照；不能把同一版本号换内容，也不能为通过比较伪造哈希。
- 原 Trace 写故障继续 fail-open、受控日志/可检测缺口；原 Prompt Registry 必须留档的 fail-closed 策略保持。新观测钩子不能在业务持锁时做网络或重型快照工作；锁竞争、缺口有专项测试。
- 新查询沿用现有 Admin 只读鉴权/本机测试边界。默认无原始请求正文；完整快照经原授权入口读取。错误码白名单、8 KiB Event 与受控投影限长保留；不存 token/API Key/完整原数据。原始请求到期仍按原策略处理，元数据/历史不擅自清理。
- 阶段 0 无迁移。阶段 1 验证已有 V0.3.1 迁移而非重建；阶段 5 才考虑业务 attempt 历史最小追加，先备份受限存储、事务迁移、外键/唯一性/回滚与旧 JSON 测试，绝不覆盖旧档案。
