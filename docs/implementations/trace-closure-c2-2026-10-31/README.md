# Phase 03-C2 — End-to-End Trace Closure

需求：REQ-0087，承接 REQ-0084、REQ-0085、REQ-0086。日期：2026-10-31。

## 验收结论

**Completed：正式真实运行 03 已通过 workflow_id 查询完整执行链，且业务归属、既有 WorkflowReader、LLM 调用、持久提交凭证与 Trace 一致。** 判断依据是实际业务 API 链路与重启后的查询，不是测试数量或文档完成。

- Workflow：`wf_65b741d8c88b45a2940abace3c8f92e5`
- Root：`run_15c55fbf4a624e3c8ff4eb2c07abb526`
- Approval：`approval_1404ce3086f44124bfd7c0aee4f45b29`
- Execution：`exec_1739e70a5bd6468eb9ed55005379e3e2`
- ReportGeneration attempt：`1`，状态 `completed`
- Report：`report_4d0455e523c645d99660ed61467dfc1e`，状态 `complete`
- 14 个实际直接 Root Span，3 条真实 qwen3.8-flash 调用；collection=`observed`，gaps=[]。
- 从上传到报告保存耗时 **16.411 秒**，没有修改 Prompt 或模型参数。

证据：`real-run-03.json`、`real-acceptance-03.json`、`acceptance-final-readback-03.json`。后者包含最终只读查询、旧 Reader 交叉校验、重启后相同 Span ID 核对和外键校验。

**Completed 是本阶段可观测性验收结论，不代表已切换 Workflow 状态权威。** Root.status 继续保留准备阶段检查点；查询中明确返回 `root_observation_scope=preparation_checkpoint_not_business_lifecycle`。Session、Execution、ReportGeneration、Report 仍分别提供原有业务事实，不能将旧 Root.status 直接当作全流程生命周期。本轮不开发 Admin 时间线。

## 1. 新增只读入口

```text
GET /admin/workflow-traces/{workflow_id}
GET /api/v1/admin/workflow-traces/{workflow_id}
```

复用既有 Admin 只读认证及本机测试权限，没有新增公开敏感数据入口。服务为 `backend/app/services/workflow_trace.py:WorkflowTraceService.get`，路由为 `backend/app/api/admin.py`。

输入必须是真实登记的 Workflow ID。精确读取 business_workflows.root_run_id，并核对 Session 的显式身份及 Root Manifest。不会按 Session 最近时间选择 Root、执行或报告。

响应包含：workflow/root/session ID、实际节点和 Event、已登记 PlanVersion/Approval/Execution/Report 关联、ReportGeneration 当前 attempt、报告提交凭证、LLMCallRecord、保留的 Report artifact Run、collection gaps。节点来自实际持久化 Span，不按模板拼接时间线。

业务归属首先从精确链接表读取，再复用既有 WorkflowReader 的不可变 Schema、引用和快照哈希规则交叉验证。不放宽旧 Reader 以容忍错误哈希。历史缺少明确归属时返回 gap 或明确错误，不把 Session 的最新记录收编到 Workflow。

本次正式运行位于隔离验收库 `var/verification/c2-closure-release03/`，**不在默认 var 根业务库**。若手工启动服务查询该 ID，应将数据目录配置到这个验收目录。自动化验收通过 FastAPI TestClient 调用现有业务 API；模型 HTTP 请求真实发送到已有服务，不宣称做过浏览器端到端操作。

## 2. 实际链路与节点

实际调用链：

```text
POST /api/v1/sessions（真实 CSV/LLM）
准备阶段原有 Profiler / Intent / Planner / Validator
POST /api/v1/sessions/{session_id}/approvals（真实批准事务）
POST /api/v1/executions（真实 claim 与受控计算）
ReportWorkflow.enqueue / generate
Evidence / Chart / Insight / Fact Validation / Assembly / Persistence
GET /admin/workflow-traces/{workflow_id}
```

准备阶段和 HITL 原有包装保持复用。新增 Engine 包装在真实 claim 后开始，结果成功持久化后核验结束。Report 使用既有节点包装，只补 Chart Builder 的真实调用观测，不叠加一个重复 Reporting 计算器。

| 实际节点 | attempt | 状态 | 耗时 ms |
| --- | ---: | --- | ---: |
| Data Profiler | 1 | complete | 5.86 |
| Intent Parser | 1 | complete | 2802.21 |
| Analysis Planner | 1 | complete | 6740.22 |
| Plan Validator：planner_output | 1 | complete | 4.38 |
| Plan Validator：initial_plan_save | 2 | complete | 3.59 |
| HITL 审批 | 1 | complete | 20.05 |
| Plan Validator：hitl_approve | 3 | complete | 2.32 |
| Analysis Engine | 1 | complete | 8.70 |
| Evidence Builder | 1 | complete | 2.41 |
| Chart Builder | 1 | complete | 1.32 |
| Insight Generator | 1 | complete | 6494.63 |
| Fact Validator | 1 | complete | 10.32 |
| Report Assembler | 1 | complete | 2.47 |
| Report Persistence | 1 | complete | 7.72 |

三个 Validator Span 对应三个真实调用点，不是重复包装。HITL 的 wall time 包含其审批内校验，因此所有节点耗时不能简单相加作为总耗时。`nodes-and-calls-03.md` 提供逐节点 span_id、实际结果引用及模型调用关联。

无 Evidence 时，新的 Root 路径只记录 `report.node_skipped` 决策事件，不创建未执行的 Insight Generator/Fact Validator Span。失败前没有执行到的组装或保存节点也不会创建。历史旧式 skipped Span 兼容读取，不回写历史。

## 3. 业务关联与最小提交保护

### 3.1 复用现有表，不新建身份或 Attempt 系统

复用 Phase 02 的 workflow_plan_versions、workflow_approval_links、workflow_execution_links、workflow_report_links，以及既有业务表。没有新建表、删除约束或修改冻结迁移 SQL。

- PlanVersion 原主键、原不可变载荷不变；新链接使用既有 legacy_ref 格式精确引用当前旧表。这是存储引用类型，不冒充历史部署版本。
- 新审批与 PlanVersion/Approval 归属链接在原 HITL 事务内提交。
- 首次绑定时固定 Workflow Dataset 版本；Workflow.control_status 不参与业务授权，不成为第二套状态机。
- Execution claim 与 execution link、dispatch_key 在原 claim 事务提交。dispatch_key 绑定 execution_id 和 claim 后的 Session revision。
- 新报告与 Generation、Session 镜像、report link、commit_receipt 在原报告事务原子提交。
- ReportGeneration 只增加可空 JSON 字段 workflow_binding，保存当前 attempt 的授权快照；没有新增 Attempt 实体或 ReportGeneration 历史表。

对前一版已批准但尚未执行的 Session，在首次真实 claim 内核对原不可变 Approval，按 legacy_ref 登记引用；不重新批准、不伪造旧 Span。缺少新 execution link 的既有历史执行仍走原报告兼容路径，不强行回填归属。

### 3.2 Engine fencing

`backend/app/storage/execution_repository.py:ExecutionRepository.finish` 在现有锁内检查不可变审批/计划/数据版本、当前 execution ID、当前 PlanVersion、登记 Workflow、Session control 和 claim revision token。过期执行拒绝修改当前分支。

恢复时保留已保存任务与历史 ExecutionResult；若执行已过时，只结束其历史记录，不修改新 Session 分支。不实现 Engine Resume 或自动重算。

### 3.3 Report 提交与持久事实核验

当前 Session 单流程采用以下顺序：

1. queue/start 保存 Workflow/Root、Execution、PlanVersion、Approval、Dataset、attempt、branch hash、active key、提交键和 authorized_revision。
2. finish 在同一业务事务内核对当前 attempt、状态、Session revision 和分支指纹，拒绝旧 revision/旧执行/旧 attempt。
3. 原子保存 Report、Generation、归属链接和不可变 audit.commit_receipt。
4. `ReportRepository.committed` 在一致业务读快照中核对已提交的 Generation/Report/link/摘要、提交 token 和精确 persistence_span_id。
5. 持久事实核验成立后，才结束对应实际 Report Persistence Span。

receipt 明确 `revision_authority=session_single_flow`。这是现有 Session 路径的最小提交适配；冻结 Workflow Policy 未接入生产授权，也不宣称已实现未来 Workflow 状态权威迁移。

业务提交成功但返回值丢失时，会从持久事实核验成功，不因异常直接写成失败。若进程真正中断，重启后已提交报告保持 completed；对应观测可保持 interrupted/collection gap，不伪造旧 Span complete。Trace 不参与业务事务，Span 未采集时 persistence_span_id 允许为空，报告仍可保存。

## 4. Trace 与兼容关系

- 新实际 Node Span 全部直接挂已登记 Root，parent_span_id=null。
- 不新增第三层节点，不新增独立 Attempt 实体。node_attempt、report_attempt 和原有调用 retry_index 各自保留职责。
- 原独立 Report Run 保留为 manifest、受控快照和报告观测状态的载体；不作为 Root 下新增执行节点层。新的报告节点不再物理存放在该 Report Run 下。
- 原 Report Run `/spans` 查询可投影其对应 Root 节点，保持真实 span_id/run_id，不复制或改写事实。旧 Report Run 的既有物理 Span 优先原样读取。
- Evidence/LLM/report 受控快照仍按 Report Run/attempt 保存，避免同一 Root 多次报告覆盖原不可变快照；Node 的 report_run_id 指向对应载体。
- Span 终态写入改为锁内检查，先保存终态，再发 finished Event；旧 callback 不能在恢复后覆盖 interrupted Span。
- Recovery 会处理等待 Root 下实际遗留的 running Span，不反推节点已成功。
- collection integrity 单调为 incomplete，窄原子写入不改变 Root lifecycle 字段或 CAS token；旧 Root 更新继续保留 incomplete。

读接口跨业务库、Trace、Registry 为 best-effort 多库读取，响应明确声明并非分布式原子快照。暂时缺失、历史缺失及 Trace 故障均显示 gap，不合成节点。

## 5. 真实计算与 LLM

使用原销售 CSV，共 60 行；2026 年华东已完成订单筛选后 16 行。独立 Pandas 计算与 Engine 完整结果一致：

| 城市 | 销售额 |
| --- | ---: |
| 济南 | 21,250 |
| 南京 | 20,250 |
| 上海 | 5,760 |
| Top 3 合计 | 47,260 |

文件 SHA-256：`8f59a00be875e6fed684be4b388b579d8b0ed9bc5f302be6deb842bc1bfcdd34`。

正式运行的三个 LLM 节点均为真实 qwen3.8-flash 调用，timeout=60 秒、enable_thinking=False，沿用既有配置。三个调用记录均 succeeded，分别关联真实 Root/Span、模板快照、请求快照、实际 Schema 和 operation ID。最终三条候选洞察均被现有 Fact Validator 接受，本轮没有改 Prompt 或放宽规则。

先前真实试跑 02 的报告为 partial（2 条接受、1 条建议被拒绝），原输出与拒绝规则保留。它不能作为本次最终验收：随后旧 Reader 交叉校验发现 writer 的 snapshot_hash 使用了不同序列化算法。修复是沿用既有 canonical digest，**没有更改旧 Reader、重算旧不可变哈希或覆盖旧记录**。正式运行 03 已重新创建 Workflow 并通过该检查。

首轮试跑 01 的业务已真实执行并保存报告，但 Admin 查询因 TestClient 本地访问模式不匹配被拒绝；失败日志及后续授权只读核验保留。最终 03 使用隔离实例的明确 read token 模式，未修改生产 .env 或降低权限规则。

## 6. 代码与测试

实际文件清单和完整差异见 `changed-files.json`、`changes.patch`；前后源码为 `before.zip/after.zip` 和哈希清单。

核心实现：

- `backend/app/storage/workflow_bindings.py`：精确归属、引用注册、分支指纹。
- `backend/app/observability/downstream.py`：claim 后 Engine 观测、直接 Root Reporting 适配、观测失败不改变业务。
- `backend/app/storage/execution_repository.py`：执行 claim/link 原子写入与提交 fence。
- `backend/app/storage/report_repository.py`：授权快照、原子 report link/receipt、提交回读。
- `backend/app/workflow/reporting.py`：真实节点复用、ack 丢失核验、持久化之后完成观测。
- `backend/app/services/workflow_trace.py`、`backend/app/api/admin.py`：按真实 workflow_id 只读查询。
- `backend/app/storage/trace_repository.py`、`backend/app/observability/recorder.py`：终态原子性、gap 与历史兼容读取。
- `backend/app/services/analysis_report.py`：仅增加实际 Chart 调用观测、无证据 skip 决策；统计/洞察规则不变。

新增专项 16 项覆盖：真实 API 全链路及重启读取、旧 Reader 交叉校验、提交回执丢失、Trace 禁用与写入失败、报告失败后重试、缺失 persistence Span、Engine partial、等待 Root 下节点中断、旧审批引用注册、旧 Report Run、无证据不调用/不伪造节点、快照故障 gap、历史归属缺失、上下文查询失败不错误归属、提交后进程中断恢复、过时执行恢复隔离。

原 REQ-0085 的两个“缺口复现”测试升级为“修复后拒绝旧回调”断言；旧版源码和失败结果保留在历史快照中，没有删除 Bad Case。旧 Trace 测试按实际新增 Chart 节点及 Root 归属更新，不通过伪造旧 run_id 维持旧断言。

完整后端回归、Frontend、Admin 测试与构建结果见最终 testing-summary.json 和日志。原有 controlled kernels、Prompt/Provider、冻结 Policy、Session/preparation 状态权威代码均有 protected-source-check.json 核验。

## 7. 仍然保留的边界

1. 不开发 Admin 生命周期时间线，不执行 Workflow Switch，不开放同 Session 多 Workflow 执行。
2. 不将旧 Root.status 改成全生命周期状态机；本阶段通过真实节点及业务提交事实闭环查询。
3. Trace 长期故障期间不能恢复未持久化观测；重启后如实显示 interrupted/gap，不补造过去成功。
4. 历史无明确归属的数据不自动收编；本次失败试跑的不可变错误 hash 记录原样保留，最终验收使用新 Workflow。
5. 跨库读取不是分布式事务；运行中查询可能暂时出现缺口，刷新后按实际事实更新。
6. 完成一次真实可观测性验证不代表全面洞察质量评测通过；本轮没有修改或重新验收业务洞察算法。

完成后停止，等待用户验收，不自动进入 Admin 时间线开发。
