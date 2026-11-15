# Root 状态机针对性审查

日期：2026-10-30。需求：REQ-0072。范围：只读审查现有运行代码、临时数据库复现和既有测试。不修改业务源码、数据库结构、生产数据、Prompt、参数或运行服务，不调用真实模型。

## 结论

当前实现是“Session 业务状态 + 准备阶段 Root Trace + 独立 Report TraceRun + Lifecycle 只读聚合”，不是已经覆盖完整执行交付的 Root 状态机。现有准备流程和报告流程可以兼容共存，但 Root 不应被当作最终业务完成状态。

确认一个优先修复的并发写入问题、两个状态防护缺口，以及一个特定恢复场景下的报告 Trace 一致性问题。167 项既有相关测试通过，不等于这些未覆盖场景已安全。

## 一、问题与证据

### F1 / P1：Root revision 防回退检查不是原子的

位置：`backend/app/storage/trace_repository.py:60`，`TraceRepository.update_run()`。

函数先 SELECT，再在 Python 中比较 business_revision，最后执行无条件 UPDATE。读取之前没有 BEGIN IMMEDIATE，也没有带预期版本的条件 UPDATE。SQLite 串行化写操作并不能保护此前已完成的无锁读取。

在临时 SQLite 的两个真实仓储调用中，控制两者先读到 revision=1；revision=20 的 waiting_approval 先提交，revision=10 的 failed 随后提交。最终数据库为 revision=10/failed，较新进度被覆盖。顺序负对照中，先提交 revision=20、再启动读取旧更新，旧 revision 正常被忽略。因此问题是读写窗口，不是“所有低版本更新都会生效”。见 probe.py、probe-results.json。

影响：Admin Root 状态和分支 revision 可倒退；Session 和不可变批准记录未被此 Trace 仓储直接改写。该方法也服务 Report Run，修复时必须保留其独立终态保护，不能只给 Root 调用方加锁。

建议：仓储内原子读改写，配合观测版本 CAS；明确返回 applied/stale/rejected，不能静默吞掉拒绝结果。BEGIN IMMEDIATE 可收窄当前竞争窗口，但本身不能解决同 revision 的旧 attempt。

### F2 / P2：Root 只有目标状态白名单，没有合法迁移矩阵或 attempt fencing

位置：`backend/app/storage/trace_repository.py:66`，`TraceRepository.update_run()`；`backend/app/observability/workflow.py:47`，`start_preparation()`。

仓储允许 Root 进入 queued/running/waiting_input/waiting_approval/failed/interrupted，未按旧状态检查成对迁移。可直接 failed→queued，无需核验准备阶段重试资格。相同 business_revision 的两个旧对象也可相互覆盖；临时复现中 waiting_approval 被同 revision 的 failed 覆盖。

这是仓储防护缺口，不表示公开 API 已允许任意恢复。业务入口 `begin_real_retry()` 有真实资格检查；`SessionRepository.mutate()` 也有写事务和 expected_revision。但 Root 仓储未绑定该重试 claim，未来迟到回调、多写者或错误调用可绕过观测层顺序。现有 API 没有公开任意写 Trace 的入口。

建议：按 kind 分离迁移规则；Root 从 failed/interrupted 恢复必须绑定已接受的 Session 重试 revision 和准备 attempt/epoch。同 revision 内的合法开始、结束事件应有明确序号，不能仅禁止所有等版本写入，否则会拒绝正常状态更新。保留旧 Span，增加新 node_attempt，不复用旧 Span，也不要改变 Root 唯一身份。

### F3 / P2：checkpoint 事件先写、状态更新后判定，陈旧回调没有明确标记

位置：`backend/app/observability/workflow.py:60`，`checkpoint()`；同文件 `interrupt()`。

checkpoint 先持久化 workflow.failed/waiting_* 事件，再执行 Root 更新。低 revision 更新会被静默忽略，但事件已进入时间线；interrupt 更使用旧 TraceContext 中的 business_revision。事件包含 session_revision，尚无明确 stale/ignored 判定，也不与 Root 更新原子提交。

影响：事件可作为历史回调证据保留，但 Admin 不应把最后一条事件直接当当前业务状态。现有 Lifecycle 根据 Session/计划/批准/执行聚合，未采用“最新事件=当前成功”，这一点正确。

建议：明确区分“已接受状态变更”与“迟到回调收到/忽略”事件。先得到仓储接受结果再发相应事件，或在 Trace 同库事务内提交状态与事件。观测故障继续 fail-open，但标记缺口，不能伪造已接受迁移。

### F4 / P2：部分恢复 + 旧 worker 仍返回时，Report Trace 可误称持久化完成

位置：`backend/app/storage/report_repository.py:66`，`ReportRepository.finish()`；`backend/app/workflow/reporting.py:52`，`ReportWorkflow.generate()`；`backend/app/observability/recorder.py:144`，`TraceContext.finish()`。

ReportRepository.finish 在 attempt 不匹配或状态已结束时返回 None，正确拒绝旧结果写入。调用方却不区分“确实保存”与“被忽略”，随后仍完成 report_persistence Span、保存报告投影并调用 trace.finish(report.report_status)。

临时业务集成复现：旧 attempt=1 正在生成，业务恢复将其标为 failed，再创建 attempt=2；旧调用随后返回。当前 generation 仍为 attempt=2/queued，旧报告未保存，但旧 Report Trace 为 complete，且 report_id 指向不存在的报告。见 report-stale-results-v2.json 的 partial_recovery。

必须限定触发条件：这个调度模拟业务恢复成功而 Trace 恢复未执行/失败，同时仍有孤立工作者返回，并非正常单进程重启。负对照同时执行业务和 Trace 恢复后，旧 Trace 保持 interrupted，未变 complete。当前部署明确以单进程为边界；不能把此条件性风险描述成每次报告重试都会误报。

建议：ReportRepository.finish 返回持久化接受结果；仅 accepted 后记录成功的 persistence/报告交付终态。被替代的旧 attempt 保留 ignored/stale 事件和旧历史，不生成已交付报告快照。保留原 Report Run 的终态不可重开规则。此处是后续修复建议，本轮没有实施。

## 二、complete / partial 的实际含义

| 对象 | 当前状态语义 | 注意事项 |
|---|---|---|
| Session | RUNNING→COMPLETED 或 FAILED | Engine success 和 partial_success 都使 Session 为 COMPLETED，不表示报告成功或完整覆盖 |
| Workflow Root | queued/running/waiting_input/waiting_approval/failed/interrupted | 当前只覆盖准备阶段；update_run 明确拒绝 complete/partial |
| Report TraceRun | queued→running→complete/partial/unavailable/failed/interrupted | 属于某 execution_id 的某次 report attempt；终态不能改写或重开 |
| AnalysisReport | report_status=complete/partial/unavailable；goal_coverage 独立 | 生成完成不等于核心目标完整回答 |
| ReportGeneration | queued/generating/completed/failed/unavailable | partial 报告保存后，generation 仍为 completed，需要读取报告状态区分 |
| Lifecycle Read Model | succeeded/partially_succeeded/failed 等 | 综合当前分支 Engine、报告状态与目标覆盖，不从 Root 状态推断业务成功 |

真实代码：`domain/tracing.py:22` 的 TraceRun 与 valid_kind；`storage/execution_repository.py:95` 的 finish；`observability/workflow.py:60` 的 checkpoint；`services/lifecycle.py:196` 和 `:223` 的 aggregate。

TraceRun 公共模型包含 complete/partial，不代表 Root update_run 已支持这些状态。模型/创建路径也没有完整的按 kind 状态语义校验，不能用“模型可解析”代替迁移合法性。Root 不闭环是现有 workflow_preparation 采集边界，不是已经发生业务失败；对全生命周期 Root 目标而言，这是待实现能力。

例：Engine success + Report failed，Lifecycle 为 partially_succeeded，含 report_failed/report_not_delivered；Engine partial_success 即使报告生成 complete，也不应被聚合为 succeeded。代码已有这些分支，相关测试通过。

## 三、失败与合法重试

| 场景 | 当前合法行为 | 代码依据 |
|---|---|---|
| Planner 等准备阶段失败 | real_v1、FAILED、有 retryable error、无 review_plan、无 execution 才允许显式重试；使用 expected_revision | orchestrator.py:328 begin_real_retry；session_repository.py:33 mutate |
| 恢复检查点 | 有 planner_result 从 validating 恢复；有效 intent 从 planning；否则 parsing_intent/profiling | orchestrator.py:328 begin_real_retry |
| Intent 澄清 | 仅 WAITING_FOR_CLARIFICATION 接受补充；清除旧 planner_result，进入 PARSING_INTENT；保留 Root ID | orchestrator.py:317 begin_real_clarification；observability/workflow.py preparation_context/start_preparation |
| HITL 修订 | 持久化不可变新版本、清空当前批准；旧 revision/plan ID/version 被拒绝 | services/plan_review.py revise_v1/current_guard；storage/plan_review_repository.py transaction |
| 执行中改计划 | RUNNING/PREPARING 时 revision_guard 拒绝；不能仅因 current_guard 没有状态检查就判定可修改 | services/plan_review.py:107 revision_guard |
| Engine 请求重放 | 相同 execution_request_id 返回保存结果；运行中拒绝重复；失败重放仍为原失败结果 | storage/execution_repository.py _existing/replay/claim |
| Engine 失败再计算 | 准备重试入口不接受已有 execution；不能假设换 request_id 即可绕过 Session/Approval 检查；新有效版本重新审批另行执行 | services/analysis_engine.py check_approval；plan_review.py revise_v1/approve_v1 |
| Report failed | expected_attempt 精确匹配、在业务写事务中 claim 新 attempt；新独立 Run，retry_of_run_id 关联旧 Run | storage/report_repository.py:33 queue；observability/recorder.py:214 queue |
| Report partial/complete/unavailable | partial 被 generation completed 表示；completed/unavailable 不允许原入口重试，返回已有记录 | storage/report_repository.py:33 queue |

Root 在准备重试时复用同一行并清空当前 error/finished_at；旧失败 Span/Event 继续保存。Root attempt 当前固定为 1，节点 node_attempt 与 LLM retry_index 是另两种编号，不能混用。RunManifest 保持不可变，重试后实际调用参数应以 LLMCallRecord/RequestSnapshot 为准，不以 Root 初始模型配置冒充每次实际调用。

## 四、并发、旧分支与跨库边界

1. **已有保护**：Session.mutate、HITL transaction、Execution.claim、Report.queue/start/finish 使用 BEGIN IMMEDIATE；客户端 expected_revision、plan_version、approval snapshot 和 report attempt 有真实检查。Root 唯一索引按 session_id，Span attempt 与事件序号分配也有事务。
2. **没有覆盖的保护**：这些业务事务不包含 Trace sidecar；Root.update_run 的读改写非原子，尚无生命周期 epoch。现有并发测试主要覆盖唯一 Root、事件序号与 Span 编号，不覆盖 F1 的状态竞争。
3. **旧 Plan/Approval**：Engine.check_approval 校验当前 Plan、批准版本、数据集和 Validator；保存旧 Execution 的结果与报告可以保留历史，不能回写成当前分支完成。Lifecycle.aggregate 以当前 Plan/Approval/Execution 匹配并标记 historical_branch_ignored，方向正确。
4. **Engine.finish 防御性边界**：写 Session 终态只检查 status==RUNNING，未再次完整比较 Execution/Plan/Approval 身份。当前正常路径有“执行中不可修订”和原子 claim 保护，未复现公开路径可触发跨版本错误完成，不把它列为已证实漏洞。未来引入取消、并发分支或旧工作者接管时必须补 execution fencing。
5. **中断恢复**：TraceRepository.recover 将所有 queued/running 标 interrupted；等待澄清/审批保持可恢复。它按单进程重启语义工作，没有活跃 owner 租约判断，不支持直接部署多 worker 后互相恢复。ReportGeneration 同样只有当前 attempt 行，没有完整业务尝试历史表；历史 Report Trace 行不能反向冒充业务记录。

## 五、Report 独立 Run 的兼容性要求

当前独立 Report Run 是正确的兼容边界：唯一键 execution_id+attempt，workflow_run_id 可关联已有 Root；没有 Root 的历史报告允许为空；重试新建 Run，旧 Run 和 Manifest 不覆盖。迁移保留报告旧数据及子记录，已有迁移字节保留测试通过。

后续若扩展 Root 生命周期，应满足：

- Root 唯一身份仍绑定 Session，不能把现有 Report Run 改成 Root 或合并删除。
- 按 kind 或明确 lifecycle 契约版本分离迁移规则。不得把 Report terminal→running 全局开放，只为满足 Root 合法恢复。
- Root complete 应要求当前数据集、计划、批准、执行、报告 attempt 身份匹配；partial 应由当前真实结果和覆盖状态决定，不按“有失败 Span”计数。
- 报告旧版本回调只能结束对应旧 Report Run；只有接受为当前分支结果的业务提交才能触发 Root 交付汇总。
- 业务结果和 collection/integrity 分开；缺少 Trace 不伪造 Span、不由历史最终报告反推节点完成。
- 建议先修 F1、F2/F3 和 F4，再扩展 Root complete/partial。单纯增加枚举无法完成闭环，还可能破坏现有 Report Trace 终态不变性。

以上均为评审建议，没有新增表、接口或字段。

## 六、验证记录

- 既有相关自动化回归：167 passed，1 个 Starlette TestClient 弃用 warning；regression.txt。
- 临时仓储复现：probe.py / probe-results.json。含 complete/partial 拒绝、同 revision 覆盖、顺序低 revision 拒绝、真实并发低 revision 覆盖、Report partial 终态保护、Root failed→queued 白名单缺口。
- 临时业务集成复现：report-stale-probe.py 及 v2 对照。使用项目既有本地测试 Provider，既有真实仓储和 ReportWorkflow；不调用外部 LLM。故障/调度是人工控制，不冒充生产已发生记录。
- 旧脚本与首次输出均保留；v2 补充完整恢复负对照，不覆盖旧文件。
- 未执行前台任务，不修改用户 Session、Trace、报告或服务配置。本轮到审查结束，不自动进入修复或 UI 开发。
