# Analysis Engine V1 集成

> 后续 HITL V1 已完成真实计划版本、服务端审批和页面到 Engine 接线，见 [HITL V1](hitl-v1.md)。以下 Engine 初次交付记录中的“本阶段”指此前 Engine 开发阶段。

真实执行链路：上传 CSV/XLSX → 指定数据集版本 → 服务端已验证批准快照 → 六类操作链 → ExecutionResultV1 → SQLite。此模块不调用 LLM，不修改 HITL 页面或报告业务逻辑。

## 开发前审查及实施顺序

| 现有能力 | 审查结论 |
| --- | --- |
| 六类内核 | `planning/operations.py` 中 filter_rows / group_aggregate / aggregate / sort_rows / top_n / derive；统一接收 `(frame, params, types)`，返回 DataFrame。已有独立内核和 Validator 测试，保持实现不变。 |
| 参数与能力 | `planning/params.py` 是严格参数 Schema；Registry 的 params_model、handler、propagate 共同定义执行及输出规则。 |
| 上传与版本 | FileStore 保存 `var/uploads/{32位ID}.{csv/xlsx}`；SQLite datasets 保存元数据，dataset_profiles 保存不可变画像。版本是文件 SHA-256、格式、table-v2 解析契约及解析选项的摘要字符串，并非递增整数。 |
| 画像与源文件 | `DatasetProfile.dataset_id` 对应上传文件 ID，fields 按列位置生成稳定 ID；画像记录工作表、表头行、编码、分隔符与文件摘要。 |
| 计划校验 | PlanValidator 接收 AnalysisPlan + DatasetProfile，输出每任务 F0/F1/F2、可执行 ID 和目标覆盖状态；校验通过不等于批准。 |
| HITL | 现有聊天审核使用旧 Mock Plan、会话 JSON、approved_plan_version。不能将该批准记录转换成 V1 的真实执行权限。 |
| 执行结果 | 已有供 Report 使用的 ExecutionResultV1；旧 Mock 另有历史 ExecutionResult。没有真实数据执行服务或执行结果表。 |

按以下顺序实施：复用契约并补充审批/日志 → 抽取已有版本公式并实现真实加载 → 事务认领执行请求 → 调用现有内核、逐任务隔离 → 结果及审批快照持久化 → API/节点适配 → 独立基准、拒绝场景、并发及重启验证。

## 文件改动

新增：

- `backend/app/execution/loader.py`：按数据集 ID 和版本读取真实数据。
- `backend/app/execution/task_runner.py`：调用现有六类内核、记录步骤、序列化完整结果并生成有限预览。
- `backend/app/execution/__init__.py`：业务模块目录。
- `backend/app/profiling/versioning.py`：共享原有版本公式，公式保持不变。
- `backend/app/services/analysis_engine.py`：审批、版本、约束、校验门禁；任务调度与恢复。
- `backend/app/storage/execution_repository.py`：执行记录、完整结果、幂等认领及读取。
- `backend/app/api/executions.py`：执行和查询入口。
- `backend/app/nodes/engine_v1.py`：供后续受控 Workflow 调用的统一 Node 适配器。
- `backend/tests/engine_fixtures.py`、`test_analysis_engine.py`：真实上传、服务端测试批准、独立 Pandas 基准及拒绝场景。
- `backend/scripts/verify_engine.py`：独立临时数据库中的真实文件验证，生成本文链接的执行示例。
- 本文、执行请求 Schema、真实执行示例及验证记录。

修改：

- `domain/execution.py`：扩展已有共享结果模型，添加请求、服务端批准快照、任务元数据、步骤日志和错误。
- `domain/models.py`：在原 SessionState 中增加 engine_approval、engine_execution_ids；兼容 uploaded 来源。
- `profiling/profiler.py`：调用共享版本函数；解析器与统计口径不变。
- `planning/capabilities.py`：更新执行范围描述，六类能力声明和内核不变。
- `main.py`：注册服务、仓库、路由及启动恢复。
- `workflow/orchestrator.py`、`services/plan_review.py`：最小兼容性守卫，拒绝旧 Mock 接口操作带 V1 批准快照的会话。
- `frontend/src/types/contracts.ts`：会话来源联合类型兼容 uploaded；没有修改页面或交互。
- README、现有模块文档中的接入状态说明及共享 JSON Schema。

## Schema 兼容性

继续使用 **ExecutionResultV1.tasks** 和 **ExecutedTask.result**，没有另建 task_results 结果模型。TaskExecutionResult 的要求由现有 ExecutedTask 补全。旧 imported 报告及历史 Mock 会话仍可读取。

新增字段：

- 执行：session_id、execution_request_id、started_at / finished_at / duration_ms、result_view、provenance、errors / warnings。
- 任务：result_id / result_ref、row_count、execution_metadata、error。
- 步骤：step_id、operation、status、input_row_count、output_row_count、duration_ms、warnings、error。
- 结果表：row_offset；字段数上限为 276，兼容 Profiler 的 256 列及最多 20 个派生字段，单元格文本保留实际内容，不按报告展示长度截断。

上述新增结果字段有默认值，旧 imported 契约仍兼容。新 Engine 始终填写版本、任务状态和真实来源。数值必须有限；整数转换可能丢失精度时任务明确失败，不返回四舍五入后的伪精确整数。完整行数是 row_count / total_result_rows；`len(rows)` 只表示当前响应返回的行数。

## 服务端批准与执行门禁

`SessionState.engine_approval` 保存 ApprovedExecutionSnapshot：批准 ID/时间、approved/revoked 状态、ValidatedAnalysisPlan、意图快照、已解决的不确定性 ID、约束审核确认。原 current_plan_version 和 approved_plan_version 必须与批准计划一致。

执行前检查：

1. 会话为 APPROVED，存在有效的服务端 V1 批准快照。
2. 请求计划 ID/版本与快照完全相同，不自动选用其他版本。
3. 会话文件 ID、dataset_ref、计划所指数据版本一致。
4. 意图可 proceed，clarify 项不得存在，defer 项必须已解决；有原始约束时必须经服务端审核确认。
5. 使用保存的真实画像重新运行 Validator，比较校验版本、Registry 版本及逐任务资格；不能信任客户端的 executable 标记。
6. 至少有一个允许执行的任务。
7. 读取真实文件并检查摘要、解析选项、版本及行列结构。
8. 在 SQLite 写事务中再次检查批准状态及会话 revision，防止读取期间发生变更。

**Engine 初次交付时尚无 V1 审批接口；现已通过 HITL V1 的 `/sessions/{id}/approvals` 创建真实服务端快照。旧 Mock 批准仍不能提供真实权限。** 按任务书允许的方式，仅在测试和验证脚本的隔离数据库中构造经过 Validator 的批准快照。后续 HITL 接入必须在服务端保存准确的批准版本、已审核约束与不确定性解决记录；不能让客户端上传一个 approved 标志获得权限。

## API

所有路径以前缀 `/api/v1` 开始，统一错误响应为 `{"error": {"code", "message", ...}}`。无客户端文件路径、计划正文或批准标志输入。

### POST /executions

仅接收：

```json
{
  "session_id": "服务端保存的会话ID",
  "plan_id": "已批准的计划ID",
  "plan_version": 1,
  "execution_request_id": "客户端生成并在重试时复用的唯一请求ID"
}
```

同步返回 ExecutionResultV1；模型字段及完整类型见 [execution-request.schema.json](execution-request.schema.json)、[execution-result.schema.json](execution-result.schema.json)。同一 request_id、同一参数重试返回原执行 ID 和原结果；执行中返回 409 EXECUTION_IN_PROGRESS，details 提供 execution_id。相同 request_id 更换任何参数返回 409 EXECUTION_REQUEST_CONFLICT，不新建执行。

只有首个通过事务认领的请求能够将 APPROVED 改为 RUNNING。不同请求 ID 也不能并发执行同一会话。终态为 COMPLETED 或 FAILED；本阶段不会触发报告生成。

### GET /executions/{execution_id}

默认 `view=preview`：每任务最多前 100 行，全执行预览数据最多约 256 KiB / 100000 单元格。大文本行可能导致 0 行预览，此时完整行数仍真实保存。

`?view=complete`：读取所有已保存任务结果，单任务不超过 5000 行、整个响应不超过 100000 单元格；超限返回 413 FULL_EXECUTION_TOO_LARGE，使用分页接口。该限制不影响完整结果保存。

### GET /executions/{execution_id}/results/{result_id}

`?offset=0&limit=5000`，limit 为 1–5000。返回完整存储结果的一页、row_offset、total_result_rows 和 truncated。result_id 必须属于该 execution_id，不暴露本地文件路径。

供后续内部 Report 使用：`executions.get/complete/get_table(execution_id, ...)` 读取真实结果，`executions.approved_snapshot(execution_id)` 取得当时的计划与意图，画像用结果中的 dataset_id / dataset_version 读取。实际调用 Report 不在本次范围；现有公开报告接口继续只接收 imported，不能通过重新提交 JSON 冒充 engine 来源。

## 执行及存储口径

每个任务从同一版本的原始 DataFrame 独立复制，按步骤顺序执行。字段参数严格通过既有 Schema 与 Registry 规则；只调用注册的内核函数，没有 eval、自由 Python 或 SQL。F0 任务保留为 skipped 及原因；F1 只执行已经存在的显式派生链。

执行状态由任务实际结果汇总：全部成功为 success，部分成功为 partial_success，无成功任务为 failed。空结果仍为 success。错误绑定任务及步骤 ID，未运行步骤不伪造日志。完成最终序列化前若发生错误，不保存部分统计结果为成功。

有效样本量按最终指标的非缺失参与数记录在 metric_valid_counts；各指标样本数不同时，valid_sample_count 为 null，避免给出含混的统一分母。effective_row_count 为首次聚合前记录数；未聚合时为结果保留记录数，不等于分页返回行数。

SQLite 新增：

- `executions`：全局唯一 request_id、原请求、会话引用、开始时间、不可变批准快照、逐任务持久进度、最终标准结果。
- `execution_results`：按 execution_id 绑定的完整任务结果 JSON、字段定义、真实结果行数。

每个任务的完整结果及进度在同一事务保存；最终结果和会话终态也在同一事务更新。返回响应丢失后可用相同请求 ID 读取原结果。服务重启保留已写入的成功结果，未完成任务标记 EXECUTION_INTERRUPTED，不自动重新计算，原请求继续返回该终态。

## 数据存储和版本风险

- 文件内容和解析选项共同决定版本；不能只凭文件名或最新画像加载数据。共享的 table-v2 公式保持不变；未来改变解析规则必须升级契约，不能静默复用旧版本。
- 数据集画像不可变，文件被替换、删除、摘要不符、指定版本不存在均明确报错。旧画像的不同表头选项不会被最新选项覆盖。
- 使用现有单进程本地部署。启动恢复会处理 running 记录，因此不要开多个 Uvicorn workers，也不要在同一数据目录并行运行多个后端实例。
- SQLite 中逐任务完整结果采用 JSON 保存；分页按已保存 JSON 切片，尚未实现流式执行、后台任务或大数据分页索引。沿用上传 10 MB、10 万行、200 万单元格上限。
- 本地单用户应用不引入账户权限系统；这里的权限校验是批准状态与版本门禁，不宣称实现了多用户身份隔离。

## 自动化及真实执行验证

在 backend 目录：

```bash
../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/verify_engine.py
```

本次验证：后端 **359 项通过**（新增 Engine 集成测试 50 项），前端 **14 项通过**，生产构建通过；80 个 Python 模块未检测到导入循环。后端保留现有 Starlette TestClient 依赖弃用提示，不影响结果。

新增测试覆盖真实 CSV / XLSX 上传、指定工作表与表头、旧解析版本读取、filter → group_aggregate → sort → top_n、全部七类聚合、两种日期派生、无效批准 / 版本 / 约束 / 不确定性 / 操作拒绝、单任务和全部失败、空结果、任务视图隔离、预览与完整结果分页、大文本及整数精度、并发幂等、重启恢复和 Report 输入兼容。

真实样例见 [ExecutionResult](engine-execution.example.json) 和 [验证记录 / 批准计划 / Pandas 基准](engine-verification.json)。运行脚本读取实际 examples/sales.csv、通过上传 API 保存文件及画像，在临时数据库保存测试批准，调用执行 API，重新打开数据库验证持久化，重复请求验证幂等。示例是计算结果，不是 Mock 数值；**批准快照为明确标记的测试夹具**。临时数据库结束后删除，文档示例 ID 不是当前服务器可查询的资源。

本次文件共 12 条、4 列：

| 任务 | 操作链 | 输入/输出行数 | 完整结果 |
| --- | --- | --- | --- |
| A01 | filter → group_aggregate → sort → top_n | 12→9→2→2→1 | 华东，record_count=6，sales_total=157000 |
| A02 | aggregate | 12→1 | sales_total=263000，record_count=12 |

两任务与独立 Pandas 计算一致；保存后读取、重新创建应用读取、同 ID 重试均一致。未调用 LLM、未修改报告、未让未批准计划执行。

## 后续未完成项

V1 计划持久化、任务删除重新校验、真实 HITL 审批及 Engine 接线已完成，详见 HITL V1 文档；LLM 自然语言修订与调用 ReportModuleNode 的完整用户流程仍待后续阶段。当前已具备可独立验证的真实 Engine 服务 / API / Workflow 节点适配与结果读取能力，不能把旧聊天的 Mock 演示称为完整真实分析体验。
