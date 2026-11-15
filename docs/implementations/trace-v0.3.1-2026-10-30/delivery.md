# Trace V0.3.1 阶段交付与验收记录

需求：REQ-0059。日期：2026-10-30。仅实施 Root Run 与准备阶段，等待用户验收后再进入 V0.3.2。不是全链路 V0.3 完成声明。

## 结果

同一真实 Session 的澄清恢复和检查点重试复用一个 Workflow Root Run。Profiler、Intent、Planner 和两个真实 Validator 调用点创建 Span。实际模型请求通过已有 LLMCallRecord 关联当前 Root/Span，保留 operation_id 和内部 retry 链。没有新增运行事实表，没有改造 Node.run 返回、Prompt 内容、模型参数或审批/计算规则。

完整后端测试：806 passed，1 项已有 Starlette TestClient 弃用提示，39.73 秒。新增专项文件运行结果为 18 passed（含参数化用例）。测试日志、失败的首次测试命令、真实超时记录均保留。

## 契约、迁移与生命周期

| 对象 | 实际约定 |
|---|---|
| Root | 原 trace_runs 中 kind=workflow；workflow_run_id 指向自身，execution_id=null；Session 唯一索引防重复 |
| 创建点 | Session repository.create 成功后、现有 access.issue 和 BackgroundTasks 前登记；Trace 失败不回滚业务 Session |
| 状态 | queued → running → waiting_input / waiting_approval / failed；重试或澄清恢复 running；真实取消/启动恢复可记 interrupted |
| 完整流程状态 | 本轮不把计划准备完成写为 complete；Root 的 Engine/Report 状态聚合留给后续阶段 |
| Span | 实际调用开始/结束写入；每次主节点重执行分配新的 node_attempt；终态不可修改 |
| Event | workflow 的 sequence 在 SQLite 事务内分配；跨恢复连续，最多 256 条/Root；超限作为观测缺口 |
| LLM Call | 原 CallRecord 存储，不复制模型请求；run_id/span_id 关联 Root/当前节点，内部重试共用节点 Span |
| Report | 原 report_generation Run 保留，新的报告可引用已有 Root；原 Manifest 不改，旧记录不回填 |
| 历史缺失 | Session 没有 Root 返回 not_collected；不能据此判定未执行，也不补造历史 Span |

对 contract-and-plan.md 的登记时点表述作此明确更正：实际代码在发放 Session 凭证之前登记；不是在发放之后。

迁移在原 Trace SQLite 中将 execution_id 从 NOT NULL 改为可空，事务复制旧记录并检查外键；新增 workflow Session 唯一索引和 trace_migrations 记录。不生成假 execution_id。专项迁移测试验证旧 Run JSON、Manifest、Span、Event 原样保留。生产存储迁移前备份在权限受限的 var/backups/，不归档数据库或密钥。

恢复策略仍限原有单进程部署：启动时将遗留 queued/running Run 和活动 Span 标为 interrupted，记录 recovered_at，不推测崩溃时刻，不补 finished_at/计算耗时；等待态保留。实际捕获到的取消具有已观测结束时刻。Root 等待时间不计入节点耗时，Root duration_ms 暂为空。

## Runtime 节点与 Trace 状态映射

| 真实入口 | Span / 关联 | 正常业务分支 | 异常 |
|---|---|---|---|
| WorkflowOrchestrator.prepare_real → data_profiler.run | data_profiler | complete；记录真实 dataset/version/行列数 | failed，受控错误代码与说明 |
| prepare_real → intent_parser.run → IntentParserService.parse | intent_parser，关联真实 CallRecord | proceed 或 clarify 均 complete；clarify 后 Root waiting_input | 节点失败、协议/Schema/超时写 failed |
| prepare_real → real_planner.run → AnalysisPlannerService.plan | analysis_planner，关联真实 CallRecord | 规划返回可行性包括 F0 时仍可 complete | 节点超时为 failed；外层超时取消的 Provider Call 可是 cancelled |
| AnalysisPlannerService 内实际 validate | plan_validator，父为当前 Planner；validation_role=planner_output | 记录 coverage/executable/blocked；F0 不等于运行异常 | 调用抛异常才 failed |
| PlanReviewService.validate_v1 | 独立 plan_validator；validation_role=initial_plan_save | 初次保存计划前的真实校验结果 | 调用抛异常才 failed |
| HITL 审批、Engine、Report 子节点 | 本阶段未新增这些节点的 Span | 不反推成功 | V0.3.2/0.3.3 再接入 |

ContextVar 只传递当前观测上下文，finally 重置；不调度业务。Validator 两次调用分别记录，不能合并伪称只发生一次。

## 错误与 fail-open 边界

TraceRepository 错误由既有 TraceRecorder 受控日志捕获，不记录原始异常/密钥/数据集内容；collector_degraded、Root integrity=incomplete、Event observation_gap 尽可能暴露缺口。Root 完全登记失败时保留进程内受限 Session gap 索引，对应查询 not_collected。写 Span 失败不伪造持久 Span ID/Attempt，也不将模型 Call 关联到不存在的 Span。

如果整个 Trace 存储不可写或进程已退出，无法保证该存储同时保存自己的缺口：进程内 gap 在重启后可能丢失，未知情况返回 observation_gap=null，而不是 false。内存索引最多 256 个 Session，日志最多 10 次；上限和事件预算是已知可观测性限制。

节点失败使用真实业务错误码，说明为受控映射；没有保存原始报错全文。LLMCallRecord 的 status 代表 Provider 协议结果，不等于 Intent/Planner 业务校验结果。

## API 与兼容

沿用原 Admin 鉴权、敏感快照权限和错误处理。本机保留用户此前启用的 loopback 本地测试模式，未扩大访问范围。

- GET /api/v1/admin/runs?kind=workflow：显式查询 Workflow Roots；原默认仍为 report_generation，防止未升级 UI 混淆对象。
- GET /api/v1/admin/workflows/{session_id}：已有根 Run 或 not_collected，返回观测范围说明及已知缺口。
- GET /api/v1/admin/runs/{run_id}/spans：真实准备阶段 Span。
- GET /api/v1/admin/runs/{run_id}/events：真实 Root/Span 事件，分页。
- GET /api/v1/admin/spans/{span_id}/llm-calls：复用原调用查询；模板及请求快照继续受原权限保护。

Run Explorer Progress、轮询、Root 专用 Inspector 本轮均未开发。现有 UI 默认继续查询报告 Run；应通过上述 API 验收阶段一，不宣称 Admin 已展示完整主链路。

## Prompt 和模型保持情况

三节点实际请求组装使用本地 MockTransport 捕获前后消息、JSON Schema 和请求参数，逐字节相等（request-assembly-comparison.json 三项 true）。这是请求组装兼容性测试，不冒充真实模型评测。

Prompt Registry 的源指纹包含服务文件，埋点会改变代码组合哈希，因此追加 composition-v0.2-trace-v0.3.1，保留原 composition-v0.1 快照。Intent intent-v1.3.3、Planner planner-v1.2、Insight report-insights-v1.1.9 的指令内容未修改。真实模型仍 qwen3.8-flash、超时 30 秒；Intent enable_thinking=false，Planner 未设置此参数。没有为了验收调整它们。

生产 Registry 原 3 个快照仍存在，新组合登记后共 6 个。完整用户请求未复制到交付文档；只有原 Registry 中受控快照保留真实请求。

## 真实前台验收

使用此前授权的 insightflow_sales_orders_test.csv，真实上传，60 行 12 列；通过前台发送问题和补充、点击现有重试。沿用当前阿里云服务和真实模型。观测脚本只读轮询实际 SQLite 持久变化，不插入任何事件；API 导出独立核对。共 2 个新 Session、6 次真实 LLM 调用；没有批准或执行分析。

| 场景 | 实际过程与结果 | 结论 |
|---|---|---|
| A 正常准备 | “统计这份数据的总订单数。”；Root run_2db5303326b244ceab1162afbf181aba；Profiler/Intent/Planner/两处 Validator 共 5 个 complete Span，12 条 Event；Root waiting_approval；2 次真实 Call succeeded | 准备追踪通过；原 HITL 约束映射仍阻止批准，不在本轮修复 |
| C 澄清恢复 | “帮我处理一下。”；Root run_8b798dfc8c34474f82429ccca1d4a221；Intent complete，next_action=clarify；Root waiting_input，尚无 Planner Span；补充原销售 Top 3 问题后，Intent attempt 2；沿用同 Root | 通过；旧 Intent 和等待事件完整保留 |
| B 自然超时 | 上述补充请求导致 Planner 在 30 秒总时限超时；Planner attempt 1 failed/LLM_TIMEOUT，Call cancelled/LLM_CALL_CANCELLED；没有 Validator/Engine 下游成功记录 | 超时追踪通过；模型调用本身失败，未伪称规划成功 |
| D 前台人工重试 | 点击一次“重试准备”；同 Root 新增 Planner attempt 2，又真实超时；原失败 Span 与第一次 API 导出逐字段相等；共 5 个 Span、16 条 Event | Attempt 留存通过；不代表重试恢复业务成功 |

复杂问题原文：“帮我分析 2026 年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。”

两个 Session：04627ec38ec245bf8794111a84803d84、8d7d0076ff4647eb99b8561ea36e91ef。刷新前台后第二个任务仍显示失败、澄清对话及重试记录；没有丢失。最终 API 与持久数据库中的根状态、Span、Event、Call 关联一致，Event sequence 连续。旧 Session 查询返回 not_collected。

live-verification/verification-checks.json 保存自动核对结论；observations.jsonl 保存中间真实 running/waiting/failed 状态，07-final-api.json 保存最终只读 API。截图 02/03/05/06 分别是正常准备、澄清、真实超时和重试刷新。04-resuming-api.json 虽名为 resuming，抓取时实际已经 failed，应以响应内容为准；01-live-running-api.json 同理实际为 waiting_approval。

本次没有人为杀进程制造“真实服务崩溃”；异常退出恢复仅由专项集成测试验证，没有混同真实前台验收。内部 JSON 重试链由自动化测试验证，本次 6 次真实请求未触发这种内部重试。

## 代码改动

修改 11 个后端文件：api/admin.py、api/routes.py、domain/tracing.py、llm/templates.py、main.py、observability/recorder.py、services/analysis_planner.py、services/intent_parser.py、services/plan_review.py、storage/trace_repository.py、workflow/orchestrator.py。

新增 4 个文件：observability/context.py、observability/workflow.py、storage/trace_migrations.py、tests/test_workflow_trace_v031.py。frontend/admin 源码、Node.run、Engine、Planner/Intent Prompt、Report 洞察业务未修改。plan_review.py 只为实际 validate 调用加观测边界，没有改变审批/删任务规则。

source-changes-final.json 是按修改前 ZIP 同等文件选择规则生成的准确清单。初次 source-changes.json 将未纳入基线 ZIP 的 5 个既有前端 JSON fixture 列为 added，属比较覆盖误报，未改动这些文件；保留该初次记录并用最终清单纠正，不把它们计入本轮改动。

## 测试范围与剩余问题

自动化覆盖真实服务+临时 SQLite、模拟模型协议响应：Root 唯一、节点生命周期、两个 Validator 入口、F0 正常返回、clarify、超时/检查点重试、JSON/Schema/节点错误、内部 LLM Call retry、并发 Context 隔离/序号分配、取消、启动恢复、4 种 Trace 写故障 fail-open、历史迁移、Report Root 关联、权限边界。没有使用模拟输出冒充上述真实前台过程。

仍存在：复杂销售问题两次 Planner 总超时；总订单数任务的 HITL 约束映射阻断；本轮不修复这些业务问题。Root Manifest 保存创建时不可变初始信息，后续澄清的最终模型请求从各次受控 RequestSnapshot 查阅，不能用初始 goal 哈希宣称后续输入相同。Root 当前 capture_scope=workflow_preparation，不支持跨节点全流程对比完整性保证。全库锁/高并发下 fail-open 可产生缺口，当前单进程恢复不是分布式任务接管。

建议：V0.3.1 的四个真实追踪场景可提交验收；尚不能宣称完整 Workflow 可观测性已完成。待用户确认后再实施 V0.3.2 的 HITL/Engine，不提前开发 Progress UI。
