# InsightFlow Lifecycle V1.0：分阶段实施与验收计划

任务书 REQ-0059；独立档案 REQ-0063。**当前只完成阶段 0，下面均为评审后的实施计划，不授权跳过阶段门槛。** 原 Trace V0.3.1 的 Root/准备埋点复用，不重复初始化。

设计入口：[现状审计](REQ-0059-lifecycle-audit.md) · [状态机/逐节点契约](REQ-0059-lifecycle-state-machine.md) · [Trace 增量契约](REQ-0059-trace-data-contract.md)。

## 阶段 0：本次实际交付

新增本目录四份指定文档、只读运行元数据、源码哈希和静态符号索引；需求原文完整登记 REQ-0063，关联 REQ-0059。无业务源码、模型参数、Prompt、数据库结构、API、UI 变更，无模型/审批/执行调用。

检查方式：只读源码、AST、SQLite mode=ro/query_only 元数据、静态引用和源码前后哈希。没有导入 app.main 启动应用，没有触发仓储恢复/迁移。只读查询遇到旧 Session 缺失字段后按 null 处理，不修改它。

既有日志中的 806 项后端测试与 59 项 Admin 测试属于之前版本，本次不重跑、不冒充 Lifecycle V1.0 通过。原真实 CSV 验收仅证明准备阶段；当前业务库没有真实 Execution/Report，不能交付“完整链路真实通过”的结论。后续各阶段必须另做对应测试。

## 阶段 1：补齐已有 Root 的完整生命周期

### 预期文件

- backend/app/domain/tracing.py：兼容可选 checkpoint 字段、Schema 版本；保留旧枚举/Manifest。
- backend/app/storage/trace_repository.py：Root 转移矩阵、状态与追加事件事务、版本/分支守卫；报告 Run 终态仍不可修改。
- backend/app/observability/workflow.py：从仅准备检查点映射扩展为聚合调用入口，复用 register_root。
- 可新增 backend/app/observability/lifecycle.py：纯聚合/投影辅助，不调度业务、不接 LLM。
- backend/app/api/admin.py / main.py：只读 Workflow 视图与启动后的观测投影校正；原 API 默认语义保持。
- tests：在 test_workflow_trace_v031.py 既有覆盖上追加生命周期聚合与并发专项，不重写业务测试。

### 数据/API

复用既有 workflow_session_unique、Root 与 Report 关联，不重做 V0.3.1 execution_id 可空迁移。新增可选观测 checkpoint，旧记录空值兼容；若无需表结构变化，明确为 JSON Schema 兼容升级。新增 /admin/workflows 主列表、扩展既有 /admin/workflows/{session_id} 的只读投影，或分阶段只上线详情；必须保留旧字段、鉴权和 report Run API。

### 验收

聚合矩阵逐例单测；Session 根唯一/并发、旧 Root/Report JSON、合法 reopen、旧分支迟到回调、未知业务记录、Trace 失败 fail-open、重启恢复不伪造时间。原真实 Session 的 Root 必须继续复用，旧记录不可回填节点。没有阶段 3–5 埋点时，只可验收聚合基础和现有准备范围，不能宣称所有节点可见。

## 阶段 2：准备节点与所有 Validator 用途

### 预期文件

复用 workflow/orchestrator.py、nodes/base.py（只核对、不改变 Node.run）、services/intent_parser.py、services/analysis_planner.py、services/plan_review.py、services/analysis_engine.py 中校验调用、reporting/contracts.py、services/analysis_report.py、api/plans.py、llm/templates.py、observability/context.py/recorder.py。

### 最小实现

保留现有 Profiler/Intent/Planner Span；绑定真实 NodeRun 引用（可选）、区分全部 Validator role。HITL/Engine 在此阶段只增加其**实际 Validator 调用的观测边界**和验证过的 Root 上下文，不提前增加审批业务事件或 Engine 主执行 Span；报告 prepare 的实际 PlanValidator 使用现有 Report TraceContext。这样阶段 2 能验收全部关联得上的校验入口，阶段 3–5 再扩展各自生命周期。

review_read 标诊断用途，不能成为主进度或触发 Root 状态变化；新监控 API 不调用 review_presentation。独立 /plans/validate 没有 Session/Root 时明确未关联，不创建虚假的用户任务。Schema 顶层错误会抛 PLAN_SCHEMA_INVALID，步骤参数 INVALID_SCHEMA 则可作为 F0 正常返回；二者测试区分。

### 验收

准备成功/自然或显式模拟超时、Schema 错误、clarify、空输入 0 Call、内部有限重试、用户重试新 Span、F0 正常返回；9 类调用用途逐点验证、真实次数（包括 Engine claim 内第二次校验）与数据库一致。Payload 组装对照证明内容/Schema/参数不变；代码指纹变化追加组合版本，不覆盖旧模板。

## 阶段 3：HITL 等待、动作与恢复

### 预期文件

api/routes.py、services/plan_review.py、storage/plan_review_repository.py（保持原业务事务/触发器）、observability/workflow.py/recorder.py、tests/test_plan_review.py 与专项观测测试。

### 最小实现

在原事务成功后记 plan_revised/approval_accepted，真实冲突/拒绝分支记诊断 Event；重复审批标 replay，不重复造 Approval。等待为业务状态与 Events，不设长期 running Span。旧审批失效以真实最新计划/快照引用判断，不修改历史 approval_status 或删除审计行。不要增加自然语言修订、取消流程或“用户拒绝”新 API。

### 验收

同 Root：等待→删除任务→新版本重验→新审批；旧审批/版本冲突、幂等参数冲突、未确认条件阻断、F0/partial 覆盖限制均保持；用户等待不进入计算耗时。审批已接受但前端未执行时显示 approved_not_started，不能造 Engine running。错误请求不泄露其他 Session/密钥，观测失败不改变审批结果。

## 阶段 4：Engine 主节点与 Task 诊断

### 预期文件

services/analysis_engine.py、execution/loader.py、execution/task_runner.py、storage/execution_repository.py、api/executions.py、观测辅助与 tests/test_analysis_engine.py / 专项生命周期测试。只加边界，不改六类 Pandas 内核、结果或执行规则。

### 最小实现

保留 replay→precheck→load→claim 的顺序。前置真实读取/校验有独立诊断；新 claim 后才创建计算主 Span。任务引用原 StepExecutionLog/TaskExecutionMetadata/结果引用，结果不复制到遥测。任务级失败隔离、空结果、skipped 的原语义保持。原中断恢复保留结果不自动重跑，Trace 显示恢复原因与未知实际结束时间。

### 验收

独立 Pandas 基准、CSV/XLSX、成功/partial_success/全失败、空表、跳过、保存异常、重复/并发同 request 不二次计算、claim 后 Trace 故障、已保存部分任务后中断恢复。前置拒绝与执行失败分离。Engine 结束但报告未 enqueue 的窗口单测/集成测必须可诊断，不擅自自动修复队列。

## 阶段 5：Reporting 完整采集与历史尝试

### 预期文件

workflow/reporting.py、services/analysis_report.py、storage/report_repository.py、domain/models.py（优先复用 ReportGeneration，不改公开形状）、storage 下增量迁移、observability/recorder.py、api/executions.py / admin.py 的只读历史查询、现有报告/Trace 测试。

### 最小实现

保留原报告 Run 与五类主 Span；补真实 Chart Builder，以及输入预检查/校验诊断。沿用 workflow_run_id 和 execution_id+attempt；报告重试新子 Run，Root 不变。按评审选择增加原 Repository 内的 ReportGeneration attempt 历史（推荐），最新投影仍是原表；不能依赖 fail-open Trace 充当完整业务历史。

Persistence 必须确认事务实际保存了该 attempt；过期 no-op 不假报 saved。业务提交后聚合 Root；报告失败不会改 Engine 状态；零证据走 skipped LLM/Fact，全部候选拒绝/缺核心仍保持真实失败。旧失败、旧报告不覆盖；completed/unavailable 当前不允许重试的规则不改。

### 验收

Engine success+报告failed、Engine partial+报告completed、报告partial/goal blocked、零证据 unavailable、LLM失败、Fact部分拒绝与全拒、核心遗漏、Chart异常、Persistence失败/过期返回、report retry、旧计划报告迟到、历史尝试缺失和迁移回滚。新的 Span 数量增长须更新新版本测试预期，旧历史五 Span 数据原样读取；不为了保住旧数量而漏采新节点。

## 阶段 6：Admin 生命周期可视化

### 预期文件

admin/src/types/traces.ts、api/traces.ts、pages/TracesPage.tsx / TraceDetailPage.tsx、features/traces 与样式/测试。保留仅 Trace/Prompt 可点的导航（REQ-0062），不顺带开放其他模块。

### 最小实现

明确切换 Workflow 主列表 API，一 Session 一行；旧 Report Run 保持详情/历史诊断入口。主进度 11 逻辑节点，Persistence/前置/Task 为详情。状态来源与 Attempt 显示真实绑定，未采集与 pending 分开；HITL 等待黄、partial 显示标签、失败和中断红但文本不同。Run/Call/Prompt Snapshot 深链复用。

活动列表约 5–10 秒、详情约 2–3 秒轮询；当前终态停止，但手动刷新/已接受重试可重新开始；等待态低频或手动刷新，避免被新恢复遗漏。API 错误只标数据不可用/陈旧，不改业务状态。不轮询会重新 Validator 的 review API。禁止根据流程顺序填绿上游。

### 验收

真实后台数据与数据库一致；并发任务隔离、历史 Root 缺失、旧 Report Run、两次 Attempt 展开、恢复后版本一致、跨请求及服务重启重载、无权限、敏感投影、超时/请求失败、活动/终态轮询停止和重新启动。Admin 构建/全测试；原前台构建/测试不退化。

## 共用冻结验收矩阵

| 场景 | 关键断言/层 |
|---|---|
| 同 Session 创建/并发恢复 | 单 Root；不同真实执行独立 Span；无跨 Session Event/Call |
| Intent clarify 与补充 | 意图执行正常 complete，业务等待；不提前 Planner；新 Span 保留旧记录 |
| Planner 调用成功但 Schema 失败 | Call succeeded 仅协议层；节点真实失败，错误规则可查 |
| F0/核心 blocked | Validator complete，审批不可越过，不伪造完整覆盖 |
| 审批冲突/重放 | 保留真实请求结果；无新成功审批，无虚假 Engine |
| Engine partial/empty/all failed | 真任务状态、结果引用/样本数，不能统一显示 succeeded |
| Engine 成功但报告失败 | Session 可 COMPLETED，Lifecycle partial、report failed 同时可见 |
| Report 部分拒绝/全部拒绝/无证据 | 保持现有 Fact 规则；partial/failed/skipped 来源真实 |
| Report retry 与旧回调 | 同 Root 新 attempt；旧失败只读，当前分支不被旧计划结果覆盖 |
| 进程中断 | 只标真实未结束记录，恢复时间不是实际执行结束，已有数据不丢不自动重跑 |
| Trace 写入失败/事件预算 | 正常业务不退化；明确 incomplete/unknown，不伪造成功或自证“无缺口” |
| 请求快照存储失败 | 保持原安全策略，不发/不释放未留档结果，不伪装 Trace fail-open |
| 历史无 Root/历史配置缺失 | run_id=null / unknown；禁止用当前配置反推历史 |
| 原分析行为 | 同输入结果、授权、幂等与输出契约保持；三节点请求 payload/Schema/参数对照 |

每阶段冻结用例后再运行，真实调用与 MockTransport/故障注入分开记录。既有真实 CSV（60 行销售订单）可复用；正常规划、HITL 不能通过时记录实际阻断，不能手工改生产批准快照来冒充前台验收。异常/进程终止优先隔离测试实例，真实验收不强行拖延模型制造超时，不中断其他用户任务。所有 Bad Case、失败命令、前后快照和输出保留。

## 评审需确认的具体选择

1. 是否采纳“有真实计算结果但报告失败→partially_succeeded，另显 report_failed”的聚合语义；它不等于完整报告交付。
2. 是否采纳终态 Root 可由既有合法修订/重试 reopen，身份不变、旧结算/失败记录追加保留。
3. 是否采纳同一 ReportRepository 的 attempt 历史最小扩展；若推迟，接受业务历史只能部分追溯的限制。
4. 是否采纳 Engine claim 前后分开诊断/计算边界，重复请求不产生第二个 Engine 计算 Span。

以上有明确推荐方案，供本次设计评审。**本轮到此停止，不进入阶段 1，也不开发 UI。**
