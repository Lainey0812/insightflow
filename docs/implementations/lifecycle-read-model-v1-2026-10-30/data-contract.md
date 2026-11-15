# Lifecycle Read Model 数据契约

契约版本：`lifecycle-read-v1`。正式机器契约是 `backend/app/domain/lifecycle.py` 和同目录 `lifecycle-read-v1.schema.json`。

## 1. 数据来源和只读约束

Session 继续作为唯一 Workflow Root 的业务锚点。读取业务库 `insightflow.sqlite3` 与原 Trace sidecar `observability/trace.sqlite3`；无新数据库、调度器、缓存表或迁移。

`LifecycleReader.read` 用 SQLite URI `mode=ro`，设置连接级 `query_only=ON`，`BEGIN` 一致性读事务。业务对象在同一业务事务快照中读取；Trace 在第二个只读事务中读取。关闭后复查 Session 完整保存内容（包含 revision），变化则 `session_changed`。数据库不存在不会创建目录或文件。服务只保存路径，构造时不连接/迁移。

`aggregate` 是纯函数。它解析既有 Pydantic 保存契约，检查记录绑定及已保存的执行状态；不运行 PlanValidator，不重新审核约束，不读取原始上传文件或完整结果表，不调用任何可能 mutate 的 Repository/Workflow/业务服务，不创建 Run/Span/Event，不设置 Trace 上下文。

查询仅返回受控元数据和实际引用，不返回用户目标原文、样本、结果行、Evidence 内容、LLM 消息、密钥或异常详情。内部读取 Session、画像和执行预览是为了核对契约，完整 `execution_results` 不读取；报告通过 SQL 只取关联元信息，不加载报告正文与结果数据。

## 2. 输出字段

| 字段 | 值/含义 |
|---|---|
| `schema_version` | 固定 `lifecycle-read-v1` |
| `business_lifecycle.status` | created / running / waiting_input / waiting_approval / succeeded / partially_succeeded / failed / interrupted / unknown |
| `business_lifecycle.execution_status` | 实际 running / success / partial_success / failed，未确认 null |
| `business_lifecycle.report_generation_status` | 当前执行最新已保存 queued / generating / completed / failed / unavailable，未确认 null |
| `business_lifecycle.report_status` | 已保存报告 complete / partial / unavailable；不是生成任务状态 |
| `business_lifecycle.goal_coverage` | 已保存报告 complete / partial / blocked |
| `business_lifecycle.report_delivery` | delivered / not_delivered / unknown |
| `activity` | not_started / preparing / profiling / parsing_intent / planning / validating / clarification / review / approved_not_started / executing / report_not_started / report_queued / reporting / finished / unknown |
| `reason_codes` | Schema 中定义的有限原因集合，无自由文本业务推理 |
| `source_refs` | 实际 Session id/revision、数据集 id/version、plan id/version、validation version、approval id、execution id、report attempt/id、Root Run id、当前 Report Run id；缺失为 null |
| `collection` | 采集 availability、integrity、原 capture_scope、Root 状态/revision、当前报告 Trace 状态、实际 Span 引用/局部 attempt/状态、所选 Run 的已存 Event 总数 |
| `consistency` | consistent / unknown / inconsistent；事务快照情况、Session 复查结果、固定 `cross_store_snapshot=non_atomic` 及具体问题 |

上述生命周期是只读产品语义，不写回 Session 或 TraceRun。`source_refs` 是查到的来源引用，并不构成新的审批或执行权限；若存在冲突，业务 status/activity/delivery 都为 unknown，保留可核查引用与源状态。

`collection.availability`：available=有被实际选中的 Root/当前报告 Run；not_collected=已查询但没有相应记录；unavailable=Trace 存储不可访问；unknown=业务数据不足，未能完成关联检查。

`collection.integrity` 当前只可能 incomplete / unknown。即使原 Root 的 integrity=observed，本轮也不声称已有整条 Workflow 埋点；准备阶段 scope 原样展示，不升格为全流程采集。Span 列表只包含真实表中存在、归属选中 Run 的记录。没有 Engine Span 时不补 Engine 成功节点。

`report_attempt_history=not_guaranteed` 明确现有 ReportGeneration 表只存最新 attempt，本轮没有补历史。

## 3. 当前分支关联

1. 核对真实 `real_v1` + uploaded Session，旧 Mock/manual review 不升级为真实主流程。
2. 当前 `dataset_ref` 与 FileInfo、持久化画像、Session 画像及内容哈希匹配。
3. Session `review_plan` 必须与不可变 `plan_versions` 的最高版本完整相等，同时内外 dataset/plan/validation 标识一致；不是按成功时间选取。
4. 当前 engine_approval 必须与不可变 ReviewApproval 完整一致，绑定当前 PlanVersion 和 validation；已保存批准状态、确认标记、意图和未解决项不能相互矛盾。不重新判断操作可行性。
5. Execution 必须属于 Session 已接受的 `engine_execution_ids`，请求与保存的批准快照匹配当前分支；结果的 Session/dataset/plan/approval/request 及任务集合逐一核对。多个当前候选返回 execution_ambiguous，不挑“最近一个”。任务集合包括 Engine 为 F0 任务保存的 skipped 项，而不只包括 executable_task_ids。
6. 只读取所选 Execution 的 ReportGeneration，必须与 Session 中镜像完整一致；已交付报告通过 report id、Execution、dataset、plan version、audit 中的 approval/plan/Session 绑定核对。
7. Report Trace 按 execution_id + 最新业务 attempt 匹配，不按时间或列表顺序；旧 attempt 不覆盖新 attempt。若 Trace 出现超前 attempt、相反的终态或冲突绑定，返回 unknown/inconsistent。

可明确识别的历史旧分支保存不动，通过 `historical_branch_ignored` 解释为什么没有沿用；它不是当前执行结果。若旧回调把 Session 改成“完成”却不存在当前分支执行，返回 unknown；不会用历史成功补全。

## 4. 生命周期判定表

| 已验证的当前事实 | status / activity | 原因/交付 |
|---|---|---|
| CREATED、无后续记录 | created / not_started | 无虚构节点 |
| 准备阶段保存状态 | running / 对应准备活动 | 表示最后持久化活动，不证明进程此刻存活 |
| Intent clarify + Session 等待 | waiting_input / clarification | clarification_required |
| 当前计划待审批 | waiting_approval / review | approval_required；保留 core_requirements_unmet / uncertainties_unresolved |
| 有效批准、尚无已接受执行 | running / approved_not_started | 不标记 Engine executing |
| 当前 execution running | running / executing | 无过程 Span 时 collection 仍不完整 |
| Engine success，报告尚未登记 | running / report_not_started | report_not_started + report_not_delivered |
| Engine partial，无报告登记 | partially_succeeded / report_not_started | execution_partial + report_not_delivered |
| 新报告 queued / generating | running / report_queued 或 reporting | report_retry（attempt>1），不沿用上次失败终态 |
| Engine success/partial，报告 failed | partially_succeeded / finished | report_failed + report_not_delivered；Engine 状态原样保留 |
| Engine success/partial，报告 unavailable | partially_succeeded / finished | report_unavailable + report_not_delivered |
| Engine success + 保存报告 complete + goal complete + 当前计划完整覆盖 | succeeded / finished | delivered；允许 Trace 缺失 |
| Engine partial / 报告 partial / goal partial 或 blocked | partially_succeeded / finished | 对应原因码；存在有效报告则 delivered |
| Engine 全部失败 | failed / finished | execution_failed；报告无证据不掩盖执行失败 |
| 准备 PROCESS_INTERRUPTED；或 Engine 恢复结果 EXECUTION_INTERRUPTED 且未继续报告 | interrupted / finished | process_interrupted，保留原结果 |
| 报告恢复失败 REPORT_PROCESS_INTERRUPTED | partially_succeeded（有计算成果时） | report_failed + report_not_delivered + process_interrupted |
| 必需记录缺失、非法契约、无法唯一定位 | unknown / unknown | consistency=unknown |
| 版本、当前分支、已保存状态或跨库事实冲突 | unknown / unknown | consistency=inconsistent |

报告 partial 与生成任务 completed 是兼容组合，不能误判为完整业务成功。业务交付已确认但 Trace finish 遗漏、仍停在 queued/running 时只标记 trace_stale；Trace 声称相反终态则是可确认的冲突。Trace 未采集/不可访问本身不降低可信业务成功。

## 5. 原因码分组

- 人工交互：clarification_required、approval_required、approved_not_started、core_requirements_unmet、uncertainties_unresolved。
- 执行/交付：execution_partial、execution_failed、report_failed、report_not_delivered、report_unavailable、report_partial、goal_not_fully_covered、report_not_started、report_retry、process_interrupted。
- 采集：trace_not_collected、trace_unavailable、trace_incomplete、trace_stale。
- 不一致/未知：trace_binding_mismatch、trace_state_conflict、unsupported_workflow、record_missing、record_invalid、branch_mismatch、historical_branch_ignored、execution_ambiguous、session_changed、business_store_unavailable、business_state_conflict。

这些字段不能替代现有批准与执行接口的服务端权限检查。
