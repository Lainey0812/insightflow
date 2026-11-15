# InsightFlow · 数据画像、意图、规划、执行与报告 V1

版本更新先保存需求，旧版需求、Prompt/源码快照、评测和失败记录只保留、不覆盖。原始需求与版本关联见 [需求档案索引](docs/versions/INDEX.md)、[模块版本索引](docs/versions/MODULE-VERSIONS.md)，后续归档规则见 [版本档案说明](docs/versions/README.md)。

面向普通业务人员的 AI 数据分析工作台。采用单页左右布局：左侧历史会话，右侧对话、文件输入和分析计划卡片；报告通过链接预览或下载。

**Data Profiler 已接入真实 CSV/XLSX 文件：解析、类型识别、质量检测和画像指标均由代码计算，并关联不可变的数据集版本。** 不做自动清洗，不调用 LLM。独立画像 API 不会触发分析规划或报告。

Intent Parser 已完成 V1.3 语义优化及真实评测，当前Prompt为 `intent-v1.3.3`，保持 qwen3.8-flash、原Schema和单LLM节点。168条主评测召回98.64%、精确率98.57%、完整请求通过161/168；独立20条通过18条，关键重复21/21。仍有非必选内容误入限制、时间混类及排名遗漏，**尚未完成完整语义验收**。冻结评分、各轮真实输出、原v1.1/v1.2保留结果及全部Bad Case见 [交付报告](docs/evaluations/intent-v1.3.3/report.md)。

Intent Parser V1 已实现：从真实画像的 `fields` 自动构建 `dataset_context.columns`，通过可替换的 LLM Provider 提取意图，并校验模式、约束、不确定性及流程决策。默认不发送样本行或完整数据。**需配置真实模型；未配置时返回明确错误，不再默认 Mock 识别成功。** 旧 Mock 历史与 API 兼容分支隔离保留，不能当作上传文件的业务分析结论。

**Workflow V1 真实主入口已接通**：上传文件与需求后自动运行真实画像 → Intent → Planner → Validator，在聊天中审核、删除任务并保存不可变版本，经原 HITL 服务端批准后调用真实 Engine，持久化 ExecutionResult。支持澄清暂停/继续、准备失败检查点重试与刷新/重启恢复。执行结果保存后会自动生成真实报告；生成状态独立保存，报告失败不改变计算状态。状态图、API、改动清单见 [Workflow V1](docs/workflow-v1.md)，真实浏览器、模型调用与 Pandas 对照见 [验收记录](docs/evaluations/workflow-v1/report.md)。

**HITL V2 已改为业务方案确认**：默认依次展示核心目标、分析条件与拟用口径、核心/辅助/补充方向、待确认事项和开始操作。技术参数折叠。新增确定性约束审计；只有明确映射到真实字段、正确步骤且完整核验通过的条件才允许作为批准依据，无法映射或未解决的口径继续阻断。原审批/版本/执行契约不变，不增加展示 LLM。四类真实浏览器结果与 Pandas 一致，详见 [数据映射与审计说明](docs/hitl-v2.md)、[截图和验收记录](docs/evaluations/hitl-v2/report.md)。

**仍有范围限制**：审计使用有限语法，不是通用自然语言理解；如“只看2026年发布”仍可能阻断，需重新明确原始时间字段。defer/clarify 不可勾选解除。旧人工 JSON 导入模式保留；原始 Intent 约束不会被清空或改写。

**真实 LLM Analysis Planner V1 已补强并复用于 Workflow**：沿用 qwen3.8-flash、单节点和现有计划契约，当前Prompt为planner-v1.2；所有草案经原Validator返回F0/F1/F2，核心不可执行任务保留。此前独立真实评测32/32计划Schema有效，原25例参考检查24/25、独立8例8/8；32例P0范围及优先级已获用户逐例认可；操作链仍有附加排序的波动及已记录的措辞/参考差异，不能仅凭高分宣称全量语义可靠。接口及配置见[规划文档](docs/analysis-planner.md)，独立评测原始输出、失败和稳定性见[交付报告](docs/evaluations/planner-v1.2/report.md)。本轮没有修改 Planner Prompt 或 HITL 审批规则。

**独立 Report Module V1 已实现**：确定性证据、受控图表、引用与事实校验、部分成功披露、交互预览与可选 HTML 下载。它接收共享的执行结果契约；旧 Mock 结果不能作为新报告输入。公开导入 API 继续只接收 imported，真实 Engine 到报告的主流程已接通；以执行保存的批准快照和完整结果为依据，报告仅发送有界证据给原有 LLM Provider。接口、信任边界与限制见 [Report Module 文档](docs/report-module.md)。

**独立 Analysis Engine V1 已实现**：按数据集版本加载真实上传文件，核对服务端已验证批准快照，复用六类内核执行操作链，保存完整结果、步骤日志与错误，支持幂等重试和执行结果读取。现有 Mock HITL 不能授权真实执行；当前已新增真实 HITL 用户确认接口和页面，隔离验收通过公开审批接口验证链路。接口、文件变更、测试及真实执行样例见 [Engine 集成文档](docs/analysis-engine.md)。

画像 API、字段契约、统计与版本口径、错误码和限制详见 [Data Profiler 文档](docs/data-profiler.md)。

意图契约、Provider 配置、澄清恢复及真实模型评测方法见 [Intent Parser V1 文档](docs/intent-parser.md)。启动聊天流程前导出 `INSIGHTFLOW_LLM_BASE_URL`、`INSIGHTFLOW_LLM_MODEL` 和可选的 `INSIGHTFLOW_LLM_API_KEY`；接口需支持严格 JSON Schema。独立画像 API 无需配置模型，自动化测试使用显式注入的受控 Provider，不联网。

## 真实报告接入 V1

真实执行完成后：保存 ExecutionResult → 读取执行时的不可变批准快照与 DatasetProfile → 确定性 Evidence / ChartSpec → 原 Provider 生成定性业务解释 → 引用与事实校验 → 原子保存 AnalysisReport。统计事实、排名、返回分组合计由代码生成。报告状态与 Engine 状态独立。

- 主对话显示报告生成状态、失败重试和在线预览入口；原始计算结果折叠保留。
- 预览 `/reports/{report_id}`；HTML 下载仅在用户点击后发生，读取时携带原会话本地访问凭证。
- 旧真实执行没有报告时可点击“生成分析报告”；失败后重试仅生成报告，不重新分析。
- 沿用现有模型配置；`INSIGHTFLOW_REPORT_ENABLE_THINKING=false` 为默认值，超时沿用 `INSIGHTFLOW_LLM_TIMEOUT_SECONDS`。不配置模型时明确失败，不回退 Mock。
- 审计、状态图、API、兼容性及文件清单见 [报告接入说明](docs/report-workflow-v1.md)。真实销售结果、模型原始返回、全部失败案例、截图及测试日志见 [验收记录](docs/evaluations/report-workflow-v1/report.md)。

业务报告已按“标题与范围 → 执行摘要与重点指标 → 核心发现与业务解读 → 建议进一步分析 → 数据说明”展示。新百分比由保存的真实结果确定性计算并标明分母；图表、证据和原始结果折叠保留。旧报告无需重新分析即可采用新结构，说明见 [业务报告展示](docs/report-business-view.md)。

**Insight Generator V1.1 第二阶段已实施，业务质量尚未验收通过**：当前 Prompt `report-insights-v1.1.6`，仍为 qwen3.8-flash 单节点。比较证据前移到 Evidence Builder，多证据事实统一保存到 AnalysisReport；新展示与 HTML 不再生成 V 系列业务结论，历史报告保留旧版路径。真实对照中可生成案例为旧版 14/15、新版 8/15，暴露出安全校验误拦截及模型越界；不能只凭证据利用率提升宣称通过。修改清单、冻结评分、全部实际返回及 Bad Case 见 [本轮交付](docs/evaluations/insight-generator-v1.1/README.md)。

## 本地运行

环境：Python 3.11+（本次验证 3.14.2）、Node.js 22.12+ 或 24+（本次验证 24.13.0）、npm。首次安装需要访问 Python/npm 包源。

在项目根目录安装后端：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'
```

可复现本次验证环境的 Python 依赖版本记录在 `backend/requirements.lock.txt`；该版本快照针对 Python 3.14。相同环境可先 `python -m pip install -r backend/requirements.lock.txt`，再安装上面的本地项目。

终端一启动后端（从项目根目录）：

```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端二启动前端（从项目根目录）：

```bash
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173 。Vite 将 `/api` 代理到 `127.0.0.1:8000`，健康检查、报告预览和下载使用同一代理。无需 CORS 配置。端口占用时启动会明确失败，释放对应端口后重试。

- 健康检查：http://127.0.0.1:8000/api/v1/health
- API 文档：http://127.0.0.1:8000/docs
- 数据目录：默认 `var/`，可用环境变量 `INSIGHTFLOW_DATA_DIR` 指定绝对路径；`backend/.env.example` 供参考，应用不会自动读取 `.env`。
- SQLite 和上传文件仅存本机，均在 Git 忽略列表中。文件名使用生成的 ID，原始名称仅作元数据。

## 真实 Workflow 验收流程

1. 导入本地 LLM 环境配置后启动服务，确认页面显示「真实分析流程」与「服务已连接」。应用本身不自动加载 `.env`。
2. 上传 `examples/workflow-sales.csv`，填写“探索这份数据的主要特征和差异。”。前端使用 `real_workflow=true`，自动调用真实 Intent 与 Planner，无需手填 JSON。
3. 查看画像、流程状态与计划的优先级、F0/F1/F2、coverage、缺失需求及约束风险。模糊请求会先暂停并允许补充需求。
4. 删除任务会生成新版本并重验。核对目标、用户条件与方案拟用口径后点击“确认并开始分析”，原 HITL 重新核验约束证明并保存真实审批，原 Engine 执行受控操作链；未通过证明、核心问题无法分析或未解决事项均不能批准。
5. 查看真实计算结果并刷新恢复。本次浏览器实测保留总体与地区任务，销售额总和 3648，华南 1515、华东 1117、华北 1016，与独立 Pandas 完全一致。
6. 点击“版本与审批记录”检查不可变版本与 approval_id → execution_ids。真实主流程会自动生成报告，支持在线预览与用户主动下载；人工导入兼容模式保持独立。

自动验收：在 backend 运行 `../.venv/bin/python scripts/verify_hitl.py`。它使用隔离临时数据库，通过公开 API 模拟确认，包含独立 Pandas 基准、版本拒绝、审批/执行幂等及重启读取，明确不代表生产人工批准。

人工导入兼容模式：`POST /sessions` 传 `manual_review=true`，可继续按 [原 HITL 文档](docs/hitl-v1.md) 提交结构化计划并审核。旧 API 两个模式标志均未传时保留原有 Mock 工作流，旧会话可读且显示历史 MOCK；其批准不能授权真实 Engine。新前端始终选择 `real_workflow=true`，两个标志不得同时开启。

每个会话接受一个非空 CSV/XLSX 文件，最大 10 MB。支持表头行设置；多 Sheet、编码和分隔符通过 API 指定。真实计划约束与未解决事项不能通过布尔确认跳过。支持有限的确定性约束证明；当前没有 LLM 修订或 defer 解决工具。修改范围使用“重新提出需求”，具体限制见 HITL V2 文档。

## 自动化检查

项目根目录：

```bash
source .venv/bin/activate
cd backend
python -m pytest -q
```

前端目录：

```bash
npm test
npm run build
```

后端测试覆盖：真实 CSV/XLSX 指标、基础类型、空文件、混合类型、重复列名和重复行、多 Sheet 选择、损坏文件、公式与 Excel 错误、结构异常、缺失与样本口径、稳定字段 ID、版本重算与读取、源文件完整性、模型一致性校验，以及画像先于意图、澄清暂停 / 恢复、审批与历史版本等回归。测试在内存中生成 Excel，不依赖外部文件或模型服务。

真实 Engine 验收可额外运行 `cd backend` 后执行 `../.venv/bin/python scripts/verify_engine.py`，输出独立 Pandas 对照、实际行数与持久化 / 幂等核验，并更新 docs 中的真实执行示例。

前端测试覆盖：健康状态、文件与需求及表头行提交、聊天内澄清答复与计划卡片、审批先于执行、历史计划只读、修订失败保留草稿及报告链接。前端构建同时运行 TypeScript 检查。

Workflow V1 最终验证：后端 **527 passed**、前端 **30 passed**、生产构建成功；新增集成覆盖真实服务链、F0/F1、约束阻断、任务隔离、幂等与中断恢复。离线测试使用显式受控 Provider，不冒充真实模型评测。浏览器另有 **7 次实际 qwen3.8-flash 调用**、实际文件上传、真实批准/执行、刷新与后端重启，证据见 [验收记录](docs/evaluations/workflow-v1/report.md)。

HITL V2 当前验证：后端 **562 passed**、前端 **40 passed**、生产构建成功。新增 35 个后端实例与 10 个前端测试；另有 10 次真实 Intent/Planner 调用，四主题浏览器真实审批/执行及一个保留阻断的案例。展示层零模型调用，原测试保持通过。

## 工程结构

```text
frontend/src/
  App.tsx                    单页工作台与交互状态
  api/client.ts              统一 API 客户端
  types/contracts.ts         API 类型
  components/
    SessionSidebar.tsx       历史会话
    Welcome.tsx              初始输入引导
    MessageComposer.tsx      文件、目标与计划修改
    MessageList.tsx          对话消息
    PlanReviewCard.tsx       HITL 卡片
    BusinessPlanReview.tsx   业务方案确认与服务端资格
    WorkflowProgress.tsx     真实主链路状态、错误与准备重试
    ReportLinkCard.tsx       报告、ECharts 预览与链接
  tests/
backend/app/
  api/                       HTTP 路由与错误映射
  core/                      本地配置
  domain/                    状态枚举、DatasetProfile、Intent Schema、来源和节点契约
  intent/                    上下文映射与意图提示词
  execution/                 真实数据加载、逐任务操作链编排及预览
  reporting/                 证据、图表推荐、事实校验、提示词与离线导出
  planning/                  能力目录、操作参数与内核、确定性计划校验、规划提示词
  review/                    确定性约束证明与业务展示映射
  profiling/                 独立解析器、基础类型识别、确定性画像计算
  workflow/                  状态转换表与节点调度
  nodes/                     Data Profiler / Intent Parser / 独立 Planner / Engine / Report V1 节点及旧 Mock 节点
  services/                  画像、意图与独立规划业务入口、真实及历史 HITL 审核、HTML 导出
  llm/                       统一协议、可配置 JSON Schema HTTP 适配器及未配置错误
  storage/                   SQLite 会话 / 数据集画像 / 真实执行与完整结果 / V1 报告及审计、本地文件存储
backend/tests/
examples/sales.csv
var/                         自动生成，不提交
```

API 和 Orchestrator 使用同一个画像业务入口；`DataProfilerNode → DataProfilerService → profiling / Repository → Domain`。节点不互相调用，不依赖 HTTP；Domain 不依赖上层模块。纯画像模块不依赖存储、HTTP 或模型。会话、消息和计划保存在会话 JSON 中；源文件元数据、各版本 DatasetProfile 保存在新增 SQLite 表中。当前不引入 ORM、队列、缓存或微服务。

## 工作流与核心契约

新页面使用 [Workflow V1 状态图](docs/workflow-v1.md)：`CREATED → PROFILING → PARSING_INTENT → PLANNING → VALIDATING → AWAITING_APPROVAL → APPROVED → RUNNING → COMPLETED`。`clarify` 暂停在已有 `WAITING_FOR_CLARIFICATION`，失败持久化 `FAILED`。以下意图解析 / Mock Planner 描述仅适用于兼容保留的旧 API 工作流。

```text
CREATED → PREPARING → AWAITING_APPROVAL → APPROVED → RUNNING → COMPLETED
                         ↑       │           │
                         └─修订──┘           │
                         └───────修订────────┘

PREPARING ⇄ WAITING_FOR_CLARIFICATION（补充需求）
PREPARING / RUNNING → FAILED
```

首次上传先完成真实 Data Profiler，再将其轻量字段元数据交给 Intent Parser；已有画像可直接复用。本次输入存在明确数据依赖，因此不继续使用原先的 Mock 并发方式。`clarify` 时进入 `WAITING_FOR_CLARIFICATION`，保存问题与原始需求并暂停；答复后复用画像重新解析，只有 `proceed` 才调用 Mock Planner。模型失败、非法输出或画像失败都不会规划。没有增加后台任务或 Agent Runtime。

- `SessionState` 保存当前状态、并发修订号、文件元数据、目标与模式、节点产物、计划历史、批准版本、消息、执行结果、报告及错误。
- `NodeInput[T]`：`session_id / run_id / payload`。
- `NodeOutput[T]`：`session_id / run_id / node_name / status / data / error / provenance`。成功只带数据，失败只带结构化错误。
- 错误：`code / message / node_name / retryable / details`；HTTP 统一为 `{"error": {...}}`。工作表选择错误在 `details.available_sheets` 中提供可用名称，不暴露内部异常详情。
- 每次删除或修订创建新计划版本，历史版本不变。修订会清空 `approved_plan_version`。
- 审批、修订和执行声明在 SQLite `BEGIN IMMEDIATE` 事务内检查状态、计划版本及 `expected_revision`。过期请求返回 `409`，重复执行不能启动第二次计算。
- 旧 Mock 操作限定 `summary / trend / category / region`。真实 Engine 仅执行 Registry 注册的六类操作，不执行模型代码，不使用 `eval`。
- 真实画像标记 `source=uploaded`；意图标记 `source=llm` 或输入校验的 `input_guard`（测试 Provider 为 `mock`），均附带数据集版本。下游计划和报告继续标记 `source=mock`。会话 `dataset_ref` 指向真实画像版本，`data_source=mock` 说明旧聊天分析 / 报告管线为演示；真实 Engine 执行后标记 uploaded，结果 source=engine 并携带 uploaded 溯源。
- 旧聊天 Report 使用历史结果生成模板报告。独立 Report V1 从 ExecutionResultV1 构建证据；本次不自动调用模型生成报告。

当前采用**单个后端进程**运行。重启保留待补充需求 / 待审核 / 已批准 / 已完成会话；准备中的会话会标为 `FAILED / PROCESS_INTERRUPTED`，保留画像/意图/Planner 检查点，支持显式“重试准备”，不自动重跑。真实 Engine 的中断执行保留已落盘成功任务，其余标记 EXECUTION_INTERRUPTED，原请求不重跑。不要使用多个 Uvicorn workers；后续需要后台执行时再引入持久任务机制。

## API

前缀 `/api/v1`，完整模型见 FastAPI `/docs`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 服务状态与能力标记，mode=real；不代表模型连接已成功调用 |
| POST | `/executions` | 四个标识读取服务端批准计划，执行并持久化真实结果 |
| GET | `/executions/{execution_id}` | 真实执行结果，view=preview 或 complete |
| GET | `/executions/{execution_id}/results/{result_id}` | 完整结果分页，offset / limit |
| POST | `/reports` | Intent + 已验证计划 + 导入执行结果，生成 V1 报告 |
| GET | `/reports/{report_id}` | V1 报告 JSON；交互预览为前端 `/reports/{report_id}` |
| GET | `/reports/{report_id}/download` | 可选离线 HTML，含静态图形与完整返回表格 |
| GET | `/capabilities` | V1 能力目录，含参数、类型与输出规则 |
| POST | `/plans/generate` | Intent + 保存的画像 → 草案 → 强制校验 |
| POST | `/plans/validate` | 独立确定性校验，不调用模型 |
| GET | `/sessions` | 历史会话摘要 |
| POST | `/intents/parse` | `user_query` + `dataset_ref`，自动读取字段上下文 |
| POST | `/sessions/{id}/clarifications` | 原文答复 `answer` 与 `expected_revision` |
| POST | `/sessions` | multipart：主入口传 `real_workflow=true`、`file`、`goal`，可选解析参数；201 返回后后台准备 |
| POST | `/sessions/{id}/retry-preparation` | expected_revision，按检查点显式重试未批准且未执行的准备失败 |
| POST | `/datasets` | 上传并计算真实画像：`file`、可选 `header_row / sheet_name / encoding / delimiter` |
| POST | `/datasets/{id}/profiles` | 对已保存文件按指定解析选项重算画像 |
| GET | `/datasets/{id}/versions/{version}/profile` | 读取指定版本的真实 DatasetProfile |
| GET | `/sessions/{id}/profile` | 读取该会话关联的真实画像 |
| GET | `/sessions/{id}` | 会话、消息及节点产物 |
| GET | `/sessions/{id}/plans` | 全部计划版本 |
| POST | `/sessions/{id}/plans` | 兼容人工导入模式；真实 Workflow 初始计划由服务端生成，拒绝手工替换 |
| GET | `/sessions/{id}/plan`、`/sessions/{id}/plans/{version}` | 真实当前 / 历史版本 |
| GET | `/sessions/{id}/approvals` | 不可变审批与执行关联 |
| GET | `/sessions/{id}/review` | 当前业务展示、逐条约束审计与服务端批准资格 |
| GET | `/sessions/{id}/constraint-audits` | 已批准记录的不可变约束证明 |
| POST | `/sessions/{id}/plan-revisions` | `expected_revision`、`plan_version`、`instruction` / `remove_task_ids` |
| POST | `/sessions/{id}/approvals` | V1 需完整版本标识、request_id、警告确认；详见 HITL 文档 |
| POST | `/sessions/{id}/execute` | 仅历史 Mock；真实会话必须调用 `/executions` |
| GET | `/sessions/{id}/report` | 结构化报告 |
| GET | `/sessions/{id}/report/preview` | HTML 预览 |
| GET | `/sessions/{id}/report/download` | HTML 附件下载 |

## 后续工作

1. 扩展有限约束映射覆盖面与 defer 解决工具；尚未证明的条件继续阻断，避免把 F2 错当成约束已验证。
2. 独立设计自然语言计划修订，必须产生新草稿并重新调用 Validator；本轮仅保留删除任务。
3. 将真实 Engine 的 ExecutionResultV1 与不可变审批快照交给 ReportModuleNode，保留统计口径、样本量、错误与分页信息。

当前已接通真实上传、模型意图/规划、计划保存与任务删除重验、服务端审批和 Engine，并明确保留约束验证阻断。尚未接通报告自动生成；不提供自动清洗、复杂语义派生、预测、多用户账户或 Agent 编排。

## Admin Console V0.1（独立工程）

测试管理界面位于 `admin/`，与现有 frontend/backend 独立。当前提供运行概览、Trace、版本对比和系统设置的布局与空状态，尚未接入真实监控 API 或身份认证。

```sh
cd admin
npm ci
npm run dev
```

访问 http://127.0.0.1:5174/dashboard。检查与构建使用 `npm run typecheck`、`npm test`、`npm run build`。端口占用会明确报错。

Admin Workflow 详情新增“失败定位”：按错误代码确定性归类（文件或解析参数、数据内容、模型服务、模型输出不合规、容量限制、规划或校验阻断、进程中断、未归类），显示失败节点、错误代码、排查提示和输入摘要；列表可按失败归因筛选（`failure_category`）。画像、意图、规划节点开始时记录输入摘要（解析参数、文件类型与大小、需求字数、澄清数、字段数、数据集版本），不记录文件名、需求原文或数据值。本功能之前的历史记录可归类，但没有输入摘要。

Admin Workflow 详情新增“质量信号”，按需求理解、分析规划、人工审核、计算执行、报告生成、模型调用分组，每项标记为“正常”“需关注”或“未采集”：需求澄清轮数、规划覆盖度与被阻断任务数、F0/F1 任务数与未覆盖核心需求数、用户修改计划次数、执行结果、洞察候选数与事实校验拒绝数（以被采用的报告尝试为准）、报告生成尝试次数、报告完整度、目标覆盖、模型重试与失败次数。列表新增“质量提示”列，显示需关注项数量。信号只由已采集的节点、模型调用和业务状态推导，执行结果和报告状态以业务库为准；未采集的项不按 0 计。计划校验节点从本功能起记录 `f0_count/f1_count/f2_count/unmet_core_count`，更早的记录这几项显示“未采集”。

Admin Workflow 详情新增“人工标注”：点击“存为 Bad Case”，填写问题类型、严重程度、问题节点、标题、观察到的问题、期望结果和标注人后保存。保存时冻结当时的业务状态、节点元数据、失败定位、质量信号、模型调用引用和回放引用（会话、数据集版本、计划、审批、执行、报告尝试），并记录证据 SHA-256；不复制原始数据、需求原文或模型文本。Bad Case 存在独立的 `var/bad_cases/bad_cases.sqlite3`，记录和处理历史只追加（数据库触发器禁止修改和删除）。状态有待确认、已确认、已修复、不处理、误报，变更以追加记录的方式保存，并用 `expected_sequence` 防止并发覆盖。新增 `/bad-cases` 列表与 `/bad-cases/{case_id}` 详情页。

写操作需要单独的标注凭证：启动后端前设置 `INSIGHTFLOW_ADMIN_ANNOTATION_TOKEN`，Admin 表单中填入（不在浏览器保存）。未配置时 Admin 保持只读，保存返回 503；`INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE=true` 的本机测试模式不需要该凭证。接口：`GET /api/v1/admin/bad-cases`、`GET /api/v1/admin/bad-cases/{case_id}`、`POST /api/v1/admin/bad-cases`、`POST /api/v1/admin/bad-cases/{case_id}/events`。

用户前端在真实流程状态的“查看过程”中显示运行编号（workflow_id），并提供“在 Admin 中查看”链接，新标签页打开对应的 `/traces/workflows/{workflow_id}`。Admin 地址默认 `http://127.0.0.1:5174`，可在启动前端前设置 `VITE_ADMIN_URL` 修改；该变量只放公开地址，不放任何凭证。未登记 Workflow 的旧会话或人工导入会话不显示该入口。

完整配置和目录见 [Admin 运行说明](admin/README.md)，实际变更与验证结果见 [V0.1 工程交付](docs/admin-console-v0.1.md)。本轮需求按 REQ-0042 保存，旧版本继续保留。

## Workflow Trace V0.1（后端）

真实 ReportWorkflow 现已记录阶段、模型调用元信息、候选接受/拒绝与规则，以及最终报告保存状态。Trace 保存于当前数据目录的 `observability/trace.sqlite3`，与业务数据库分开；不重复保存原始数据或模型文本。

只读查询入口为 `/admin/runs`、`/admin/runs/{run_id}`、`/admin/runs/{run_id}/spans`、`/admin/spans/{span_id}/events`，同时支持 `/api/v1/admin` 前缀。服务端未配置 `INSIGHTFLOW_ADMIN_READ_TOKEN` 时默认关闭；请求通过 `X-Admin-Token` 鉴权。不要把凭证放入 VITE_ 变量。

本轮未接入 Admin Trace 列表 UI。数据契约、真实失败 Trace、测试与剩余边界见 [Workflow Trace V0.1](docs/workflow-trace-v0.1.md)。需求关联 REQ-0043、REQ-0044，历史记录继续保留。

## Admin Trace V0.2

`/traces` 现已接入真实运行列表、组合筛选和分页，`/traces/:runId` 提供阶段层级、失败定位、事件和候选拒绝诊断。复用 V0.1 记录与权限，新增短期 HttpOnly Cookie 只读访问；没有创建第二套运行记录或加入自动修复。

使用方式、真实成功/失败/部分成功案例与验证结果见 [Trace V0.2](docs/admin-trace-v0.2.md)。本轮需求 REQ-0045，V0.1 历史及所有失败记录继续保留。

## Admin Trace V0.3

`/traces` 支持选择两次历史运行，`/traces/compare?left=...&right=...` 提供输入/版本可比性、节点身份与重试对齐、状态/错误/拒绝规则及受控证据与报告比较。缺失字段显示 unknown，不回填历史，不自动归因 Prompt。

新增快照仍存于既有 Trace sidecar，权限与业务流程保持原样。用法、API、真实比较和隐私/历史限制见 [Trace V0.3](docs/admin-trace-v0.3.md)，需求 REQ-0046。

### Prompt Registry V0.1：后端模板与调用快照

三个真实 HTTP LLM 节点现按最终出站请求保存模板绑定和调用快照，独立存储于 `INSIGHTFLOW_DATA_DIR/prompt_registry/registry.sqlite3`。增量迁移只创建该侧库，不改现有业务/Trace 表。模板和请求元数据不可变；每次重试独立记录。调用前快照保存失败时不发模型请求，调用后记录失败时明确报错，不伪装成功。普通 Trace 写入仍为 best effort。

- 原有 `INSIGHTFLOW_ADMIN_READ_TOKEN` 可读取调用元信息；完整请求另需 `INSIGHTFLOW_ADMIN_SNAPSHOT_TOKEN`，仅在服务端设置，不能放入任何 Vite 环境变量。
- 默认保留历史请求，不自动删除旧模板或调用记录。可显式设置正整数 `INSIGHTFLOW_LLM_REQUEST_RETENTION_DAYS` 限制原始请求保留期；启动时清理到期 payload，到期内容在查询时也不可读，哈希与模板保留。数据库备份/磁盘加密需由部署环境管理。
- 元信息：`GET /admin/llm-calls/{call_id}`；按 Trace：`GET /admin/runs/{run_id}/llm-calls`、`GET /admin/spans/{span_id}/llm-calls`；模板：`GET /admin/prompt-templates/{snapshot_id}`。
- 完整请求：`GET /admin/llm-calls/{call_id}/request`，同时提交 Admin 只读凭证与 `X-Admin-Snapshot-Token`；所有读取返回 `Cache-Control: no-store`。
- 模型返回（Registry 迁移 002）：成功调用保存模型消息内容（业务校验前，含后续被拒候选）；HTTP 错误、拒答、输出截断或结构异常保存 Provider 原始响应体，最多 64KB 并标注截断。与调用终态同事务写入，失败按原语义报 `LLM_CAPTURE_FINALIZE_FAILED`；保留期限与请求相同。读取 `GET /admin/llm-calls/{call_id}/response`，使用同一快照凭证，读取时校验哈希。超时等无响应调用及本功能之前的调用显示 unavailable，不回填。Admin 调用详情页新增“受控模型返回”。
- Report 关联已有 Run/Span/Manifest；Intent、Planner 尚无完整 Trace Run，使用 operation_id 与 retry_of_call_id 追溯，不伪造运行。旧 Run 没有请求快照时返回 unavailable。
- `succeeded` 表示模型 HTTP/响应协议调用成功，不代表 Intent/Plan/Insight 已通过后续业务校验。未完成调用重启后标记 interrupted，不能据此断定供应商是否已收到或计费。
- 不改变三个节点的 Prompt 内容、模型参数或业务规则；固定重试指令仅提取为同值常量。Registry 列表、版本详情和 Diff 页面待后续开发。

完整契约、权限、失败语义和限制见 [Prompt Registry V0.1 交付说明](docs/implementations/prompt-registry-v0.1-2026-10-29/delivery.md)。

### Prompt Registry V1.0：只读 Admin 页面

Admin 的 Prompt 管理已接入真实 Registry 查询：`/prompts`、节点历史、不可变版本详情、同节点文本 Diff 与关联模型调用。默认只展示固定模板和请求元信息；完整模型请求继续要求额外授权。Report Trace 只按保存的模板 ID 跳转，旧 Run 缺失内容显示 unavailable。

没有新建第二套快照库，没有修改三个 LLM 节点或 Prompt。无已登记历史时页面显示真实空状态，不将今天的代码填充成旧版本。

完整路径与操作说明见 [Prompt Registry V1.0](docs/implementations/prompt-registry-v1.0-2026-10-29/delivery.md)。后端完整重启以加载新增只读 API；现有 Admin 开发服务可继续使用。
