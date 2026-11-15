# Phase 02-A：Expand Only 实施与验证报告

关联需求：REQ-0077。实施目录按开始日期 2026-10-30 保留。状态：**Expand 完成；未 Backfill、未 Switch、未开放多 Workflow**。

生产 Business Workflow 数量为 **0**。现有 Session 仍是唯一分析状态权威；Schema 已存在不代表 Session 1 已可使用新 Workflow 功能。

## 1. 实施前补充与范围解释

五项事务/归属约束见 [design-addendum.md](design-addendum.md)，以新稿补充冻结的 Phase 02 文档，没有覆盖旧设计。

- Workflow 身份、预留 Root ID、创建请求键及 hash 位于同一业务行；未来创建必须同事务提交。
- 未来 Workflow 原生审批、执行、报告与归属链接必须同业务事务提交。Expand 没有接入这些 writer；旧 Session 路径仍按原合同运行，不能把新表的单向 FK 宣称为已经强制旧事实写入链接。
- Switch 前需检测五类活跃记录、排空/停止旧 worker、部署业务 fencing 与旧写入保护。本阶段只创建路由结构，不启用路由切换。
- 消息用 (session_id,message_id) 主键；origin 是同 Session 来源引用，不用于隐式选择当前工作流；parent 只作不可变同 Session 来源，不继承审批。
- ReportGeneration 是当前 generation，历史 Report Run 是观测，AnalysisReport 是已提交报告。未恢复的历史尝试不补造；没有 Attempt 实体或第三层 Trace。

## 2. 实际源码变更

**没有修改或删除任何已有源码文件。新增 8 个文件：**

| 文件 | 原因 |
|---|---|
| [domain/business_workflow.py](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/business_workflow.py) | 冻结的只读 WorkflowView/WorkflowPlanView；复用现有 PlanVersion，不建立执行服务 |
| [storage/workflow_expand.py](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/workflow_expand.py) | 显式迁移、Schema/版本/校验和检测、FK=ON、单库原子提交及只读检查 |
| [storage/workflow_reader.py](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/workflow_reader.py) | URI mode=ro/query_only；读取 Workflow、native/legacy 版本、审批/执行/报告及侧库链接；不调用 Validator 或业务写服务 |
| [业务库 DDL](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/migrations/workflow_expand_business_001.sql) | 业务基础结构、同 Session/Workflow FK、只追加历史保护 |
| [Trace 库 DDL](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/migrations/workflow_expand_trace_001.sql) | Run 归属链接与每 Workflow 唯一 Root 链接，不删除旧 Session 唯一 Root 索引 |
| [Registry 库 DDL](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/migrations/workflow_expand_registry_001.sql) | LLM 调用归属链接，不改调用、请求和模板原始记录 |
| [scripts/expand_business_workflow.py](/Users/lainey/Desktop/vibe-coding/insightflow/backend/scripts/expand_business_workflow.py) | 明确维护窗口、活跃任务检测、SQLite backup API、逐库执行与失败报告；没有 Workflow 创建命令 |
| [tests/test_workflow_expand.py](/Users/lainey/Desktop/vibe-coding/insightflow/backend/tests/test_workflow_expand.py) | 31 项约束、幂等、回滚、兼容、备份及只读行为测试 |

原应用 main、API、Planner、Engine、Reporting、Lifecycle、Root CAS、前端及 Admin 源码均未改，也未添加启动迁移钩子。见 isolation-verification.json、source-diff.json。新组件没有被现有运行模块导入，因此不会偷偷改变真实审批/计算路径。

## 3. 新 Schema 清单

完整逐字段、PK、FK、对象名及行数在 [schema-inventory.json](schema-inventory.json)，实际 SQL 在上表三个 DDL 文件。合计新增 **14 张表（含每库各一张迁移版本表）、6 个显式索引、30 个触发器**；约束生成的 SQLite 自动索引另由表定义承载。

### 3.1 业务库：10 表、3 显式索引、20 触发器

| 表 | 主要字段/键与约束 |
|---|---|
| business_workflows | workflow_id PK、root_run_id UNIQUE、session_id FK；创建 key/hash、目标/hash、数据引用、origin/parent、control_status/context、revision/active key、当前计划/批准/执行引用；UNIQUE(session_id,creation_request_id) |
| session_messages | PK(session_id,message_id)、UNIQUE(session_id,sequence)；role/kind/content/time、可空 Workflow 归属 |
| session_datasets | PK(session_id,dataset_id)，FK Session/Dataset |
| workflow_plan_versions | plan_version_id PK、UNIQUE(workflow_id,plan_version)；native payload 或 legacy locator 二选一；legacy locator FK 保留旧 (session_id,version)；数据版本必须与 Workflow 相同 |
| workflow_approval_links | approval_id PK/FK 旧审批、Workflow/Session/版本组合 FK、客户端 key/hash、批准快照 hash、来源与登记时间 |
| workflow_execution_links | execution_id PK/FK 旧执行、同 Workflow 的 approval+plan_version 组合 FK、dispatch key、客户端 key/hash |
| workflow_report_links | report_id PK/FK 旧报告、同 Workflow/Session 的 Execution 组合 FK、accepted_report_attempt；native 链接须匹配实际已完成 generation |
| session_workflow_routes | Session PK/FK、legacy/shadow/workflow_v2 元数据、同 Session 的 default Workflow FK；**实际行数 0、未启用** |
| workflow_backfill_items | source_type/key/decision_version 复合 PK、source hash、候选 Workflow、裁定状态、规则、证据与错误；裁定只追加 |
| workflow_expand_migrations | 本库版本、database_kind、checksum、applied_at；不可修改/删除 |

显式索引：workflow_session_created、expand_approval_owner、expand_execution_owner。后两者只给旧表增加组合唯一索引，没有删除或修改旧 PK、旧唯一约束。

触发器：迁移版本 no_update/no_delete；Workflow identity_immutable、revision_guard、history_no_delete；message_identity_immutable；workflow_legacy_plan_owner、workflow_plan_no_update/no_delete；approval/execution/report source_guard 及各自 no_update/no_delete；workflow_backfill_no_update/no_delete。

同 Session 约束覆盖 origin message、parent、授权文件及当前 Workflow；同 Workflow 组合 FK 覆盖版本、批准、执行、报告和当前引用。源守卫还核对旧 JSON 的 Session/计划/数据/审批身份；hash 完整性和完整快照等价由只读 Resolver/未来 writer 核对。FK 不等于已实施命令准入或语义幂等。

### 3.2 Trace 库：2 表、2 索引、5 触发器

- trace_workflow_links：run_id PK/FK、workflow_id、session_id、kind、evidence、registered_at。
- workflow_expand_migrations：本库版本，独立于原 trace_migrations。
- 索引：expand_workflow_root_identity（kind=workflow 时 workflow_id 唯一）、expand_trace_workflow_lookup。
- 触发器：版本 no_update/no_delete；trace_workflow_source_guard；链接 no_update/no_delete。

原 workflow_session_unique 仍在；测试确认同 Session 的第二个 Root 仍被数据库拒绝。新链接不是新的 Trace 节点，也不把历史 Report Run 改成子层。

### 3.3 Registry 库：2 表、1 索引、5 触发器

- llm_call_workflow_links：call_id PK/FK、workflow_id、session_id、真实 run_id/span_id、可空 root_run_id、证据和登记时间。
- workflow_expand_migrations：本库版本，原 registry_migrations 保持原值。
- 索引：expand_call_workflow_lookup。
- 触发器：版本 no_update/no_delete；call_workflow_source_guard；链接 no_update/no_delete。

不创建跨 SQLite 的伪 FK。侧库只能核对本地 Run/Call 与 Session 元信息；只读 Resolver 额外核对业务 Workflow，不能凭一条侧库链接制造业务归属。将来的 Backfill 仍需验证证据，不能把 Schema 接受视为历史关联已确定。

## 4. 迁移、备份与幂等验证

迁移版本：三个库各自登记 `phase02a-expand-001`，每库恰一条记录。migration-execution.json 保存本次三库 checksum、备份和执行状态；[idempotency-verification.json](idempotency-verification.json) 保存重复执行结果，三库均为 already_applied。

执行顺序：

1. 检测 Session/Review、Execution、ReportGeneration、TraceRun、LLMCallRecord，五类活跃计数为 0（runtime-active-before.json）。
2. 识别并正常停止唯一后端监听进程 24023，确认 8000 端口已无写服务。
3. 用 SQLite backup API 备份三个库，验证 quick_check 与 foreign_key_check；副本权限 0600，目录 0700，独占创建不覆盖旧备份。测试专门验证已提交但仍在 WAL 的记录包含在备份内。
4. 全部备份成功后，逐库 `BEGIN IMMEDIATE`；FK 实际开启，DDL 与版本行同事务；不用 executescript 或关闭 FK。
5. 核对旧 Schema/记录，重复执行迁移并确认无重复结构或版本；新业务表全部为空。
6. 恢复原后端进程 27711，健康 real/ok；原 Prompt 登记、Admin Trace/Lifecycle 查询正常，未发起新的模型请求。

备份保存在 [本地维护备份目录](/Users/lainey/Desktop/vibe-coding/insightflow/var/backups/phase02a-expand-2026-10-30-01)。其中包含真实业务/请求数据，受本地权限保护，不打入源码档案、不上传外部服务。三个快照在后端停止的协调窗口取得；工具本身不宣称支持分布式原子快照或自动识别所有外部 worker。

迁移失败策略：本库 DDL/版本原子回滚；库间部分成功独立报告，不能声称全局成功。重跑验证已完成库并重试未完成库。若发现人工留下的部分 Schema、错定义、额外触发器、错版本或 checksum，不自动删表、改数据或“认领”为成功，需先人工审查。

## 5. 自动化结果

| 验证 | 结果 | 记录 |
|---|---|---|
| 新增 Expand 测试 | 31 passed | tests-r3.txt；最终代码也包含在完整回归 |
| 完整后端 | **879 passed**，1 个既有 Starlette TestClient 弃用 warning | backend-full.txt |
| 前端 | **67 passed**，9 文件；构建通过 | frontend-tests.txt、frontend-build.txt |
| Admin | **78 passed**，10 文件；类型检查/构建通过 | admin-tests.txt、admin-build.txt |

新增测试覆盖：旧表/记录逐项不变、重复迁移、部分 Schema、列和触发器漂移、错 checksum/无版本、各库事务失败回滚、三库部分完成再运行；Workflow/Root/创建 key 唯一性；两个临时 Workflow 各有 v1；旧版本按原键解析；跨 Session origin/parent/数据引用和跨 Workflow 当前指针/审批链接拒绝；新事实+失败链接的事务整体回滚；只读连接写入拒绝；缺文件不创建数据库；WAL 一致备份与拒绝覆盖；活跃任务阻止维护；原 Root 唯一索引保留；Trace/Registry 链接不得虚构原 Run/Call。

两个 Workflow 场景仅在 pytest 独立临时数据库构造，没有生产创建服务。旧 Session 单流程 API 在 Expand 后继续返回原数据，新增表未成为状态权威。完整后端回归包含原 Root CAS、同 revision 旧回调、Report stale callback、Lifecycle、HITL、Engine 和报告测试，没有降低其断言。

## 6. 生产兼容性核验

[database-compatibility-corrected.json](database-compatibility-corrected.json) 显示：

- 三个库的所有原 Schema 对象定义逐项保留；原 PlanVersion PK、Session 唯一 Root、原唯一约束和不可变触发器仍在。
- 所有原表行数和内容 hash 与维护前一致，未回填、删除或改写历史 payload。
- FK=ON，foreign_key_check 无违例；各库新迁移版本行恰 1 条。
- business_workflows、消息/数据关联、版本仓、所有业务/侧库归属链接、路由和回填记录表均为 **0 行**。

首轮核验脚本直接将 sqlite3.Row 与 tuple 比较，错误地产生 Schema=false；原输出 database-compatibility.json 保留。统一为 tuple 后复核全部旧定义一致，纠正结果另存 corrected 文件，没有重写旧 Schema 或修改 hash 来消除差异。

runtime-verification.json 记录后端健康、三个节点原快照 registered、旧 Lifecycle 一致结果及六个 Session 的新 Workflow 列表均为空。其中默认 `/admin/runs` total=1 指默认 report_generation 筛选，不是全部 Root/Report Run 数量；旧默认 API 语义未改变。

## 7. 运行说明

项目根目录，仅检查、不创建/回填：

```sh
.venv/bin/python backend/scripts/expand_business_workflow.py --data-dir var
```

未来需要执行时，先真正停写/排空，使用一个**全新**备份目录，再显式确认维护窗口：

```sh
.venv/bin/python backend/scripts/expand_business_workflow.py --data-dir var --apply \
  --backup-dir var/backups/NEW-UNIQUE-MAINTENANCE-DIRECTORY \
  --maintenance-window-confirmed
```

不要在当前正常运行的服务旁直接照抄第二条命令；确认参数只是操作者声明，不是替代停写。当前环境已执行完成，不需要为使用前台重复迁移。`--kind` 可用于在核对其他库状态后定向检查/重试，不能用来忽略未完成库并宣称全阶段成功。

只读内部示例（不是新增 HTTP API）：`WorkflowReader(Path('var/insightflow.sqlite3')).list(session_id)` 当前返回空列表；版本查找始终使用 Workflow+版本，legacy locator 从原键读取，不按 Session 最新计划兜底。

## 8. 风险及 Phase 02-B 准入结论

**满足进入 Phase 02-B Backfill 独立评审的结构与回归前置条件；不表示已完成或自动授权 Backfill。**

仍需下一阶段明确：

1. 真实历史归属裁定、缺失/歧义记录及 legacy_mock 只读策略；不能因为新列/链接表存在就推断 verified。
2. 本阶段未实现 Workflow 创建、原生审批/执行/报告事务 writer；单向 FK 不禁止旧业务事实继续出现无新链接。未来 writer 必须同事务提交和核对完整快照/语义幂等，不能用本报告替代该验收。
3. 跨库只具备本地约束和元信息读取，仍需后续证据验证及缺口处理，不提供分布式事务或租约恢复。
4. Schema 不匹配按安全策略拒绝自动修复；需要人工恢复方案。迁移 001 已应用，应冻结，不得原位修改后重算台账；后续 Schema 改动使用新版本。
5. 仍未删除 Session 唯一 Root，未修改旧计划 PK，未开放 1:N，未切换 Session 权威。Switch 的旧 worker 隔离与 fencing 条件只是补充设计，尚未实施。
6. 本轮是数据基础设施验证，不是真实 LLM 业务质量评测；没有改变模型、Prompt、分析算法或 UI。

本轮停止于 Expand，等待后续评审/任务。原需求、设计、源码前后 ZIP、测试和维护记录全部保留；未初始化 Git 或宣称远程备份。
