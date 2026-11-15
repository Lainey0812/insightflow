# Evaluation Admin v1 设计（Phase 2-A）

- 需求：REQ-0146（评测平台 Phase 2-A：Admin 架构设计与实施规划）。
- 性质：只设计，不编码。本文所有“现状”均来自对仓库的实际读取（2026-11-13），每条结论附代码位置或命令依据。
- 状态：等待架构审核。审核前不进入 Phase 2-B。

---

## 0. 结论摘要

1. 评测内核（`backend/app/evaluation`）已经能把三种历史运行读成统一契约：`read_run()` + `trusted_metrics()`。但仓库里**没有跨目录的运行索引，也没有数据集注册表**。这两项是 Phase 2-B 必须新增的。
2. Admin 后端的约定是 `create_admin_router` 挂载在 `/admin` 与 `/api/v1/admin` 两处，前端默认 Base URL 是 `/api/v1/admin`。候选路径 `/api/admin/evaluations/...` 与现行约定不符，建议改为 `/api/v1/admin/evaluations/...`。同时要避开已占用的 `/admin/runs`（Trace 运行）。
3. Golden 运行的 `<case>/trace.json` 就是 `workflow-observability-v1` 结构，与 `WorkflowDetailPage` 渲染的对象完全相同，可以直接复用图与节点详情组件。前提是增加“离线证据模式”：关闭按 `call_id`/`span_id` 回查主库的请求，因为这些 ID 属于运行目录里的隔离库，主库查不到。
4. 评测页面一律放在 `/evaluations/*` 下，不放进 `/traces/*`。原因：`/traces/:runId` 是捕获式路由；`/traces` 已按 REQ-0126 重定向到 `/traces/workflows`，因此遗留的 10 个前端测试至今仍红。本阶段不改动 `/traces` 路由。
5. 冻结状态：仓库里不存在任何“冻结”声明记录。Golden Set 文件没有 `version` 字段；TC 套件只有文件哈希清单。按需求要求，所有数据集一律显示“未声明冻结”，不推断为 Frozen。
6. Phase 1 契约缺口：Agent Version 恒为空、Golden 没有 Dataset Version、尚无任何真实的新格式 Golden 运行、TC 的 Trace 只存在于运行目录内的 SQLite。详见第 9 节。缺口一律显示为“未记录”，不伪造。

---

## 1. 现有代码审查与复用矩阵

### 1.1 读取依据

| 范围 | 文件 |
|---|---|
| 路由与导航 | `admin/src/app/routes.tsx`、`admin/src/app/navigation.ts` |
| Golden Set 页 | `admin/src/pages/GoldenSetPage.tsx`、`admin/src/features/evaluations/golden-set.json` |
| Evaluation Runs 占位 | `navigation.ts` 中 `evaluation-runs` 未设 `enabled`，由 `ModulePlaceholderPage` 渲染 |
| 回归对比 | `RegressionsPage.tsx`、`RegressionDetailPage.tsx`、`api/regression.ts`、`types/regression.ts`、`backend/app/services/regression_runs.py` |
| Workflow Trace | `WorkflowsPage.tsx`、`WorkflowDetailPage.tsx`、`api/workflows.ts`、`features/workflows/*`、`features/traces/*`、`TraceDetailPage.tsx`、`TracesPage.tsx` |
| Bad Case | `BadCasesPage.tsx`、`BadCaseDetailPage.tsx`、`backend/app/services/bad_cases.py` |
| 后端 Admin API | `backend/app/api/admin.py`（349 行）、`backend/app/main.py:140-155`、`backend/app/api/errors.py`、`backend/app/domain/errors.py` |
| 评测内核 | `backend/app/evaluation/{contracts,runs,integrity,metrics,aggregate,golden_run,manifest}.py` |
| 前端请求 | `admin/src/api/client.ts`、`admin/src/config/env.ts`、`admin/vite.config.ts` |

### 1.2 复用矩阵

| 现有模块 | 当前能力 | 可复用部分 | 需要新增 | 潜在冲突 |
|---|---|---|---|---|
| `routes.tsx` / `navigation.ts` | 导航驱动路由；`evaluation-runs` 是占位；`currentNavigation()` 按前缀高亮 | `AccessBoundary permission="evaluations:view"`；导航分组“评测中心” | `/evaluations/runs`、`/evaluations/runs/:runId`、`.../cases/:caseId`、`.../cases/:caseId/trace`、`/evaluations/datasets/:datasetId`；`currentNavigation()` 增加 `/evaluations/runs/` 与 `/evaluations/datasets/` 前缀 | `/traces/:runId` 会捕获 `/traces/` 下任何未知子路径；评测页不得放在 `/traces/*` |
| `GoldenSetPage` | 渲染打包进前端的 `golden-set.json` 副本（sha256 `fe52a92c…`，与 docs 原件字节相同） | 9 行表格与 5 条用例表格，原样作为 Golden 数据集详情的“内容”区 | 数据集列表页；详情改为从 API 取元数据（ID、哈希、冻结状态、关联运行） | 打包副本与原件可能漂移；页面文案写着“冻结内容”，但没有冻结证据（见 4.1） |
| Evaluation Runs 占位 | 只有说明文字 | 导航项与权限 | 整页 | 无 |
| `RegressionsPage` / `RegressionDetailPage` + `RegressionRunService` | TC 运行列表、详情、两次运行对比；`RUN_ID` 正则白名单；`AppError` 404；隔离库的 `workflow_id` 显示为不可点击文本 | ID 正则与“只按白名单解析目录”的做法；`workflow_id` 不链接主库的展示先例；TC 原始详情页作为 Case Detail 的“查看原始回归记录”入口 | 无（列表与对比保持原样） | 两处都会展示 TC 运行，必须说明关系：回归对比看 TC 原始检查项，Evaluation Runs 看统一契约投影。不合并、不删除 |
| `WorkflowDetailPage` + `NodeKindDetail` 等 | 用 `workflowApi.get()` 拉取 `workflow-observability-v1`，渲染节点图与节点详情 | 图（`GraphNode`、`flattenSpans`）、`NodeKindDetail`、`StatusBadge`、`presentation.ts`；`isWorkflow()` 结构校验可直接校验 `trace.json` | 把“取数”和“渲染”拆开：抽出 `WorkflowTraceView({view, mode})`；`mode='evidence'` 时禁用远程请求 | `LlmCallDetail` 用 `call_id` 调 `promptApi.raw*`；`NodeInspector` 用 `span_id` 调 `traceApi.events`；`LifecyclePanel` 用 `session_id` 调 `lifecycleApi`。评测运行的 ID 属于运行目录里的隔离库，回查主库会得到 404 或错误归属 |
| `TracesPage` / `TraceDetailPage` / `TraceComparisonPage` | Run Explorer（报告 Trace），已从导航移除（REQ-0126）；`/traces` 重定向到 `/traces/workflows` | 无 | 无 | `traces.test.tsx`（9 个）与 `comparison.test.tsx`（1 个）仍以 `/traces` 为 Run Explorer 入口，当前红（实测 10 failed / 109 passed）。属既有问题，本阶段不改 |
| `BadCasesPage` / `BadCaseDetailPage` | 列表、筛选、`limit/offset` 分页（≤100）、按 `workflow_id` 过滤 | 分页参数约定；空状态与错误展示 | 无（本阶段不做 Bad Case 回流） | Bad Case 绑定主库 `workflow_id`；评测运行的 `workflow_id` 在隔离库，不可混用 |
| `client.ts` / `env.ts` | 统一 Base URL（默认 `/api/v1/admin`）、路径不得越出 Base、超时、`ApiError` 分类、HttpOnly Cookie | 全部复用 | 新增 `api/evaluations.ts`，并像 `regression.ts` 一样做运行时结构校验 | 无 |
| `AccessPanel` / `TraceError` | 403 时提供凭证交换；503 等不当作空数据 | 直接复用 | 无 | 无 |
| `admin.py` `create_admin_router` | 统一鉴权依赖 `protected`（Header 或签名 Cookie，`Cache-Control: no-store`）；服务注入（`regression_runs=`、`replay_runs=`）；服务缺失时返回 503 | 鉴权、注入模式、503 语义 | 注入 `evaluation_admin=` 服务；新增 6 个 GET 路由 | `/admin/runs*` 已是 Trace 运行，新路由必须在 `/evaluations/` 前缀下 |
| `errors.py` | `AppError` → `{"error":{code,message,details}}`；422 统一为 `VALIDATION_ERROR`（不回显输入）；未知异常 → 500 `INTERNAL_ERROR` | 全部复用 | 新错误码（见 4.2–4.6） | 无 |
| `evaluation/runs.py` | `read_run(run_dir)` 按目录名前缀分派 gf_/rg_；`trusted_metrics(view)`；三种格式都返回 `RunView` | 完整复用，不改投影逻辑 | 运行索引（发现、去重、缓存）；Case 级视图组装 | `read_run` 每次调用都会重算所有文件哈希（`verify_recorded`），列表页需要缓存 |
| `evaluation/integrity.py` | `contained_path()` 拒绝绝对路径、`..`、反斜杠、NUL、符号链接越界；`verify_recorded()` | 证据读取时的路径约束直接复用 `contained_path` | 无 | 无 |
| `evaluation/metrics.py` | 各类比率，分母为 0 时返回 None；按 Evaluator 统计 `error_rate` | 全部复用 | 无 | 无 |
| `evaluation/aggregate.py` | E2E Hard Gate，产出 `gate` 与 `reason` | 用 `gate` 推导“失败归属”（见 6.3） | 推导函数（展示层），不写回记录 | 无 |

### 1.3 `/traces` 冲突分析（不改路由）

- 现状（`routes.tsx:37-41`）：`/traces` → 重定向 `/traces/workflows`；`/traces/detail` → 重定向；`/traces/workflows/:workflowId`；`/traces/compare`；`/traces/:runId`（报告 Trace 详情，捕获式）。
- REQ-0126「运行追踪只留 Workflow 图与节点详情」移除了 Run Explorer 的导航入口，但 `pages` 映射里仍保留 `run-explorer: TracesPage`，相关测试也未更新，因此 10 个测试失败。
- 对本设计的约束：
  1. 评测 Trace 入口放在 `/evaluations/runs/:runId/cases/:caseId/trace`，不放在 `/traces/*` 下，避免被 `/traces/:runId` 捕获，也避免把隔离库的 workflow 混进日常 Workflow 列表。
  2. 不链接到 `/traces/workflows/:workflowId`：Golden/TC 的 `workflow_id` 只存在于运行目录内的隔离库，主库查不到。沿用 `RegressionDetailPage` 的先例，显示为纯文本并注明“属于本次评测的隔离库”。
  3. 修复 REQ-0126 遗留测试是另一项工作，需要单独立项。

---

## 2. 页面信息架构

### 2.1 路由与跳转

```
/evaluations/datasets                      数据集列表（替换现 GoldenSetPage 的入口位置）
  └─ /evaluations/datasets/:datasetId      数据集详情（Golden 详情内含现有 9 行与 5 条用例表格）
        └─ 关联运行行 → /evaluations/runs/:runId
/evaluations/runs                          Evaluation Runs（Golden + TC 统一列表）
  └─ /evaluations/runs/:runId              Run Detail（运行概览 + Case Results）
        ├─ 数据集链接 → /evaluations/datasets/:datasetId
        ├─ TC 运行 → “原始回归记录” → /evaluations/regressions/:runId（已有页面）
        └─ /evaluations/runs/:runId/cases/:caseId          Case Detail
              └─ /evaluations/runs/:runId/cases/:caseId/trace  证据 Trace（离线证据模式）
/evaluations/regressions                   回归对比（保持不变）
```

- `:datasetId` 使用 API 返回的不透明 `dataset_key`（见 4.1），不直接使用文件名。
- 返回链接遵循现有 `wf-back` 模式；筛选与分页写入 URL（与 `BadCasesPage` 一致）。

### 2.2 Dataset List / Detail

列表列：Dataset ID、Dataset Version、类型（golden / tc_suite）、Case 数量、内容哈希（前 8 位，悬停显示全文）、冻结状态、关联运行数。

详情区块：

1. 元数据：ID、版本、类型、Case 数量、`content_sha256`、来源（仓库相对路径，非绝对路径）。
2. 冻结状态：只有存在冻结声明记录时才显示 Frozen。当前一律为“未声明冻结”，并说明“历史静态数据不能推断为正式发布版本”。
3. 内容：Golden 复用现有 9 行表格与 5 条用例表格；TC 展示 15 条用例的 ID、标题、`test_mode`、`execution_status`（来自 `cases.json`）。
4. 关联运行：按 `dataset_id` 匹配的运行，带一列“哈希一致性”：运行记录的 `dataset_hash` 与当前文件哈希相同、不同或运行未记录。哈希不同时提示“该运行使用的内容与当前文件不同”。

### 2.3 Evaluation Runs

列：Run ID、Run Type（Golden / TC）、Agent（`agent_id` + `agent_version`，为空时显示“未记录”）、Dataset、Created At、Run Lifecycle、Integrity、E2E 确认成功率（`PASS/valid`，附分子分母）、已评判 Case 数（`PASS+FAIL` / started）、数据来源（新记录 / 历史投影）。

列表“综合状态”只是导航提示，各列仍独立展示。按以下优先级取第一个命中：

| 优先级 | 条件 | 文案 |
|---|---|---|
| 1 | 运行目录不可读 | 无法读取 |
| 2 | lifecycle = INCOMPLETE | 运行未完成 |
| 3 | integrity = INVALID | 证据不可信（指标仅含已验证 Case 或不显示） |
| 4 | integrity = UNVERIFIED | 历史数据，完整性无法验证 |
| 5 | FINISHED + VERIFIED，且存在非 PASS 的 E2E | 完成，有失败或无法评判 |
| 6 | FINISHED + VERIFIED，全部 PASS | 完成，全部通过 |

筛选：`run_kind`、`integrity`、`lifecycle`、`dataset_id`、`provenance`。排序：`created_at`（默认降序）、`run_id`。

### 2.4 Run Detail

运行概览：

- 配置：数据集（链接 + 哈希一致性）、模型、`source_fingerprint`、审批策略、Evaluator 清单（id、version、requirement、`config_sha256` 前 8 位）。历史运行显示“历史运行未记录 Evaluator 清单”。
- 完整性：状态 + `reasons`；INVALID 时列出不一致文件（manifest 中的相对 ref，不给绝对路径）。
- 指标：见第 6 节，每个比率都显示分子与分母。
- Case 状态分布：Execution Status 计数与 E2E Verdict 计数分开显示；单独列出未开始的 Case（TC 的 `not_started_case_ids`）与缺失的 Case（`missing_case_ids`）。

Case Results 表：Case ID、Execution Status（含 `blocking_stage`）、E2E Verdict + Gate、失败归属（推导，见 6.3）、Required Evaluator Results（逐个 id: verdict 徽标）、Case Integrity、来源（新记录 / 历史投影）。

### 2.5 Case Detail

| 区块 | 新格式 Golden（recorded） | 历史 Golden（legacy_projection） | TC（legacy_projection） |
|---|---|---|---|
| 用户任务 / 测试目标 | Golden Set 中该用例的 `user_input`、`oracle`、`must_execute`、`must_forbid`；仅当运行的 `dataset_hash` 等于当前文件哈希时才展示，否则显示“无法确认运行时内容” | 同左 | `cases.json` 中的 `title`、`user_query`、`expected`；同样以 `cases_sha256` 校验 |
| 执行结果 | `CaseExecution` 全字段 + `projection.execution_status` 推导依据 | 同左（`unverified` 字段标注“历史未记录”） | 同左 + `expect_blocked` 推导依据 |
| Oracle 结果 | `insightflow.golden.oracle` 结果 | `insightflow.golden.score_case`（历史投影，`legacy` 原值可展开） | 无 Oracle；显示 `insightflow.tc.checks` 与逐项 checks |
| MustForbid 结果 | `insightflow.golden.must_forbid`：verdict、failure_code、reason、evidence_refs；reason 按 `;` 拆成条目 | 显示“历史运行未执行此 Evaluator”（不是 NOT_EVALUATED） | 不适用 |
| Node Fidelity | optional 结果，注明“不影响 E2E” | 显示“未记录” | `legacy.fidelity` 原值（若有），标注历史 |
| Hard Gate | `E2ESummary.gate` + `reason` + `required_verdicts` / `optional_verdicts` | 同左（由投影重算，标注“历史投影”） | 同左 |
| Evidence References | 每个 ref 的类型、是否可读取、完整性（manifest 校验结果） | 同左；完整性一律为 UNVERIFIED | 同左 |
| Plan / Engine 证据 | `observed.plan`、`observed.execution_steps`、`observed.result_tables`、`observed.profile` | 历史 result.json 无 plan / result_tables，显示“历史运行未保存” | `plan`（摘要）、`execution_steps`、`result_tables`（来自 run.json 的 case 记录） |
| Trace 入口 | `<case>/trace.json` → 证据 Trace 页 | 同左 | Trace 在运行目录 SQLite 内，见决策问题 Q3；默认显示“未开放” |

每个区块右上角显示数据来源徽标：`新记录` / `历史投影`；投影值可展开 `Derivation.sources` 与 `basis`。

### 2.6 证据 Trace（离线证据模式）

- 数据来自 `GET .../cases/{case_id}/evidence?kind=trace`，内容是脱敏后的 `workflow-observability-v1`。
- 前端用现有的 `isWorkflow()` 校验，再交给抽出的 `WorkflowTraceView` 渲染（图 + `NodeKindDetail`）。
- `mode='evidence'` 时：
  - 不调用 `promptApi.raw*` / `traceApi.events` / `lifecycleApi`，原位显示“该 Trace 来自评测运行的隔离存储，原始快照不在主库，未开放查看”；
  - 页头显示 `workflow_id` 纯文本 + “隔离库”说明，不生成任何可点击的 `/traces/workflows/...` 链接；
  - 没有 `trace.json`（`trace_ref` 为空）时，显示“本 Case 未保存 Trace”，不构造 workflow_id。

---

## 3. 后端模块划分与数据流

### 3.1 模块

| 模块（新增） | 职责 |
|---|---|
| `app/evaluation/run_index.py` | 按配置的根目录列出 `gf_*` / `rg_*` 目录（仅接受正则匹配的目录名，拒绝符号链接越界）；同一 `run_id` 出现在多个根时标为冲突；为每个运行缓存 `RunView`，缓存键为关键文件的 `(size, mtime_ns)` |
| `app/evaluation/datasets.py` | 从配置的数据集源（Golden 文件、TC `cases.json`）读取元数据并计算 `content_sha256`；运行中出现但没有对应源文件的数据集记为 `referenced_only` |
| `app/evaluation/admin_views.py` | Pydantic 响应模型（`extra='forbid'`）与由 `RunView` 组装视图的纯函数；不读文件 |
| `app/evaluation/evidence.py` | 按 `kind` 白名单读取证据：先解析运行目录（来自索引），再用 `contained_path` 校验相对 ref，读取后经脱敏器与大小限制处理 |
| `app/services/evaluation_admin.py` | 组合以上模块；分页、筛选、排序；把 `RunNotReadable` 等转成 `AppError` |
| `app/api/admin.py`（修改） | `create_admin_router(..., evaluation_admin=None)`；注册 6 个 GET 路由；服务缺失时返回 503 |
| `app/main.py`（修改） | 按配置构造 `EvaluationAdminService` 并注入 |
| `app/core/config.py`（修改） | 新增评测根目录与数据集源配置（见 7.1） |

现有 `read_run` / `trusted_metrics` / `summarize` / `compute` / `contained_path` 一律复用，不改投影逻辑。

### 3.2 数据流

```
配置的根目录 ──► run_index.scan()（目录名白名单 → 映射 run_id → 目录句柄）
                    │  缓存（按文件 size + mtime）
                    ▼
            runs.read_run(dir) ──► RunView（契约对象，含 integrity）
                    │                 │
                    │                 └─► trusted_metrics(view, oracle_evaluator_id)
                    ▼
       admin_views.run_summary / run_detail / case_detail（纯函数，标注来源）
                    ▼
       EvaluationAdminService（分页、筛选、错误映射）
                    ▼
       /api/v1/admin/evaluations/*（鉴权依赖 protected，Cache-Control: no-store）
                    ▼
       admin/src/api/evaluations.ts（运行时结构校验）──► 页面
```

证据读取：`run_id` → 索引查目录（不拼接字符串）→ `case_id` 必须属于该运行的 `case_execution_refs` → `kind` 映射到固定的相对 ref（例如 `trace` → `CaseExecution.trace_ref`）→ `contained_path` → 读取 → 脱敏 → 截断 → 返回。

---

## 4. API 契约

### 4.0 公共约定

- 前缀：`/api/v1/admin/evaluations`（同时会出现在 `/admin/evaluations`，这是现有双挂载的副作用，前端只用前者）。
- 鉴权：复用 `protected`；未配置 → 503 `ADMIN_NOT_CONFIGURED`；凭证无效 → 403 `ADMIN_ACCESS_DENIED`。
- 响应头：`Cache-Control: no-store`（来自现有依赖）。
- 所有路径类字段只返回运行目录内的相对 ref（如 `RF-02/result.json#observed.plan`）或仓库相对 ref（如 `docs/testing/typical-suite-v1-2026-11-09/cases.json`），不返回绝对路径。
- 每个对象带 `provenance`（`recorded` / `legacy_projection`）；历史缺失的字段为 `null`，并列入 `unverified`；推导值放在 `projection`，附 `sources` 与 `basis`（原样来自契约）。
- 分页：`limit`（1–100，默认 20）、`offset`（≥0），响应带 `total`、`limit`、`offset`（与 `/admin/runs`、`/admin/bad-cases` 一致）。
- 错误体：`{"error":{"code","message","details"}}`。

### 4.1 `GET /evaluations/datasets`

Query：`kind`（`golden` / `tc_suite`，可选）、`limit`、`offset`。

```json
{
  "schema_version": "evaluation-dataset-page-v1",
  "items": [
    {
      "dataset_key": "golden:requirement-fidelity-golden-v1",
      "dataset_id": "requirement-fidelity-golden-v1",
      "dataset_version": null,
      "kind": "golden",
      "case_count": 5,
      "content_sha256": "fe52a92cc77bb16fa5425f5618c7d7a9dd633f0790eaf341a3c434554a052142",
      "source_ref": "docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json",
      "freeze": {"status": "NOT_DECLARED", "evidence": [], "notice": "未找到冻结声明记录；不推断为正式发布版本。"},
      "run_count": 2,
      "unverified": ["dataset_version"]
    },
    {
      "dataset_key": "tc_suite:typical-suite-v1",
      "dataset_id": "typical-suite-v1",
      "dataset_version": null,
      "kind": "tc_suite",
      "case_count": 15,
      "content_sha256": "4536f389d92ed41dbefae1df1fb58885f834c60661f1d941eb41c9342873c88a",
      "source_ref": "docs/testing/typical-suite-v1-2026-11-09/cases.json",
      "freeze": {"status": "NOT_DECLARED", "evidence": [], "notice": "套件附带文件哈希清单 manifest.json，但这是完整性记录，不是冻结声明。"},
      "run_count": 1,
      "unverified": ["dataset_version"]
    }
  ],
  "total": 2, "limit": 20, "offset": 0
}
```

`freeze.status` 取值：`FROZEN`（存在冻结声明，且声明的哈希等于当前文件哈希）、`DECLARED_MISMATCH`（有声明但哈希不同）、`NOT_DECLARED`。当前仓库没有任何声明，因此全部为 `NOT_DECLARED`。声明格式待产品决策（Q2）。

### 4.2 `GET /evaluations/datasets/{dataset_key}`

`dataset_key` 必须匹配 `^(golden|tc_suite):[A-Za-z0-9._-]{1,80}$`，并且只在数据集注册表中查找，不拼接路径。

```json
{
  "schema_version": "evaluation-dataset-v1",
  "dataset": { "...同列表项..." },
  "content": {"kind": "golden", "columns": ["编号","城市","岗位名称","岗位类型"], "row_count": 9,
              "cases": [{"case_id": "RF-01", "user_input": "对比上海和深圳的岗位数量，排除实习岗位。", "oracle": {"上海": 3, "深圳": 1}}]},
  "runs": [
    {"run_id": "gf_20261112-143406_cde1fd", "run_kind": "golden", "created_at": "2026-11-12T14:34:06.698918+00:00",
     "dataset_hash": "fe52a92c…", "hash_match": "match", "integrity": "UNVERIFIED", "provenance": "legacy_projection"}
  ]
}
```

`hash_match`：`match` / `mismatch` / `not_recorded`。数据集未知 → 404 `EVALUATION_DATASET_NOT_FOUND`。源文件不可读 → 200，`content: null`，并带 `content_error: "source_unreadable"`（元数据中仍保留运行引用）。

### 4.3 `GET /evaluations/runs`

Query：`run_kind`、`integrity`（四值之一）、`lifecycle`（`FINISHED` / `INCOMPLETE`）、`dataset_id`、`provenance`、`sort`（`created_at` / `-created_at` / `run_id`，默认 `-created_at`）、`limit`、`offset`。非法枚举 → 422。

```json
{
  "schema_version": "evaluation-run-page-v1",
  "items": [
    {
      "run_id": "gf_20261112-143406_cde1fd",
      "run_kind": "golden",
      "provenance": "legacy_projection",
      "agent": {"id": null, "version": null},
      "dataset": {"id": "requirement-fidelity-golden-v1", "version": null, "hash": "fe52a92c…", "dataset_key": "golden:requirement-fidelity-golden-v1"},
      "created_at": "2026-11-12T14:34:06.698918+00:00",
      "finished_at": "…",
      "lifecycle": "FINISHED",
      "integrity": {"status": "UNVERIFIED", "reasons": ["legacy_run_has_no_manifest"]},
      "list_state": "HISTORICAL_UNVERIFIED",
      "counts": {"started": 5, "not_started": 0, "missing": 0, "valid": 5, "decided": 5, "e2e": {"PASS": 2, "FAIL": 3}},
      "e2e_confirmed_success": {"numerator": 2, "denominator": 5, "rate": 0.4, "trust": "unverified"},
      "unverified": ["agent_id", "agent_version", "dataset_version", "evaluator_manifest"]
    }
  ],
  "unreadable": [{"run_id": "gf_…", "reason": "run_not_readable"}],
  "conflicts": [],
  "total": 3, "limit": 20, "offset": 0
}
```

- `trust` 取值：`verified`（VERIFIED）、`partial_verified`（INVALID，只含已验证 Case）、`unverified`（UNVERIFIED）、`incomplete`（INCOMPLETE）、`none`（INVALID 且没有可信 Case，此时比率为 null）。
- `list_state` 取值：`UNREADABLE` / `INCOMPLETE` / `EVIDENCE_INVALID` / `HISTORICAL_UNVERIFIED` / `FINISHED_WITH_ISSUES` / `FINISHED_ALL_PASS`，规则见 2.3。
- 不可读的运行目录不会让整页失败，而是进入 `unreadable`。同一 `run_id` 出现在多个根时进入 `conflicts`，两份都不展示详情。

### 4.4 `GET /evaluations/runs/{run_id}`

`run_id` 必须匹配 `^(gf|rg)_\d{8}-\d{6}_[0-9a-f]{6}$`，否则 404（与 `RegressionRunService` 一致，不给出“格式错误”的提示，避免探测）。

```json
{
  "schema_version": "evaluation-run-detail-v1",
  "run": { "...EvaluationRun 原样（integrity.files 中 ref 为相对路径）..." },
  "evaluators": null,
  "evaluators_notice": "历史运行未记录 Evaluator 清单",
  "metrics": {
    "trust": "unverified",
    "included_case_ids": ["RF-01","RF-02","RF-03","RF-04","RF-05"],
    "excluded": [],
    "e2e_confirmed_success_rate": {"numerator": 2, "denominator": 5, "rate": 0.4},
    "decidable_pass_rate": {"numerator": 2, "denominator": 5, "rate": 0.4},
    "evaluation_coverage": {"numerator": 5, "denominator": 5, "rate": 1.0},
    "execution_completion_rate": {"numerator": 2, "denominator": 5, "rate": 0.4},
    "evaluator_error_rate": {"insightflow.golden.score_case": {"numerator": 0, "denominator": 5, "rate": 0.0}}
  },
  "distribution": {"execution": {"COMPLETED": 2, "BLOCKED": 2, "FAILED": 1}, "e2e": {"PASS": 2, "FAIL": 3}},
  "cases": [
    {"case_id": "RF-04", "execution_status": "FAILED", "blocking_stage": "…", "failure_origin": "agent",
     "e2e": {"verdict": "FAIL", "gate": "task_condition", "reason": "task_not_completed:FAILED"},
     "failure_attribution": {"value": "agent_execution", "basis": "E2E gate task_condition"},
     "required_results": [{"evaluator_id": "insightflow.golden.score_case", "verdict": "NOT_EVALUATED", "reason": "no_engine_result"}],
     "integrity": "UNVERIFIED", "provenance": "legacy_projection"}
  ],
  "links": {"regression_view": null}
}
```

示例取自历史运行 `gf_20261112-143406_cde1fd` 的实际读取结果。新格式运行的 `evaluators` 为 config 中的清单（id、version、requirement、config_sha256）。比率的分子与分母来自 `compute()` 的计数（公式见 6.2），不在 API 层重新定义口径。TC 运行的 `links.regression_view` 为 `"/evaluations/regressions/{run_id}"`（前端路由，不是文件路径）。

错误：404 `EVALUATION_RUN_NOT_FOUND`；409 `EVALUATION_RUN_ID_CONFLICT`（多个根中出现同名运行）；409 `EVALUATION_RUN_UNREADABLE`（目录存在但 `read_run` 无法解析，例如缺少 `run-config.json` 与 `summary.json`）；503 `EVALUATION_ROOTS_UNAVAILABLE`。

### 4.5 `GET /evaluations/runs/{run_id}/cases/{case_id}`

`case_id` 必须匹配 `^[A-Za-z0-9_-]{1,40}$`，并且属于该运行的 Case 集合（包括缺失与未开始的 Case）。

```json
{
  "schema_version": "evaluation-case-detail-v1",
  "run_id": "gf_…", "case_id": "RF-01",
  "case_state": "present",
  "task": {"source": "dataset", "hash_match": "match", "user_input": "…", "oracle": {"上海": 3, "深圳": 1},
           "must_execute": ["…"], "must_forbid": ["…"]},
  "execution": { "...CaseExecution..." },
  "results": {
    "oracle": { "...EvaluatorResult 或 null..." },
    "must_forbid": {"state": "recorded", "result": { "...EvaluatorResult..." }, "reason_items": ["row_set@must_execute[0]:t1:included=J04"]},
    "node_fidelity": {"state": "not_recorded", "result": null},
    "others": []
  },
  "e2e": { "...E2ESummary..." },
  "failure_attribution": {"value": "business_quality", "basis": "E2E gate required_evaluator: insightflow.golden.must_forbid FAIL"},
  "evidence": [
    {"kind": "plan", "ref": "RF-01/result.json#observed.plan", "available": true, "integrity": "ok"},
    {"kind": "trace", "ref": "RF-01/trace.json", "available": true, "integrity": "ok", "size_bytes": 173494}
  ],
  "workflow": {"workflow_id": "wf_…", "store": "isolated_run_store", "linkable": false},
  "provenance": "recorded"
}
```

- `case_state`：`present` / `missing`（配置中有但没有 result.json）/ `not_started` / `unreadable`。非 `present` 时 `execution`、`results`、`e2e` 为 null，并给出原因。
- `results.*.state`：`recorded`（有结果）、`not_recorded`（该运行格式没有这个 Evaluator）、`not_applicable`。`not_recorded` 不能显示为 NOT_EVALUATED。
- 错误：Case 不属于该运行 → 404 `EVALUATION_CASE_NOT_FOUND`；其余同 4.4。

### 4.6 `GET /evaluations/runs/{run_id}/cases/{case_id}/evidence`

Query：`kind`，枚举值：`trace`、`plan`、`engine`、`result_tables`、`profile`、`case_record`。

| kind | 新格式 Golden | 历史 Golden | TC |
|---|---|---|---|
| `trace` | `<case>/trace.json` | `<case>/trace.json` | 不开放（Q3），返回 409 `EVIDENCE_NOT_EXPOSED` |
| `plan` / `engine` / `result_tables` / `profile` | `result.json#observed.*` | 不存在 → 404 `EVIDENCE_NOT_RECORDED` | `run.json#cases[i].plan / execution_steps / result_tables`；无 profile |
| `case_record` | `result.json`（去掉 `observed` 后的契约部分） | `result.json` 原样（脱敏） | case 记录（脱敏） |

```json
{
  "schema_version": "evaluation-evidence-v1",
  "run_id": "gf_…", "case_id": "RF-02", "kind": "trace",
  "ref": "RF-02/trace.json",
  "integrity": {"status": "ok", "expected_sha256": "…", "actual_sha256": "…"},
  "content_sha256": "…",
  "size_bytes": 173494,
  "truncated": false,
  "redactions": [{"path": "trace.llm_calls[*].endpoint", "rule": "url_removed"}],
  "content": { "...脱敏后的 workflow-observability-v1..." }
}
```

- 大小限制：读取前检查文件大小，原始文件超过 2 MiB 返回 413 `EVIDENCE_TOO_LARGE`；脱敏后 JSON 超过 1 MiB 时数组按尾部截断并设 `truncated: true`，同时列出截断路径。现有最大 trace.json 为 173 KB。
- `integrity.status`：VERIFIED 运行给出 manifest 校验结果（`ok` / `mismatch`）；文件为 `mismatch` 时仍可查看，但响应带 `integrity.status = "mismatch"`，前端显示红色“证据被修改”横幅。历史运行为 `unverified`。
- 错误：`kind` 非法 → 422；运行格式没有该证据 → 404 `EVIDENCE_NOT_RECORDED`；ref 越界或不在白名单内 → 404（不区分原因）；JSON 损坏 → 409 `EVIDENCE_UNREADABLE`；未开放 → 409 `EVIDENCE_NOT_EXPOSED`。

---

## 5. 前端组件复用方案

| 新页面 / 组件 | 复用 | 新增 |
|---|---|---|
| `EvaluationDatasetsPage` | `wf-page`、`wf-table`、`EmptyState`、`TraceError` | 列表 |
| `EvaluationDatasetDetailPage` | 从现有 `GoldenSetPage` 抽出 `GoldenCasesTable`、`GoldenRowsTable` | 元数据、冻结状态、关联运行 |
| `EvaluationRunsPage` | 筛选与分页写入 URL 的模式（`BadCasesPage`、`RegressionsPage`）；`timeText`、`durationText` | 状态徽标组（5 种状态各一个组件，见 6.1） |
| `EvaluationRunDetailPage` | `wf-back`、`StatusBadge` 风格 | 指标卡（分子 / 分母 / trust）、分布、Case 表 |
| `EvaluationCaseDetailPage` | `RegressionDetailPage` 的检查项展示（TC checks） | 区块与来源徽标、Derivation 展开 |
| `EvaluationTracePage` | 从 `WorkflowDetailPage` 抽出 `WorkflowTraceView({ view, mode })`；`isWorkflow()`；`NodeKindDetail` | `mode='evidence'` 开关，向下传到 `LlmCallDetail`、`NodeInspector`、`LifecyclePanel` 以禁用远程请求 |
| `api/evaluations.ts` | `createAdminClient()`、`ApiError` | 6 个方法及其结构校验 |

`WorkflowDetailPage` 改为 `workflowApi.get()` → `<WorkflowTraceView mode="live">`。这是唯一触及现有 Trace 页的改动，必须以原有 `workflows.test.tsx` 全部通过为验收条件。

---

## 6. 状态与指标展示规则

### 6.1 五种状态，各自独立显示

| 状态 | 取值 | 来源 | 展示 |
|---|---|---|---|
| Run Lifecycle | FINISHED / INCOMPLETE（索引另有 UNREADABLE） | `EvaluationRun.status` | 运行级徽标 |
| Case Execution | PENDING / RUNNING / WAITING_APPROVAL / COMPLETED / BLOCKED / FAILED / TIMEOUT / CANCELLED / null | `CaseExecution.execution_status` | 带 `blocking_stage`；null 显示“无法确定”，并附推导依据 |
| Evaluator Verdict | PASS / FAIL / NOT_EVALUATED / EVALUATOR_ERROR，另有展示态“未记录” | `EvaluatorResult.verdict` | 每个 Evaluator 一个徽标，并标 required / optional |
| E2E Verdict | PASS / FAIL / NOT_EVALUATED / EVALUATOR_ERROR / INFRA_ERROR | `E2ESummary.verdict` + `gate` | 徽标 + gate 文本 |
| Integrity | VERIFIED / INVALID / INCOMPLETE / UNVERIFIED | `IntegrityReport.status` / `case_status` | 运行级与 Case 级分别显示 |

不提供合并后的单一 Success / Failure 字段。

### 6.2 指标（全部来自 `trusted_metrics` → `compute`）

| 指标 | 公式 | 含义 |
|---|---|---|
| E2E 确认成功率 | PASS / valid（valid = started − INFRA_ERROR） | 有效样本中端到端确认成功的比例 |
| 可判定样本通过率 | PASS / (PASS + FAIL) | 只看能下结论的 Case |
| 评测覆盖率 | (PASS + FAIL) / valid | 有效样本中能下结论的比例 |
| 执行完成率 | COMPLETED / 已知终态的非基础设施 Case | 与质量无关 |
| Evaluator Error Rate | 每个 Evaluator 的 EVALUATOR_ERROR / 该 Evaluator 的结果数 | 评测基础设施健康度 |

- 分母为 0 时显示“—（无样本）”，不显示 0% 或 100%。
- 每个比率旁都显示 `trust` 标签：只有 `verified` 用正常颜色；`unverified` 用灰色并注明“历史运行，完整性无法验证”；`partial_verified` 注明“已排除 N 条证据不一致的 Case”；`none` 不显示比率。
- 跨运行汇总：Phase 2 不提供（Q4）。列表页只展示单次运行的数值，不做加总或平均。

### 6.3 失败归属（展示层推导，不写回记录）

| E2E gate | 归属 | 文案 |
|---|---|---|
| `infrastructure` | `evaluation_infrastructure` | 运行器或模型服务失败，不计入 Agent 质量 |
| `task_condition` | `agent_execution` | Agent 未完成任务（拦截、失败、超时） |
| `required_evaluator` + FAIL | `business_quality` | 已执行，但业务结果或约束不满足 |
| `required_evaluator` + EVALUATOR_ERROR | `evaluator_error` | 评测器异常 |
| NOT_EVALUATED（任一 gate） | `undetermined` | 无法评判，附原因 |
| `all_gates` | `none` | — |

API 返回 `failure_attribution.value` + `basis`，前端只负责渲染。

### 6.4 特殊情况

| 情况 | 现状（实测） | 展示规则 |
|---|---|---|
| TC 历史运行无 Manifest | `rg_20261112-133157_f04289`：UNVERIFIED `tc_run_has_no_manifest`；1 条执行，14 条未开始 | 灰色“完整性无法验证”；未开始的 14 条单列，不进入任何分母 |
| 历史 Golden 的 Evaluator Version 为空 | 两个 gf 运行 `evaluator_manifest = null`，结果 `evaluator_version = null` | 显示“历史运行未记录版本”，不填当前版本 |
| Agent Version 为空 | 所有运行（包括新格式 config：`agent.version = None`）都为 null | 显示“未记录”；附 `source_fingerprint`（如有），但不把它当作版本 |
| RF-01、RF-03 的 BLOCKED | `gf_…143406`：BLOCKED → E2E FAIL `task_condition: task_not_completed:BLOCKED`，Oracle NOT_EVALUATED `no_engine_result` | 执行状态 BLOCKED + 拦截阶段；归属 `agent_execution`；Oracle 显示“无执行结果，未评判”，不显示为质量失败 |
| RF-04 的 FAILED | `gf_…143406`：FAILED，`failure_origin = agent` | 同上，归属 `agent_execution` |
| 必选 Evaluator NOT_EVALUATED | 例如 must_forbid 的 `row_set_unverified:…`、`oracle_not_pass:…` | E2E 显示“无法评判”，并逐条列出 reason；不计入通过率分母 |
| INCOMPLETE 运行 | 新格式缺少最终 manifest，或 TC 只有 `run-start.json` | lifecycle 与 integrity 都显示 INCOMPLETE；列出 `missing_case_ids`；比率带“未完成，部分数据” |

---

## 7. 数据完整性与权限边界

### 7.1 根目录与路径

- 配置项（新增，Phase 2-B）：`evaluation_roots`，每项包含 `root_id`、`kind`（`golden` / `tc_regression`）、绝对目录。默认两项：
  1. `golden`：`<repo>/docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs`（`run_golden_fidelity.py` 的输出目录）；
  2. `tc`：`<data_dir>/regression/runs`（`RegressionRunService` 已在用）。
- 根目录启动时解析为绝对路径。注意：当前 `.env` 里 `INSIGHTFLOW_DATA_DIR=../var` 是相对路径，结果取决于启动目录。Phase 2-B 需要在启动日志中记录解析后的根目录（日志只在服务端，不进 API）。
- 运行目录：只接受根目录下一层、名称匹配白名单正则的目录；`resolve()` 后必须仍在根内（拒绝符号链接越界）。请求中的 `run_id` 只用于在索引中查找，永不参与路径拼接。
- 证据：`kind` → 固定的相对 ref → `integrity.contained_path(run_dir, ref)`。
- 只读：不打开运行目录内的任何 SQLite。打开 SQLite 会在历史目录中生成或修改 `-shm` / `-wal` 文件（`gf_…143406/data/insightflow.sqlite3-shm` 的修改时间为 2026-11-13 01:12，说明曾有读取者留下痕迹）。TC 的 Trace 因此默认不开放（Q3）。

### 7.2 脱敏

- 键名规则：递归删除键名匹配 `(?i)(api[_-]?key|authorization|secret|password|token|cookie|credential)` 的值，替换为 `"[redacted]"`，并记入 `redactions`。
- URL：`trace.llm_calls[*].endpoint` 实测为完整的 http(s) URL。改为只保留 scheme 和 host，或整项移除（Q5），并记入 `redactions`。
- 原始快照：`request_snapshot_id` 等只保留 ID，不提供内容（内容在隔离库）。
- 用户输入：Golden 与 TC 的输入都是固定测试集文本，允许显示。`runner_error_message` 等自由文本截断到 500 字符。
- `legacy` 原值：只以白名单字段返回（例如 TC 的 `checks`、`status`、`plan` 摘要），不整体透传。

### 7.3 鉴权

- 复用现有管理员只读凭证与 `evaluations:view` 前端权限。
- 证据 Trace 是否需要额外的快照凭证（`admin_snapshot_token`）待决策（Q5 关联）。默认只用只读凭证，因为脱敏后不含原始请求与响应。

### 7.4 可信展示

- INVALID 运行：比率只基于已验证 Case（`trusted_metrics` 的行为），并显示排除清单；没有已验证 Case 时不显示比率。
- 被篡改的证据可以查看，但带“证据与 manifest 不一致”横幅，且不出现在任何“可信”标签下。
- UNVERIFIED 与 VERIFIED 的运行不在同一个汇总数字中出现（Phase 2 不做跨运行汇总）。

---

## 8. 实施拆分与验收标准

依赖关系：2-B1 → 2-B2 → 2-C1 → 2-C2 → 2-D。每一阶段单独验收、单独归档。

### Phase 2-B1：运行索引与数据集（后端）

- 任务：`run_index.py`、`datasets.py`、配置项、`EvaluationAdminService.list_runs / get_run / list_datasets / get_dataset`；在 admin router 中注册 4 个 GET 路由。
- 验收：
  1. 3 个现有运行（两个 gf、一个 rg）出现在列表中，字段与 `read_run` 一致；列表请求不修改任何历史文件（13 份基线哈希不变，并检查 SQLite 的 `-shm` / `-wal` 修改时间不变）。
  2. `run_id` 路径穿越、非法格式、符号链接越界、同名冲突：分别返回 404 / 404 / 不收录 / 409。
  3. INVALID 与 INCOMPLETE 用临时目录的伪造运行覆盖，`trust` 与 `list_state` 正确。
  4. 两个数据集全部为 `NOT_DECLARED`；`hash_match` 正确。
  5. 响应中不出现绝对路径（测试中断言响应文本不包含仓库根路径）。

### Phase 2-B2：Case Detail 与证据（后端）

- 任务：`admin_views.case_detail`、`evidence.py`（白名单、`contained_path`、脱敏、大小限制）、2 个 GET 路由。
- 验收：
  1. 三种格式的 Case Detail：`not_recorded` 与 NOT_EVALUATED 区分正确；`failure_attribution` 覆盖 6 种 gate。
  2. trace 证据经 `isWorkflow` 等价的结构校验后通过；`endpoint` 已脱敏；`redactions` 非空。
  3. 越界 ref、非法 kind、超大文件、损坏 JSON、被篡改文件分别得到 404 / 422 / 413 / 409 / 200 + mismatch。
  4. 不打开任何 SQLite（测试中用 monkeypatch 让 `sqlite3.connect` 抛错）。

### Phase 2-C1：Dataset、Run List、Run Detail 页面（前端）

- 任务：数据集列表 / 详情（复用 Golden 表格）、Evaluation Runs（启用导航项）、Run Detail；`api/evaluations.ts`；`currentNavigation` 前缀。
- 验收：
  1. 五种状态徽标独立显示；比率显示分子 / 分母 / trust；分母为 0 显示“—”。
  2. 四种列表状态（未完成、有失败、证据不可信、历史无法验证）都有对应的 fixture 测试。
  3. 现有 `golden-set.test.tsx`、`regression.test.tsx`、`navigation.test.tsx`、`routes.test.tsx` 通过；`traces.test.tsx` / `comparison.test.tsx` 的失败数不增加（仍为 10 个既有失败，不在本阶段修复）。

### Phase 2-C2：Case Detail 与证据 Trace（前端）

- 任务：Case Detail 页；从 `WorkflowDetailPage` 抽出 `WorkflowTraceView`；`mode='evidence'` 禁用远程请求；证据 Trace 页。
- 验收：
  1. `workflows.test.tsx` 全部通过（抽取不改变现有行为）。
  2. evidence 模式下渲染 trace fixture 时，`promptApi`、`traceApi.events`、`lifecycleApi` 的调用次数为 0；不出现任何 `/traces/workflows/` 链接。
  3. 新记录与历史投影的来源徽标正确；“未记录”区块不显示为 NOT_EVALUATED。

### Phase 2-D：端到端验收

- 任务：在本机 5174（Admin）+ 8000（后端）上走通完整查看流程；结果写入新的验收目录。
- 场景：
  1. 历史 Golden `gf_20261112-143406_cde1fd`：列表 → 详情 → RF-01（BLOCKED）、RF-04（FAILED）、RF-02（PASS，trace 可看）。
  2. 历史 TC `rg_20261112-133157_f04289`：TC02 → 原始回归记录入口；Trace 显示“未开放”（取决于 Q3）。
  3. 新格式 Golden：仓库中尚无真实的新格式 Golden 运行。来源待决策（Q1）。
- 验收：浏览器截图存档；历史 13 份哈希与 SQLite 文件修改时间不变；没有绝对路径与凭证泄露（检查网络响应）。

---

## 9. Phase 1 契约缺口（不得伪造）

| 编号 | 页面字段 | 缺口 | 处理 |
|---|---|---|---|
| G1 | Run 列表 | 没有跨根目录的运行索引；`read_run` 只接受单个目录 | 2-B1 新增 `run_index` |
| G2 | Dataset 列表 | 没有数据集注册表；TC 的 `dataset_id` 实际是 `suite.version` | 2-B1 新增 `datasets`，ID 与版本的混用照实标注 |
| G3 | Dataset Version | Golden 文件没有 `version` 字段；新格式 config 中 `dataset.version = None` | 显示“未记录” |
| G4 | 冻结状态 | 没有任何冻结声明记录 | 全部为 `NOT_DECLARED`；声明格式待定（Q2） |
| G5 | Agent Version | `golden_run.build_config` 写入 `agent.version = None`；TC 与历史运行没有该字段 | 显示“未记录”；后续需要在 runner 中采集（单独立项，不在 Phase 2） |
| G6 | 历史 Evaluator 清单 | 历史 Golden 与 TC 的 `evaluator_manifest = null` | 显示“历史运行未记录” |
| G7 | Plan / Engine 证据（历史 Golden） | 历史 `result.json` 只有 verdict、execution_status、nodes 等，没有 plan / result_tables | 显示“历史运行未保存” |
| G8 | TC Trace | 只存在于运行目录内的 SQLite | 默认不开放（Q3） |
| G9 | 新格式 Golden 运行 | 仓库中只有两个历史 gf 运行；新格式运行只出现在测试临时目录 | 2-D 需要决定来源（Q1） |
| G10 | 失败归属 | 契约中没有该字段 | 由 E2E gate 推导，并给出 basis |
| G11 | Golden 运行标签 | Golden 没有 `label`；TC 有 | Golden 显示 run_id |
| G12 | 用户任务 | 新格式 `result.json` 只保存 case 引用，不内嵌 `user_input` | 从数据集文件读取，并以哈希一致性作为前提 |

---

## 10. 风险

1. 打开隔离 SQLite 会改动历史目录：Evidence API 只读 JSON，不打开 SQLite。
2. `read_run` 对 VERIFIED 运行会重算全部文件哈希，运行数增多后列表会变慢：需要按文件 `(size, mtime)` 缓存。缓存只是性能优化，详情页始终实时校验。
3. 相对的 `INSIGHTFLOW_DATA_DIR` 依赖启动目录：根目录解析失败时返回 503，而不是空列表。
4. Golden 运行目录位于 `docs/` 下：只开放这一个 runs 目录，不开放 `docs/`；证据 ref 一律经 `contained_path` 校验。
5. 复用 Trace 组件时的远程回查：`mode='evidence'` 必须有测试证明请求数为 0。
6. 前端打包的 `golden-set.json` 副本可能与原件漂移：2-C1 之后详情页改用 API；副本是否保留待决策（Q2 关联）。
7. TC 运行同时出现在“回归对比”和“Evaluation Runs”：页面注明两者口径不同（原始检查项 vs 统一契约投影），并互相链接。
8. `/traces` 遗留红测试：与本设计无关，评测路由不碰 `/traces/*`。

---

## 11. 需要产品决策的问题

- Q1：Phase 2-D 的“新格式 Golden 运行”从哪里来？候选：(a) 用脚本化 Agent 在临时根目录生成（不调用 LLM，只验证查看流程，不代表质量）；(b) 用真实模型跑一次 `run_golden_fidelity.py`（产生 LLM 调用与费用，结果写入 docs 下的新运行目录）。
- Q2：冻结声明采用什么形式？候选：(a) Phase 2 一律显示“未声明”，冻结声明格式另行设计；(b) 现在就定义一个冻结声明文件（版本、冻结时间、内容哈希、批准人），并为现有数据集补一份。注意：补的声明只代表“从此冻结”，不能回溯到历史运行。
- Q3：TC 运行的 Trace（运行目录内的 SQLite）是否开放？候选：(a) 不开放，只显示 case 记录中的 plan / steps / tables；(b) 以 `mode=ro&immutable=1` 只读打开，并以测试证明不产生 `-shm` / `-wal` 改动。
- Q4：是否需要跨运行的汇总指标？候选：(a) Phase 2 不做；(b) 只对 VERIFIED 运行做汇总，并单独说明。
- Q5：Trace 中 LLM `endpoint` 的脱敏粒度，以及证据 Trace 是否需要额外的快照凭证？候选：(a) 整项移除，只用只读凭证；(b) 保留 host，只用只读凭证；(c) 保留 host，证据 Trace 需要快照凭证。
- Q6：API 前缀确认使用 `/api/v1/admin/evaluations`（与现有 Admin 一致）而非候选的 `/api/admin/evaluations`。
