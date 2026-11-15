# Session / Workflow 身份假设只读兼容性审计

日期：2026-10-30。需求：REQ-0074。架构约束：REQ-0073，Workflow Root + Node Span 两层，不新增第三层节点或独立 Attempt 实体。REQ-0073 是上一条用户原文在本轮补录，不冒充当时已完成归档。

## 结论与术语

当前代码没有独立的业务 `workflow_id` 字段，也没有直接将 `run_id` 字符串赋为 `session_id`。`register_root()` 实际生成独立 `run_<uuid>`，`workflow_run_id` 对 Workflow Root 指向自身 run_id，session_id 则保存 Session.id。

真正存在的假设是：**一个 Session 就是一条业务分析工作流及其计划修订历史，且最多对应一个 Workflow Root Trace**。不能把“ID 值不同”误认为“Session 与 Workflow 的业务身份已经解耦”。目前重试、澄清、删任务是同一 Session 的延续，不是同一聊天容器下多条独立业务工作流。

如果未来只是为现有一对一关系增加名称别名，改动较小，但必须明确别名含义；如果目标是一条 Session 内容纳多条工作流，现有主键、状态槽、查询、幂等键、权限和聚合都需评审，不能只放开唯一 Root 索引。本轮不决定新增业务 ID 的名称或最终模型，也不新增表、接口或实现。

## 1. Session 唯一 Root：显式硬约束

| 位置与函数 | 真实行为 | 兼容性含义 |
|---|---|---|
| `storage/trace_migrations.py:26`，migrate_workflow_roots | 对 kind=workflow 的 JSON session_id 建唯一索引 workflow_session_unique | 数据库禁止同 Session 多 Root |
| `storage/trace_repository.py:48`，create | INSERT OR IGNORE；Workflow 返回 workflow(run.session_id) | 相同 Session 再登记会返回已有 Root，而不是新工作流 |
| 同文件 `:55`，workflow | 仅按 kind=workflow + session_id 查询单条 | 没有业务工作流选择参数 |
| `observability/workflow.py:11`，register_root | 新 run_id、自引用 workflow_run_id、Session 来源的 file/goal/created_at/业务 revision | Root 的输入和生命周期取自 Session |
| 同文件 `:40`，preparation_context | 仅用 session_id 获取 Root | 所有准备节点及其重试附着同一 Root |
| `observability/recorder.py:214`，TraceRecorder.queue | 为 Report 按 execution_id+attempt 创建独立 Run；用 execution.session_id 查父关联 Root | Report 自身不是按 Session 唯一，但其 Root 查找仍依赖一对一关系 |
| `domain/tracing.py:22`，TraceRun.valid_kind | Workflow Root execution_id 必须为空，workflow_run_id 必须等于自身 run_id | 已区分 Root 与 Report Run，不能删除该区分 |

重要后果：若直接在旧 Session 内“启动另一条 Workflow”，重复登记可能回收旧 Root、旧不可变 Manifest，而不是可靠地拒绝业务输入冲突。这是当前一对一模型下的幂等设计；扩展后会成为错误关联风险。

Trace 仍是 fail-open 的观测侧库，业务成功允许没有 Root。`register_root` 失败时只记 workflow_gap。因此不能未经设计就把“数据库里一定存在的 Trace run_id”当作所有业务对象必须持有的唯一归属键，否则会改变 Trace 写失败不得影响业务的约定。

## 2. PlanVersion、Approval、Execution、Report 归属键

| 对象 | 主键/唯一约束 | 归属与当前选择 | 多 Workflow 同 Session 的阻碍 |
|---|---|---|---|
| SessionState | sessions.id | 单个 file/dataset_ref、user_goal、intent、status/revision/error、review_plan、engine_approval | 不是纯聊天容器；只有一组当前分析状态 |
| AnalysisPlan | Schema 含 plan_id、dataset_id/version、plan_version | 纯规划契约不含 Session/Trace ID | 可独立复用，但持久化适配层仍 Session 化 |
| PlanVersion | PRIMARY KEY(session_id, plan_version)；plan_id 非主键组成 | PlanVersion.session_id；current_guard 按 Session 全历史最后版本匹配 | 两条独立计划不能各自在同 Session 从 v1 开始；最新版本检查会把另一条计划当旧分支 |
| ReviewApproval | approval_id 主键；UNIQUE(session_id, request_id) | session_id + plan_id/version + dataset/version + validation_version；当前批准在 Session.engine_approval | 历史审批可区分计划，但当前批准槽只有一个 |
| Execution | execution_id 主键；execution_request_id 全局唯一 | request.session_id + plan_id/version；保存不可变批准快照；Session.engine_execution_ids 汇总 | 历史执行身份较完整，但 claim/finish 更新同一 Session.status/revision |
| ReportGeneration | execution_id 主键 | session_id 归属；每执行当前 attempt/status/report_id；镜像到 Session.report_generations | 已按执行隔离；并非按 Session 挑最近报告，但只有当前 attempt 行 |
| AnalysisReport | report_id 主键；报告内 execution_id、dataset/version、plan_version | audit 中保存 session_id/approval_id/plan_id；权限按 audit.session_id | ID 查询相对独立，但所有权与权限仍在 Session 层 |
| Report TraceRun | UNIQUE(execution_id, attempt) | session_id + workflow_run_id，可无历史 Root；retry_of_run_id 指向旧 Run | 历史兼容必须保留，不得合并成 Session 最新报告 |

来源：`domain/models.py:137` SessionState、`:125` ReportGeneration；`domain/plan_review.py:11` PlanVersion、`:28` ReviewApproval；`domain/execution.py:107` ExecutionRequest；`domain/analysis_plan.py` AnalysisPlan；`domain/analysis_report.py:77` AnalysisReport；`storage/plan_review_repository.py:8` 初始化 DDL；`storage/execution_repository.py:13` 初始化及 claim/finish；`storage/report_repository.py:9` 初始化及 queue/_write_generation。

状态槽的影响不仅在查询：`WorkflowOrchestrator.prepare_real(session_id)`、begin_real_retry、begin_real_clarification、save_generated_plan 都读写这一份 Session。save_generated_plan 要求 review_plan 为空，初始 plan_version 固定为 1。这不支持同一 Session 再创建另一份独立分析计划。PlanReview.revise_v1 是同计划修订，不是新工作流启动。

## 3. 按 Session 解析“当前/最新”的入口清单

以下范围覆盖当前业务 API、Admin API、服务与前端直接调用，不把历史/显式 ID 查询误称为“按最新成功时间选结果”。

### 3.1 当前对象与聚合入口

| 入口 | 实际选择依据 | 结论 |
|---|---|---|
| GET /api/v1/sessions | SessionRepository.list 按 Session.updated_at 排序 | 最近更新的咨询列表，不是最新成功 Workflow 列表 |
| GET /api/v1/sessions/{session_id} | Session 单条快照 | 前端恢复、轮询及多种当前结果字段的事实入口 |
| GET /api/v1/sessions/{session_id}/profile | Session.dataset_ref，再精确按 dataset_id/version | 当前 Session 画像；不是按画像创建时间选最近 |
| GET /api/v1/sessions/{session_id}/plan | Session.review_plan | 唯一当前计划槽 |
| GET /api/v1/sessions/{session_id}/review | PlanReviewService.review_presentation/current_guard | 当前计划；内部 current_guard 以 Session 版本历史最后项核对 |
| GET /api/v1/sessions/{session_id}/report | completed_report 读取 Session.report | 旧 Report 契约入口，不是新 AnalysisReport 的通用最新查询 |
| 同上 /report/preview、/report/download | 同一 completed_report，要求 Session.COMPLETED 且 state.report 非空 | 历史兼容路径；真实主流程通过 ReportGeneration.report_id 进入报告页，不能混用 |
| GET /admin/workflows/{session_id}，及 /api/v1/admin 对应别名 | TraceRepository.workflow(session_id) | 路径叫 workflows，参数实际仍是 Session ID，不是 Root run_id |
| GET /admin/workflows/{session_id}/lifecycle，及 /api/v1/admin 对应别名 | LifecycleService.get(session_id) | Session 当前分支聚合，不是某历史 Root 的冻结业务状态 |
| TraceRepository.workflow(session_id) | 唯一 Root 索引下的记录 | 无“最新 Root”排序概念，只有一个 |
| PlanReview.current_guard、AnalysisEngine.check_approval | 按 Session 最新 plan_version、当前 review_plan/engine_approval 检查 | 正确防旧版本执行，同时硬编码单工作流计划命名空间 |
| frontend currentReportGeneration(session) | 当前批准版本相等，再取 engine_execution_ids.at(-1)，匹配 generation.execution_id/session_id | 依赖 Session 接受执行的追加顺序，不是完整的计划/批准快照重匹配 |

相关真实函数：`api/routes.py:44,85,100,107,166`；`api/datasets.py:41`；`api/admin.py:118,127`；`services/plan_review.py:158`；`services/analysis_engine.py:20`；`frontend/src/workflow/presentation.ts:6`。

### 3.2 Session 范围内的历史查询，不应改称“最新结果”

- GET /sessions/{session_id}/plans：真实计划历史（旧流程则 state.plans）。
- GET /sessions/{session_id}/plans/{version}：按该 Session 的版本号取历史记录，没有 plan_id 选择维度。
- GET /sessions/{session_id}/approvals：历史审批；execution_ids 还按 approval_id 过滤，已有正确细分。
- GET /sessions/{session_id}/constraint-audits：该 Session 全部审批约束审计。
- 对应仓储 PlanReviewRepository.versions/approvals/constraint_audits 都按 session_id 分区。

### 3.3 已经使用明确 ID 的入口，应保留

- GET /executions/{execution_id}、/results/{result_id}：指定执行及结果，不选择 Session 最近一次。
- GET /executions/{execution_id}/report：该执行当前 ReportGeneration，不是 Session 当前 Workflow。
- POST 同一 /report：指定执行及 expected_attempt；Session token 只负责权限归属。
- GET /reports/{report_id}、/presentation、/download、/execution：指定保存报告及其来源执行。
- GET /datasets/{dataset_id}/versions/{version}/profile：精确数据版本。
- GET /admin/runs/{run_id}：指定 Trace Run。business_source.latest_attempt 从该 Run.execution_id 查当前 generation，并返回 same_attempt，不能把它描述为 Session 最新业务结果。
- GET /admin/runs/{run_id}/spans、/events、/snapshots，/admin/spans/{span_id}/events、/admin/comparison?left=&right=：按 Run/Span ID。
- Intent parse、独立 plans/generate/validate 使用既有 Intent/Dataset/Plan 契约，无须 Session 即可运作；不会凭 Session 伪造 Trace 归属。

## 4. Lifecycle Read Model：分支核对正确，聚合边界仍是 Session

`storage/lifecycle_reader.py:45` 的 read(session_id) 从 Session 取当前 dataset_ref，按 Session 读取计划、审批、执行、generation 和全部 Trace。业务库只读事务与 Trace 库分别读取，之后重读 Session 检测跨库收集期间变更，没有声称跨库原子。

`services/lifecycle.py:74` 起依次：

1. 以 Session.review_plan 为当前计划，并要求它等于该 Session 的最大 plan_version。
2. 核对 Session.engine_approval 与不可变审批持久记录及当前计划一致。
3. 从 Session.engine_execution_ids 接受集合中，选择与当前计划和批准快照精确一致的执行；多个候选记 execution_ambiguous，旧分支记 historical_branch_ignored。
4. 报告必须绑定该 execution_id，并核对 report audit 的 plan/dataset/approval。
5. collection 另按 Session 收集 Root；大于一个 Root 直接标 trace_binding_mismatch，缺少则 not_collected/incomplete；不会从最终报告反推 Span。

因此它**不是“最近成功时间”算法**，但只允许输出 Session 唯一当前工作流。即使两个 Workflow 各自都有完整历史，只要同 Session 同时存在多个 Root/独立计划命名空间，现有聚合也不能直接使用。

`domain/lifecycle.py:30` SourceRefs 仅含 session_id、workflow_run_id、计划/执行/报告等引用，没有独立 workflow_id。Admin LifecyclePanel 以 run.session_id 发起查询，并明确提示历史 Report Trace 与 Session 当前分支不同。这一提示正确；未来如果有同 Session 多 Workflow，仅提示“历史报告”仍不足以避免查错工作流。

来源：`services/lifecycle.py:74,128,271` aggregate/_collection；`storage/lifecycle_reader.py:111,128`；`admin/src/api/lifecycle.ts:33`；`admin/src/features/traces/LifecyclePanel.tsx` 的加载与 historical 判定。

## 5. 前端路由、当前 Session 与权限边界

| 位置 | 隐含假设 | 兼容风险 |
|---|---|---|
| frontend/src/main.tsx:7 | 除 /reports/{report_id} 外统一渲染 App | 工作台没有 workflow 路由或独立工作流选择 |
| frontend/src/App.tsx:14 | localStorage insightflow.session 只存当前 Session ID | 刷新恢复的是 Session 单分析状态，不是同一 Session 的某 Workflow |
| App.tsx:17,49,76 | 一个 Session 对象；同 ID 用 revision 防旧响应；轮询 /sessions/{id} | Session 内换 Workflow 时，当前逻辑无法区分同 Session 不同工作流回调 |
| App.tsx:112,119 | 新分析清空当前 Session，提交创建新 Session；澄清才继续同一 Session | 目前产品流程确实是一咨询一工作流 |
| SessionSidebar | 历史每项是 SessionSummary，selectedId=Session.id | 并非同 Session 多工作流列表 |
| api/client.ts:74 | 审批幂等键 insightflow.approval.{session.id}.{plan_version} | 同 Session 两计划若各有 v1，键冲突；还未含 plan_id |
| api/client.ts:85 | 执行幂等键 insightflow.execution.{session.id}.{plan_version} | 同上；后端 request_id 冲突检查会拒绝，不会自动正确选择 |
| MessageList.tsx:25 | 展示 Session 唯一 review_plan；遍历其全部 engine_execution_ids | 若强行复用 Session，会混放多工作流结果，未按 workflow 分组 |
| workflow/presentation.ts:6 | 当前批准版本 + 最后接受 execution ID 决定报告活动 | 适用于当前单流程约束；多 Workflow 下不能直接复用 |
| ReportGenerationCard | 按 execution_id 重试、report_id 跳转 | 比 Session 最新结果安全，可继续复用，但需要明确所属业务分支 |
| reporting/ReportPage.tsx | 独立 report_id 页面、保存报告与显式结果引用 | 本身不把 Session ID 当 report ID |

访问权限也是 Session 范围：`api/session_access.py` 从执行表或报告 audit 解析所属 session_id，再查 session_access；前端 `api/client.ts:10` 等从 insightflow.access.{session_id} 取 token。当前 Session 是本地能力凭证边界，不是用户账户或租户身份。如果未来一个 Session 包含多个 Workflow，这些工作流默认会共享该凭证权限；不能把归属键更名当作已经实现隔离。

## 6. CAS、旧版本回调与 Report 兼容性复核

本轮重新执行 REQ-0072 的临时 SQLite 复现，确认问题仍在，未被近期配置/UI 修改修复：

- `storage/trace_repository.py:60` update_run **没有真正 CAS**，只是 SELECT 后比较 business_revision，再无条件 UPDATE。并发时 revision=20 可被 revision=10 覆盖；同 revision 旧对象也可覆盖较新状态。
- business_revision 来源是 Session.revision，不是独立 Workflow/节点版本。即使以后加工作流选择，仍需先解决原子更新与回调接受条件；改归属 ID 不会自动修复此竞争。
- `observability/workflow.py:60` checkpoint 先写事件再更新 Root，低 revision 更新被忽略时，事件仍保留。必须区分历史回调与已接受状态，不靠最后一条事件推断当前进度。
- `storage/report_repository.py:66` finish 正确拒绝旧 attempt，但返回值不区分已保存和被忽略；`workflow/reporting.py:52` 随后仍可记录 persistence 完成与 trace.finish。部分恢复且旧工作者返回时，旧 Report Trace complete、报告却未保存的问题仍可复现。
- 同时恢复业务与 Trace 的负对照仍保护旧终态：旧 Report Trace interrupted，新 attempt queued。因此不能声称普通完整重启必然产生假成功。
- ReportGeneration 以 execution_id 隔离，Report Trace 以 execution_id+attempt 隔离，本身没有按 Session 覆盖“最新报告”。不应为了去除 Session 假设而删除或重建历史 Report Run。

复现文件：root-recheck.json、report-stale-recheck.json。脚本为原审查保留的 probe.py 与 report-stale-probe-v2.py，读取当前代码，所有业务写入仅在临时目录。实际生产 Session/Trace/报告未改写。

## 7. 兼容性判断及后续设计前置条件

### 已可复用

精确 dataset/version、plan_id、approval_id、execution_id、report_id；不可变批准/计划快照；独立报告 ID 路由；按 execution 处理报告；Run/Span/Event 与 LLMCallRecord 引用。这些都不需要新增 Trace 层级或独立 Attempt 实体。

### 不能直接兼容同 Session 多工作流

Session 唯一 Root 索引；PlanVersion 的 Session 版本命名空间；Session 单一当前状态/计划/批准；只接受 session_id 的工作流与 Lifecycle 查询；前端当前 Session、缓存和幂等键；Session 范围权限。不能只增加一个可空 workflow_id 后宣称改造完成。

### 最小设计前置项（未实施）

1. 明确 Session 是否继续等价于一次分析，还是将变成聊天容器；明确业务 Workflow 身份与观测 Root run_id 的关系及 Trace 缺失策略。
2. 为“当前计划、批准、执行和报告”定义显式工作流归属与分支选择规则；保留旧 Session 单流程映射，旧历史缺失字段标明来源，不能按当前配置伪造。
3. 明确旧 API 的默认解析语义。若仍按 Session 查询，存在多个候选时必须要求选择或返回歧义，不能静默取最近成功结果。
4. 单独修复原子 Trace 更新与 stale report persistence 接受结果；不要借身份迁移放宽 Report 终态保护。
5. 保持 Workflow Root + Node Span 两层。重试仍用已有 Node Span.node_attempt、调用序号和业务版本；不新增第三层节点或独立 Attempt 实体。历史 Report 独立 Run 只做显式兼容处理，不能伪装成新第三层。

本轮停止于兼容性审计，没有选择或实施上述方案。

## 8. 验证与保留

- 后端相关回归：167 passed，1 个 Starlette TestClient 弃用 warning，backend-regression.txt。
- 前端：9 文件、67 tests passed，frontend-regression.txt。
- Root 并发与报告迟到回调临时复现均保存；没有真实外部模型调用或前台提交。
- source-before.json 与 source-verification.json 用于核对 backend/app、backend/tests、frontend/src、admin/src 未变化。仅新增需求/审计记录及测试输出，未修改业务源码、Schema、迁移、服务配置或 UI。
- 扫描范围为当前仓库运行源码与现有 API；未声称穷尽未知外部调用方、历史部署或未接入脚本的契约依赖。
