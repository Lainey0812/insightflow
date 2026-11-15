# Phase 03-D：Admin Workflow Observability MVP

需求：REQ-0088。实施日期：2026-10-31。代码、浏览器验证与回归已完成，等待用户验收。本阶段没有执行 Workflow Switch，没有改动业务状态权威、数据库 Schema、Prompt、分析算法或历史 Trace。

## 实现与审计结论

复用 Phase 03-C2 的 `WorkflowTraceService`，以已登记的 workflow_id 和不可变 root_run_id 查询真实关联。复用 `LifecycleReader` 和现有 Lifecycle 聚合规则，增加 business_only 读取选项，使新业务摘要不读取任何 Trace。原有调用默认行为保持不变。

新增 `WorkflowObservabilityService` 是只读投影，不调用重新校验、审批、执行、恢复或报告生成服务。SessionState 仍然是当前业务路径的权威。新页面和 API 没有业务控制操作。

本轮没有新增运行记录、第三层 Trace 或 Attempt 实体。相同 node_key 的实际重入单独展示，不把所有重入都称为失败重试。LLMCallRecord 保持每次真实请求的独立记录。

## 页面与读取 API

- `/traces/workflows`：真实 Workflow 列表，精确 Workflow ID / Session ID、受控业务状态筛选、分页、加载、空态、错误态与手动刷新。
- `/traces/workflows/:workflowId`：业务摘要、精确关联、实际时间线、事件、重入、LLM 调用与采集缺口。
- `GET /admin/workflow-observability?workflow_id=...&session_id=...&status=succeeded&limit=20&offset=0`
- `GET /admin/workflow-observability/{workflow_id}`

现有 `/api/v1/admin` 别名同样可用。旧 `/admin/workflow-traces/{workflow_id}`、Runs、Report Trace、Prompt Registry API 保持兼容。权限复用现有 Admin 只读校验和受限本地测试模式，没有新增匿名远程访问权限。非法筛选返回 422，缺少权限返回 403，不存在的 Workflow 返回 404，不提供 POST 控制入口。

列表排序为 `created_at DESC, workflow_id ASC`。状态筛选发生在分页之前。状态来自 Business DB，Trace DB 不可用时仍保留业务结果。

响应契约为 `workflow-observability-v1`，列表为 `workflow-observability-page-v1`。包含 business_lifecycle、activity、source_refs、consistency、collection、duration_ms、has_exception 与只读 trace。完整真实示例见 [final-api-detail.json](final-api-detail.json) 和 [final-api-list.json](final-api-list.json)。新 UI API 不返回完整结果行、原始用户需求、Prompt、fencing token、原始错误文本或提交回执；调用链接继续受现有 Registry 权限保护。

## 业务结论、耗时与一致性

业务摘要先校验 Session 中的显式 workflow_id / root_run_id 与登记身份一致。失配或缺失标记 inconsistent / unknown，禁止选择“最近成功记录”。当前 Plan、Approval、Execution、Generation 和 Report 使用已有 Lifecycle 精确引用规则。

总耗时仅在有可靠业务终态时间时计算：Workflow 创建到精确当前 ReportGeneration 或 Execution 的终态时间，包含 HITL 人工等待。它不是各 Span 耗时之和，也不是 API 请求性能计时。缺少可靠终态时返回 null。

读取后再次核对 Session revision。读取期间分支变化时返回 unknown 和 SESSION_CHANGED_DURING_READ，不将不同 revision 静默拼成成功结果。跨库查询仍不是分布式原子快照，页面明确提示此限制。

异常标记同时保留已发生的 Engine partial_success、报告失败/不可用和实际异常节点，不因报告排队或 Trace 缺失隐藏业务失败。

## Collection Gap 的五类语义

| 分类 | 证据与显示规则 |
| --- | --- |
| not_executed | 仅根据已保存的显式跳过事件；不根据节点缺席推断 |
| executed_trace_missing | 存在明确执行/提交事实，但相应 Span 缺失 |
| observation_incomplete | 已有观测但结束、完整性或调用关联不完整 |
| inconsistent | 业务引用或 Workflow 归属不一致 |
| unknown | 缺少足够证据，或 Trace 不可读取 |

Execution claim 本身不足以证明 Engine 已实际开始；中断 claim 无 Span 显示 unknown。时间线只循环数据库返回的实际 Span，不预设节点补齐流程图。`observed` 仅表示已读取记录未发现显式缺口，不承诺从缺席中证明所有可能节点均已执行。

## 固定真实 C2 样本

使用原始 `var/verification/c2-closure-release03` 数据库，未新跑 LLM 或业务分析，未补造数据。

| 对象 | 真实引用 |
| --- | --- |
| Workflow | wf_65b741d8c88b45a2940abace3c8f92e5 |
| Session | 71b2a50f7e4c4b44bea7e245b5b9cdf4 |
| Root | run_15c55fbf4a624e3c8ff4eb2c07abb526 |
| PlanVersion | wpv_a69aaaf0ac668ccca2ad8ec8356c35275a6296576074b91f79f09277fb1c06ac |
| Approval | approval_1404ce3086f44124bfd7c0aee4f45b29 |
| Execution | exec_1739e70a5bd6468eb9ed55005379e3e2 |
| Report | report_4d0455e523c645d99660ed61467dfc1e |

真实页面展示 **14 个实际 Span、3 条已保存的真实 LLM 调用**，业务状态 succeeded、报告已交付。Root 原始状态仍是 waiting_approval，页面明确区分准备阶段检查点与业务结论，没有篡改旧 Root。业务耗时约 16.24 秒，口径如上。

浏览器实际验证列表进入详情、精确 ID + 状态筛选、直接刷新、展开 Engine 结果引用与事件。证据见 [browser-verification.json](browser-verification.json)、[详情截图](workflow-detail-final.jpg)、[列表筛选截图](workflow-list-filtered.jpg)、[Engine 展开截图](workflow-engine-expanded.jpg)。

故障注入仅断开测试读取实例的 Trace 依赖，不修改数据库。页面仍展示业务报告已交付，时间线为 0 个可读取实际 Span，清楚展示采集缺口。3 条 Registry 调用仍为独立可读取事实。见 [故障响应](trace-unavailable-api.json) 与 [故障截图](workflow-trace-gap.jpg)。

通过只读连接逐表计算行内容摘要，Business / Trace / Registry 三库验证前后摘要均一致。见 [只读证明](fixed-sample-readonly-proof.json)。没有任何本轮真实 LLM 调用或历史状态回写。

## 预览运行方式

当前 5174 预览连接的是 **固定 C2 样本的只读后端 8005**，用于验收，不是主业务 var 数据库的实时监控。

复现固定样本：在项目根目录运行 `.venv/bin/python docs/implementations/admin-workflow-observability-2026-10-31/readonly-browser-harness.py`，然后在 admin 目录以 `ADMIN_API_PROXY_TARGET=http://127.0.0.1:8005 npm run dev` 启动。该验证入口只读打开原始样本，没有初始化、恢复、模型调用或迁移。`--trace-off` 使用 8006 注入 Trace 不可用，只用于验收。

正常业务环境使用原有后端启动方式及 Admin 默认代理 8000；新 API 已接入应用装配，不需要修改 .env。当前预览未改写任何 .env。

## 修改清单

权威逐文件清单为 [changes-final.json](changes-final.json)，代码差异为 [changes-final.patch](changes-final.patch)，源码快照为 source-final.zip / source-final.json。

- 后端：新增聚合服务与 9 个测试；修改 LifecycleReader 的只读选项、Admin 路由与 main 装配。
- Admin：新增类型/API、列表、详情、共享展示、测试及真实脱敏样本 fixture；更新导航、路由、404 文案、样式和测试；TypeScript 开启 JSON fixture 导入。
- Frontend：未改动产品代码。
- 数据库：无迁移，无历史载荷改写。

初始快照范围与自动扫描纠正说明见 [snapshot-scope-note.md](snapshot-scope-note.md)。四个历史 SQL 文件未在本轮新增或修改，不能把初始扫描的误分类当成迁移交付。

## 回归结果

| 检查 | 实际结果 | 日志 |
| --- | --- | --- |
| Backend 全量 | 1468 passed，1 个已有依赖弃用警告 | backend-tests.log |
| Frontend 全量 | 67 passed | frontend-tests.log |
| Frontend 构建 | 通过 | frontend-build.log |
| Admin 全量 | 88 passed | admin-tests.log |
| Admin TypeScript + Vite 构建 | 通过 | admin-build.log |

新增后端测试覆盖真实列表/详情读取与行记录不变、Trace 下线、关联不一致、稳定分页、报告失败、显式跳过、claim 不等于执行、并发 revision 变化、Engine 部分成功在报告排队时仍标记异常。权限、非法参数和只读入口纳入断言。

Admin 新测试覆盖 14 Span / 3 Call 展示、筛选分页、展开、错误/空态、Trace 缺失、错误归属响应拒绝与导航兼容。构建中一次测试查询类型错误已修复，早期失败日志单独保留，没有覆盖。

## 剩余限制与验收建议

1. 第一版手动刷新，没有轮询或后台推送。
2. 状态筛选需要只读聚合候选 Workflow，当前为 O(N)；未引入物化统计表。大规模数据需另行优化。
3. 跨库无分布式快照。revision 复核能识别业务分支变化，无法消除所有跨库瞬时延迟。
4. 历史未登记 Workflow、丢失 Span 或缺少精确引用仍显示缺口，不自动回填或伪造。
5. 固定样本本身没有覆盖每一种真实失败/重试；异常类别通过独立临时数据库与故障注入测试验证，没有改写样本来伪造真实异常历史。
6. 本阶段只读。没有新增业务 Retry、Recover、审批、Prompt 修改、Dashboard 或多 Workflow 功能。

建议按真实截图和固定 API 样本完成验收。实施到此停止，下一阶段须另行确认。
