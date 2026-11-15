# Workflow Identity Bootstrap V1 交付报告

需求：REQ-0084。日期：2026-10-31。范围：现有 Session 单流程的准备阶段身份登记与四节点 Trace 关联；不进行 Workflow Switch。

## 1. 审计结论与最小实现

既有 Phase 02 Expand SQL 已包含 `business_workflows`、`session_messages`、`session_datasets`、`trace_workflow_links`，以及身份不可变、Root 唯一、创建幂等、同 Session 归属等约束。但之前没有生产 Workflow 创建器，只有只读 Reader。旧 `register_root()` 自行生成 Root，`preparation_context()` 按 Session 查 Root。Profiler、Intent、Planner 已有真实 Span；Validator 已在 Planner 输出和保存前分别校验，不新增第三个重复包装。

本轮复用上述表及现有 `apply_expand()`，新增最小身份写入 Repository，不引入第二套身份表或状态机。所有既有迁移 SQL、Engine、Reporting、HITL、Prompt 和 Admin 源码保持不变。代码差异见 `runtime.patch`；修改前后源码见 `before.zip`、`after.zip` 及对应哈希清单。

## 2. 修改文件与接口

| 文件 | 入口 | 变化 |
| --- | --- | --- |
| `backend/app/storage/workflow_identity.py` | `WorkflowIdentityRepository.create/resolve/require_unregistered` | 新增原子登记、幂等重放和严格身份核验；`WorkflowIdentity` 为不可变准备上下文 |
| `backend/app/domain/models.py:137` | `SessionState` | 增加可空 `workflow_id/root_run_id`，旧 JSON 兼容；权威身份保存在业务表 |
| `backend/app/main.py:41` | `create_app` | 复用幂等 Expand 校验并注入身份 Repository；默认启用。`bootstrap_identity=False` 仅用于构造原始 pre-Expand 兼容测试/嵌入场景，没有 HTTP 或环境变量开关 |
| `backend/app/api/routes.py` | `create_session/clarify_intent/retry_preparation` | 新真实 Session 使用原子登记；后台任务显式携带身份；路由和审批/执行契约不变 |
| `backend/app/workflow/orchestrator.py:45` | `create_real_session/identity/trace_created/prepare_real` | 校验业务登记，启动前幂等修复物理 Root，准备上下文携带明确身份 |
| `backend/app/observability/workflow.py:11` | `register_root/preparation_context` | 使用预留 ID 创建或精确读取 Root；新路径不调用 `workflow(session_id)` 推断 Root |
| `backend/app/storage/trace_repository.py:55` | `create_registered_root` | Root 与 Trace Link 在同一 Trace 事务提交；校验保留 ID、Session、Workflow；拒绝静默替换 |
| `backend/app/observability/recorder.py:54` | `SpanHandle` | 仅显式绑定的新准备 Trace 使用平铺 node_key 和直接 Root 归属；保留 Report/旧嵌套记录读取行为 |

测试新增 `backend/tests/test_workflow_identity_bootstrap.py`；更新 `test_workflow_trace_v031.py` 的新平铺期望和故障注入入口；`test_trace_write_safety.py` 的延迟测试替身接收显式上下文；`test_workflow_expand.py` 明确构造旧版无 Bootstrap 环境，继续验证原始迁移前后不变量，没有放宽数据库约束测试。

## 3. 原子性、幂等与传播

业务数据库 `BEGIN IMMEDIATE` 内一次提交：

1. 创建 Session，并保存明确 `workflow_id/root_run_id`。
2. 登记真实上传文件 manifest（仅 FileInfo，不伪造 DatasetProfile），关联 Session 数据集。
3. 保存初始用户消息，创建 Workflow 并绑定 origin message。
4. 保存预留 Root、创建请求 ID 和创建载荷 SHA-256。

同 Session、同创建请求、同载荷返回既有 Session，包括现有检查点，不清空状态。同请求不同载荷、不同幂等键、多个候选、归属不符均拒绝。并发创建由 SQLite 写事务串行化。Workflow 与 Root 由已有不可变触发器保护；保留旧 Session 唯一 Root 索引。

创建幂等键为服务端 `prepare:<session_id>`。**这是同一已分配 Session 的创建幂等，不是跨两次 HTTP 上传去重**。不同上传仍创建不同 Session，不引入新的全局上传请求表。

后台准备、澄清、失败重试均传递 `WorkflowIdentity(session_id, workflow_id, root_run_id)`，并与业务记录校验。Session 查询只用于核验明确身份及排除多候选，不用于选取 Root。新 Trace 通过精确 `root_run_id` 获取。测试禁止调用旧 `workflow(session_id)`，仍可完成新准备流程。

本轮 `business_workflows.control_status` 保持身份登记时 `CREATED`，`control_context` 明确 `authority=session, scope=identity_only`；不作为生命周期状态权威或当前进度显示来源。SessionState 仍控制所有业务状态。未写入 WorkflowPlanVersion、审批/执行/报告链接，不进入后续事实迁移阶段。

## 4. Fail-open 与历史边界

Trace 创建、链接、事件和 Span 写入均复用 TraceRecorder fail-open。物理 Root 与链接写入失败不回滚已提交业务身份，也不阻止真实分析准备。下一次准备入口自动重试 `trace_created`，也可显式调用该幂等修复方法。已有 Root 不改写 Manifest；补链使用同一预留 ID。

若直到准备结束仍未采集到 Root，之后修复只登记身份，标记 `integrity=incomplete`，保持未观测状态，不补造已完成 Span，也不填充当前 Prompt/模型配置冒充历史调用。未执行的节点没有 Span。

历史无显式身份的 Session 不自动创建 Workflow、不改写旧 Root、不制造历史执行事件；已有 Trace 仍可兼容查询。若业务表已登记但 Session 丢失显式身份，则拒绝，不退回 Session 推断。新注册流程重入沿用同一 Root；真实节点重试由现有原子 Span 预留机制递增 `node_attempt`。LLM HTTP 重试继续使用已有调用记录，不新增 Attempt 实体。

既有 native Workflow Schema 要求非空 goal。本轮空需求返回明确 `ANALYSIS_GOAL_REQUIRED`（422）且回滚 Session/移除上传文件，不虚构目标或留下部分身份。这是输入边界收紧：原入口允许先创建 Session 再由 Parser 处理失败；此处明确披露，不将其描述为完全相同的空输入行为。

## 5. 真实 CSV、真实模型与持久化证据

通过 FastAPI TestClient 发起真实上传 API，使用已有销售 CSV、真实磁盘存储及真实网络 Provider；没有 Mock transport。不是浏览器操作验收，也没有连接主运行目录的 UI 展示。验证数据库隔离保留在：

`var/verification/identity-bootstrap-v1-release/`

用户问题：帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。

| 证据 | 实际值 |
| --- | --- |
| Session | `785cb72f289d4e49b786af59b8b0ba69` |
| Workflow | `wf_10208b7d772a4f9397b495e6b6ef1069` |
| 预留且实际持久化的 Root | `run_5826443004884409a998d7acf0e6055e` |
| 模型 | 已配置的 `qwen3.8-flash`，模型参数未改 |
| Profiler 行数 | 60 |
| Session 结果 | `AWAITING_APPROVAL` |
| Root 观测状态 | `waiting_approval` |
| 准备总耗时 | 9.647 秒 |
| 模型调用 | Intent、Planner 各一条真实 succeeded 调用，均绑定该 Root 和实际节点 Span |

| 实际节点 | attempt | 状态 | 耗时 ms |
| --- | --- | --- | --- |
| data_profiler | 1 | complete | 6.82 |
| intent_parser | 1 | complete | 3520.29 |
| analysis_planner | 1 | complete | 5890.15 |
| plan_validator：planner_output | 1 | complete | 5.65 |
| plan_validator：initial_plan_save | 2 | complete | 4.09 |

四类节点共 **5 个真实 Span**：Validator 在两个实际调用点执行，并非埋点重复。全部 `parent_span_id=null`，`run_id` 等于上述 Root，属性含明确 Workflow/Root ID，稳定 node_key 不再拼接父节点身份。未批准，未执行 Engine，未生成 Report。

`live-preparation-release.json` 保存真实结果及校验计划；`live-release-readback-verified.json` 是独立只读数据库核验，检查唯一业务身份、链接、Root Manifest、5 个不同节点/attempt、2 条精确关联调用、外键完整性及未执行分析。`verify-release.py` 可重复读取验证，无额外 LLM 调用。原始模型请求快照继续保存在隔离 Registry 数据库，不把完整上传数据或密钥复制到公开文档。

保留首轮网络受限失败记录 `live-preparation-network-failed.json`：返回真实 `LLM_UNAVAILABLE`，未用 Mock 掩盖。中间一次真实成功运行也保留；其验证脚本错误地纳入同库前次调用而断言失败，见 `live-intermediate-script-failure.log`。最终验证按 Root 过滤，并在独立目录重新执行成功；不删除这些失败记录。

## 6. 自动化与兼容性结果

- 新身份专项：**11 passed**。覆盖原子创建、相同请求重放、不同请求/载荷冲突、8 路并发创建、事务回滚、不可变身份、多候选、缺失显式身份、错误上下文、Root 缺失修复、Trace DB 故障、旧 Span 保留和重启读取。部分测试组合多个断言。
- 最终后端完整回归：**1434 passed**，58.67 秒。包括准备流程、澄清恢复、模型重试/超时/Schema 失败、Root CAS、旧回调隔离、Report stale commit、Lifecycle Read Model 及 Expand 迁移约束。
- 用户端：**67 passed**；Admin：**78 passed**。二者构建通过。
- 一条既有依赖警告：Starlette TestClient 的 httpx 适配弃用提示；未顺带升级依赖。
- 初次完整回归失败结果保留 `regression-first-failures.log`：旧测试的 pre-Expand fixture 被新默认初始化提前 Expand，以及旧延迟替身参数不兼容。修正测试构造与显式调用参数后，原有约束、旧回调断言继续全部成立。
- 没有新增迁移 SQL 或新表定义，复用已冻结 Expand。隔离验证库使用新目录；既有主运行库迁移已应用，启动幂等校验不回填业务数据。没有直接复制运行中 SQLite 文件充当一致性备份。

## 7. 剩余限制与停止点

1. 不开放一个 Session 的第二个 Workflow；多 Workflow 创建、事实归属迁移和状态权威 Switch 均未实施。
2. 旧 Session 不做自动身份回填；缺失旧身份/旧观测仍明确不可用。
3. Trace 长时间故障期间的事件不会重建。业务检查点可恢复，但不能恢复未持久化观测。
4. 本轮 Root 仍只覆盖准备阶段；Engine、HITL、Reporting 业务逻辑及旧 Report Run 保持原状，不宣称已经完成全流程统一埋点。
5. 没有新增常驻 Root 修复调度器或管理 UI；修复由准备入口或显式幂等方法触发。
6. 新业务库启动复用 Expand；若 Schema 不匹配会明确失败，不能通过删表或重新计算旧校验和绕过。旧版本程序不应在新身份登记启用后并行执行写入。

身份 Bootstrap 与真实四节点链路已具备可核验结果。本轮停止，等待验收，不自动开始下一阶段。
