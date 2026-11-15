# Lifecycle Instrumentation Vertical Slice 02：HITL 接入与下游阻断报告

需求：REQ-0085，关联 REQ-0084。日期：2026-10-31。

**交付结论：部分实施，不满足完整 Vertical Slice 02 验收。** 已接通可核验的 HITL；按照任务书“缺少必要 fencing 时停止该路径”的要求，没有将 Engine 或 Reporting 新接入 Workflow Root，没有为受阻节点创建 Span，也没有为了完成演示改动业务成功标准。

## 1. 实施前审计

| 路径 | 已有事实与真实入口 | 接入决定 |
| --- | --- | --- |
| 身份 | `WorkflowIdentityRepository.resolve` 校验 Session 的明确 `workflow_id/root_run_id`、唯一业务登记、源文件；Root 按预留 ID 查询。见 `backend/app/storage/workflow_identity.py:86`、`backend/app/observability/workflow.py:47` | 复用，不新增身份系统 |
| HITL | `PlanReviewService.approve_v1/revise_v1`；`PlanReviewRepository.transaction` 使用 `BEGIN IMMEDIATE`，审批、计划版本和 Session 更新在同一业务事务。审批请求有精确版本、数据集、validation、revision、幂等检查，成功后可读取不可变记录。见 `backend/app/services/plan_review.py`、`backend/app/storage/plan_review_repository.py:29` | 接入实际动作，不创建等待 Span |
| Engine | `AnalysisEngineService.execute` 的 `ExecutionRepository.claim` 在锁内重验批准快照及 revision，保存 execution request、Approval 和 Session；TaskRunner 和结果持久化真实存在。见 `backend/app/services/analysis_engine.py:99`、`backend/app/storage/execution_repository.py:40` | claim 有保护，但 finish 还不满足本轮当前分支 fencing；停止接入 |
| Engine 结束 | `ExecutionRepository.finish` 只检查执行行仍 running；更新 Session 的条件只是 Session.status=RUNNING。未核对当前执行 ID、当前 PlanVersion、revision/active key。见 `backend/app/storage/execution_repository.py:86` | B01 阻断 |
| Reporting | `ReportWorkflow.enqueue/generate` 精确读取保存的 Execution 与其不可变 Approval；校验 execution/approval/plan/dataset 引用，而非直接使用“最新计划”替代历史快照。见 `backend/app/workflow/reporting.py:13`、`:28` | 保留原行为，不把旧执行报告误当成当前分支交付 |
| Report 提交 | `ReportRepository.finish` 在同一事务保存 Report、当前 Generation、Session；检查 execution_id 对应的 attempt 和 queued/generating 状态。见 `backend/app/storage/report_repository.py:65`、`:84` | 已有 attempt 防护成立；缺少 Workflow 当前分支授权及 C19 提交凭证，B02 阻断 |
| Report Trace | 当前 `report_persistence` 包装真实提交，accepted=False 抛出 stale callback，不记录 complete；既有独立 Report Run 及 stale callback 测试有效。见 `backend/app/workflow/reporting.py:52` | 不退化既有保护，不等同已实现 C19-A/B |
| Workflow Root | `TraceRepository.update_run` 对 workflow 类型仅支持准备阶段转换；`waiting_approval` 无出边，workflow.complete/partial 被拒绝。见 `backend/app/storage/trace_repository.py:89` | B04 阻断，不能将报告 Trace 的状态规则直接用于 Workflow Root |
| Plan 引用 | Bootstrap 只登记身份；旧 PlanVersion 真实主键为 `(session_id, plan_version)`。没有运行时物化的 WorkflowPlanVersion ID 和后续归属链接 | 不制造 plan_version_id；B05 归属/契约缺口 |

`audit.json` 提供结构化审计结论。上述源文件的实施前完整内容已存入 `before.zip`，可以区分审计时事实与本轮新增的观测代码。

## 2. 最小阻断与证据

### B01：Engine 完成回调未绑定精确当前分支

已有 claim revision 检查不能替代 finish 时的 fence。新增隔离测试 `test_engine_finish_fencing_gap_is_reproducible_in_isolated_state`：真实构造已批准计划并 claim；通过测试 fixture 模拟 Session 分支漂移，再调用原始 `finish`，旧执行仍可更新状态。测试使用临时数据库，未改生产数据。

这是**原始写入函数在合成分支漂移下的真实行为**，不是宣称普通用户可通过现有 API 任意切换运行中计划。当前单流程业务入口已有额外限制；风险在于不能据此为全流程 Root 提供目标级旧回调保证。

### B02/B03：不能把 accepted 布尔值当作完整 C19-B 凭证

冻结契约 `docs/designs/lifecycle-contract-v1.2-2026-10-31/README.md` 的第 2–5 节要求：

- C19-A 在真实事务前/事务内核对 Workflow、精确当前分支、revision、active key、attempt 与幂等信息。
- 事务原子保存 Report、Generation、Workflow 归属和可恢复的提交元数据。
- C19-B 从持久事实核验提交与精确 persistence_span_id；即使业务提交成功后未返回 accepted，也不能误判业务提交失败。

现有 Report 保存与 attempt 防护是实装能力，但没有这些 Workflow 归属链接及授权/提交 token、提交请求载荷摘要和精确 Span 绑定。纯 Policy Validator 已有 C19-A/B 设计与测试，尚未接入真实 Writer。不能用一次 `accepted=True` 冒充完整冻结契约，也不能关闭校验来接入 Root。

隔离测试 `test_report_attempt_guard_does_not_fence_changed_plan` 验证：当前 attempt/status 满足时，模拟 Session 计划漂移后，原始 Generation 提交函数仍接受写入。该测试只验证现有提交 guard 的边界，不把旧执行生成历史报告的兼容能力误报为非法行为。

原有 `test_immutable_execution_snapshot_used_if_latest_session_plan_changes` 仍通过：旧执行的历史报告本来就可以读取其批准快照。未来 native Root 接入必须区分“合法历史报告保存”和“允许完成当前分支”，不能直接删除这种 legacy 能力。

### B04：Root 仍是准备阶段状态机

物理枚举里存在 complete/partial 不表示 workflow 类型的更新规则允许这些状态。本轮未改变 Root 转换或 CAS。HITL 的动作 Span 可以直接归属已登记 Root，但 Root.status 仍是旧准备检查点；不能把它展示为全流程当前业务状态。

### B05/B06：缺失能力保持缺失

- 没有物化 WorkflowPlanVersion 时，使用真实旧主键 `session_id + plan_version` 和 plan_id 等业务引用，不伪造新 UUID。
- 没有用户“拒绝整个方案”的业务入口或不可变拒绝事实；本轮 `hitl.denied` 表示真实审批请求被服务端拒绝，**不是用户拒绝方案**。未新增拒绝 API。

## 3. 实际实现

| 文件 | 修改 |
| --- | --- |
| `backend/app/observability/hitl.py`（新增） | `HITLObserver.perform` 仅包裹真实服务动作；使用显式登记身份和已有 Root；事后核验不可变提交；所有观测 IO fail-open |
| `backend/app/services/plan_review.py` | `approve_v1/revise_v1` 接入观测装饰器；原幂等返回分支只标记一个进程内 receipt，用于区分 replay；不写额外业务状态，不改变授权条件和事务 |
| `backend/app/services/plan_review.py:validate_v1` | 复用既有 Validator Span，不重复包装；观测角色在 HITL 中标为 `hitl_approve/hitl_revise`，准备阶段仍是原标签 |
| `backend/app/observability/recorder.py` | 增加 `approval_id/command/outcome` 安全白名单，不保存分析原文或完整数据 |
| `backend/app/main.py` | 注入 HITLObserver，legacy pre-Expand fixture 继续可用 |
| `backend/tests/test_vertical_slice02_hitl.py`（新增） | HITL 行为、并发重放、观测故障、提交核验故障和两个原始提交 guard 的隔离复现 |

最终差异为 `changes-release.patch`；最终源码包为 `after-release.zip` 和 `after-release.json`。早期 `changes.patch/after.zip` 保留为本轮中间快照，后者尚未校正审批内 Validator 的观测角色，不冒充最终版本。

### HITL Span 和 Event

- 仅真实 approve/revise 请求开始时创建 `node_key=hitl`，直接挂 Root；空等候期间不创建长期运行 Span。
- 每次真实调用，包括幂等重放，分配新的 Span 和原子 `node_attempt`；重放不新增 Approval。
- `hitl.approved`：服务事务已退出、精确 PlanVersion 与 Approval 已从业务库核验。
- `hitl.replayed`：原有幂等分支实际命中，且提交事实可核验；不是通过时间或“调用前是否存在记录”推测。并发重放使用 ContextVar 隔离 receipt。
- `hitl.revised`：新版本已保存并重新校验，关联实际版本，不新增审批事实。
- `hitl.denied`：实际 AppError，例如 PLAN_VERSION_MISMATCH、STALE_SESSION、APPROVAL_REQUEST_CONFLICT；Span failed 并保存安全错误代码。
- `hitl.failed`：真实非业务异常；原异常原样传播，不由 Trace 修改业务决定。
- post-commit 观测核验失败：业务结果保持不变，Span 不伪装 complete，使用 `TRACE_COMMIT_UNVERIFIED` 标记观测失败。

Trace Root 缺失、身份观测不明或 Trace DB 故障时不推断 Root，不阻止原审批，也不补造历史 Span。没有新增表、迁移或 API。身份、Policy、Prompt、模型参数、Engine、Reporting、Admin 源码不变。

## 4. 最终真实运行：准备与 HITL

使用真实上传 API、真实 60 行 `insightflow_sales_orders_test.csv` 和已有 qwen3.8-flash Provider；网络调用不是 Mock。测试通过 FastAPI TestClient 发起，不宣称浏览器端到端已完成。

持久化目录：`var/verification/vertical-slice02-hitl-release/`。本次没有写入主用户测试会话或修改历史 Trace。

| 项目 | 真实值 |
| --- | --- |
| Session | `37fb29be79074d81844108f4ded6cb7f` |
| Workflow | `wf_9633a95ead3d48d2aa707d48d513822c` |
| Root | `run_5cfdf3c072ee4f5ca7ccba2938a09c54` |
| 数据 | 60 行，实际 CSV 内容摘要见 JSON |
| 准备耗时 | 10.717 秒 |
| 准备 + 首次审批 + 重放总耗时 | 10.758 秒 |
| HITL 首次审批 Span | complete，约 17.80 ms，outcome=approved |
| HITL 重放 Span | complete，约 5.60 ms，outcome=replayed |
| 业务结果 | Session=APPROVED；只有一条不可变 Approval |
| 节点与调用 | 同一个 Root 下 8 个真实直接 Span；Intent/Planner 两条 succeeded LLMCallRecord |
| Engine/Generation | 0 / 0；受阻路径未执行 |
| Root 状态 | 保留 preparation 的 waiting_approval，未伪造全生命周期状态 |

8 个 Span 包括：Profiler、Intent、Planner、准备阶段两次真实 Validator、审批期间一次真实 Validator、一次批准动作、一次实际重放动作。每个 Span 有不同 span_id；真实重复请求不是重复业务提交。

`live-preparation-hitl-release.json` 保存业务记录、事件、Span、Approval 和调用关联；`live-release-readback.json` 是独立只读数据库核验结果。`live-script.py/live-preparation-hitl.json/live-readback.json` 保留首次真实运行；最终 release 文件另外保存，没有覆盖先前数据。原始请求仍由 Registry 权限和保留策略控制，没有复制 .env、密钥、Session access token 或完整 CSV 到报告。

**本轮没有执行“审批后 Engine → 报告交付”的真实验收，因为这样做不能证明缺失的 fencing 已成立。** 即使旧路径可以生成报告，也不能借旧独立 Report Run 宣称它已接入当前 Workflow Root。

## 5. 测试与兼容性

- 新增专项 9 项：真实提交与 replay/denial、计划删除与重新验证、3 类 Trace 写入故障、提交证明读取失败、并发重放隔离、Engine 分支 drift 复现、Report 分支 drift 复现。
- 后端完整测试：最终 **1443 passed**。完整日志 `backend-release-tests.log`；原始一轮完整测试也保留为 `backend-tests.log`。
- Frontend：**67 passed**；Admin：**78 passed**；两者构建通过，源码未改。
- 原有 Engine partial_success、单任务失败隔离、Report failure/retry、无证据 unavailable、旧 Planner 回调、Report accepted/stale callback、Root CAS 和 Lifecycle Read Model 测试全部作为兼容回归通过。
- 这些旧测试验证的是原有业务/Report Trace 行为，不能替代“Engine/Reporting 已接入同一 Root”的验收。
- 原有 Starlette/httpx 弃用警告继续存在，未升级无关依赖。

## 6. 未完成节点与下一步准入

| 项目 | 状态 |
| --- | --- |
| Data Profiler / Intent / Planner / Validator | 复用 REQ-0084 实现，回归通过 |
| HITL approve/revise/replay/denied | 已接入并真实验证 |
| 用户主动拒绝方案 | 无业务入口，未开发、不伪造 |
| Engine Root Span、结果映射、中断与重试 Root 关联 | 停止接入：B01、B05 |
| Reporting 子节点迁入 Root、Chart Builder 观测、持久化 C19-A/B | 停止接入：B02、B03、B04、B05；原独立 Report Run 不变 |
| 全 Workflow Root 生命周期 | 未实施，当前仍是准备阶段 Root 状态契约 |
| 进程硬中断后 HITL 孤立 running Span 的恢复 | 未增加新的恢复扫描器；现有 Trace recover 主要覆盖 queued/running Root，等待 Root 下的动作观测可能留下缺口，不能推断完成 |

最小后续工作应先明确单流程下当前 execution/plan 的提交 fence 与持久关联，再使 Report Writer 原子保存授权/提交证据，增加提交成功但返回前崩溃的事实恢复验证；最后扩展 Root 的合法转换并保留 CAS。此方案不必切换 Session 权威，但属于业务提交与观测契约的独立修复，不能在本轮以埋点名义悄然实施。

本轮到此停止，等待对部分交付与阻断项的评审，不自动进行 Writer 修复或 Workflow Switch。
