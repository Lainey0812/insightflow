# Report Module V1

把结构化计算结果整理为可交互、可追溯的业务报告。V1 包含证据提取、规则图表、受约束的模型解释、事实与引用校验、报告保存、预览及可选 HTML 下载。不实现新的分析执行、自然语言追问、文本频次、词云、完整对话式 BI、PDF 或 Word 导出。

## 工程接口与信任边界

当前聊天中的 `domain.models.ExecutionResult / Report` 仍属于旧固定销售 Mock 流程，缺少结果类型、执行状态、口径与截断信息，不能升级为真实报告。本模块使用独立 V1 契约，不修改原会话历史，不把旧 Mock 数据传入新报告。

输入依次为：

1. 已有 `ParsedIntent / IntentArtifact`。
2. 已有 `ValidatedAnalysisPlan`。
3. 新增 `domain.execution.ExecutionResultV1`。
4. 已保存的真实 `DatasetProfile`。

`ReportModuleNode` 可由未来 Orchestrator 调用；独立 API 按执行结果的数据集引用读取已保存画像，用户不需要手动填写字段或画像。整个报告服务不会加载、清洗、重新分析源文件，也不会增加统计任务。

**上游已有独立 [真实 Engine V1](analysis-engine.md)。** 共享结果契约已兼容并验证；Engine 自动调用报告的工作流接线尚未实施。本阶段用实际操作内核计算的测试结果验证报告。独立 API 仅接受明确标记 `source=imported` 的导入结果；不允许调用者把导入数据标成内部 engine 来源。旧 Mock 一律拒绝。内部服务 / 节点可接收可信 Engine 的结果，公开接口的来源校验保持不变。

版本与结构校验不能证明外部导入数字确实由源文件计算。producer、样本数、统计口径和批准版本是上游声明；`approved_plan_version` 的匹配也不是审批凭证。未来 Engine 必须自行保证来源文件完整性、真实审批状态和确定性执行。报告明确披露导入来源，不能把这些检查称为“已复算全部原始数据”。

## 文件改动

```text
backend/app/
  domain/execution.py            V1 执行状态、结果表、字段类型、统计范围与总体引用
  domain/analysis_report.py      Evidence / ChartSpec / Insight / AnalysisReport
  reporting/
    contracts.py                版本、资格、字段类型、统计结果结构与计数一致性
    evidence.py                 确定性证据、分母验证与来源行索引
    visualization.py            默认图表和可切换类型
    prompt.py                   模型仅选择证据并解释，不产生自由数值事实
    fact_validation.py          引用、类型、可识别统计断言、因果断言校验
    export.py                   无脚本的离线 HTML / SVG / 表格
  services/analysis_report.py    报告业务入口、状态与覆盖、受控 LLM 调用
  nodes/report_v1.py             统一节点输入输出
  storage/report_repository.py  SQLite 不可变报告及原始输入审计
  api/reports.py                生成 / 读取 / 可选下载
  main.py                       注入已有 Provider、Registry 与报告仓库
frontend/src/
  types/report.ts               V1 报告契约
  reporting/
    ReportPage.tsx              报告文档、图表切换、结果表、排序与证据
    InteractiveChart.tsx        受控 ECharts 渲染
    chartAdapter.ts             ChartSpec → ECharts Option
    report.css                  报告页面样式
  api/client.ts                 读取保存的报告
  main.tsx                     /reports/:reportId 预览入口
```

不新增包依赖或 Agent Runtime。保存报告需要一个新增 SQLite 表 `analysis_reports`，记录不可变报告与输入审计；刷新、重启读取不会再次运行模型或分析。

## ExecutionResultV1

机器契约见 [execution-result.schema.json](execution-result.schema.json)。关键字段：

- execution_id、dataset_id / dataset_version、plan_id / plan_version、approved_plan_version。
- execution_status：success / partial_success / failed，需与任务状态一致。
- source：API 接受 imported；内部还可使用 engine；mock 被拒绝。
- tasks：每个计划任务都有一条 success / failed / skipped 记录，失败 / 跳过必须提供原因且不能带结果。
- 成功任务结果包含 result_id、columns、rows、truncated、total_result_rows、total_refs。
- 每列给出稳定字段或别名、逻辑类型、dimension / metric 角色与单位。每行字段必须与 columns 完全一致，数值类型不能用字符串伪装。
- 每个任务提供 effective_row_count、可空的 valid_sample_count、sample_definition、scope 和 calculation。有效样本量不是报告自行猜测；必须附上它的业务定义。
- `total_refs=[{metric_field,result_id,result_field}]` 只能引用其他成功的同口径标量指标，不能直接提交一个没有来源的分母值。

整体限额：每任务最多 5000 行、30 列，全部结果最多 10 万单元格，序列化执行输入最多 4 MiB。超限明确报错，不静默丢弃结果。截断标记需与返回行数、总体结果行数一致。

报告前重新运行 Plan Validator，不信任调用者提交的 executable。核对四类输入的数据集版本、计划 ID / 版本、意图快照、每个任务状态及操作链最终输出。字段、类型或角色不同会报错。完整简单行计数还会与任务有效行数核对。**这些是内部一致性检查，不是全量原始数据复算。**

## Evidence Builder

支持：已计算指标读取、返回结果排名与 Top N、最大 / 最小、并列名次、占比、差值、合法基期的变化率、兼容已计算指标比较，以及上游有效样本数相对画像行数的覆盖信息。

每条证据包含来源 task_id、data_ref、result_field、source_row_indices（零起始）、scope、calculation 和原值 / 派生值。与总体分母相关的证据另带 related_result_refs。样本元数据证据使用 `$execution.valid_sample_count` 路径，其来源保存在报告 execution_metadata 中，不伪装成结果表列。

规则：

- 排名采用竞争排名，等值同名次；最大 / 最小保留全部并列来源行。只对已返回数据排名，截断结果不宣称全体排名。
- 变化率比较已返回的首末时间点，基期必须为正。不推断缺失时间点连续，不把变化率当同比 / 环比。数值型月份按数值顺序处理，不按字符串顺序。
- 差值与比例使用确定性运算，无法表达的非有限派生值不生成；不填零或改写原结果。展示中的约数带“约”或近似提示。
- full group_aggregate 的 count / sum 可在完整、互斥且未被后置过滤 / top_n 截断的分组上求总体分母；必须非负、完整且总体大于零。
- avg、median、min、max、distinct_count 不能被简单相加当总体分母。
- Top N / 截断结果只有显式总体引用通过验证后才生成总体占比。分母必须是成功、完整标量，同指标函数 / 原始字段 / 单位、同聚合前操作链及样本范围。不同筛选范围、失效引用、零或不合理分母会报错。
- 不生成失败任务、无有效数值指标任务的事实。没有有效证据时，返回 unavailable，不调用 LLM。

数字来自执行结果；证据构建阶段只做规格允许的排名、差值、比例等报告派生，不生成缺失的基础指标。

## Visualization Builder 与前端

ChartSpec 仅含类型、数据引用、维度、指标、可选类型、显示排序和显示上限；禁止任意 JS、formatter 函数或模型 ECharts Option。

默认规则：

| 结果形态 | 默认展示 | 可切换 |
| --- | --- | --- |
| 单一维度分类指标 | 排序条形图 | 条形图 / 表格，满足完整构成规则时加饼图 |
| 日期、日期时间或已提取年 / 月 | 折线图 | 折线图 / 条形图 / 表格 |
| 明确构成目标，少量短标签且有完整占比证据 | 饼图 | 饼图 / 条形图 / 表格 |
| 单行单指标 | KPI | 指标卡 / 表格 |
| 多维度、多字段或多指标标量 | 表格 | 表格 |

饼图最多 5 个短标签类别，必须覆盖完整分组。Top N 即使有总体分母，也不画成代表整体构成的完整饼图。类别多或标签长使用条形图，不生成词云。分类条形图默认前 10 个返回分组，完整返回数据保留在表格；时间线展示已有时间点，缺失时间分组仅见表格。

ECharts Option 由本地受控适配器生成；提示使用 richText，不执行数据中的 HTML。提供悬浮提示、兼容类型切换、完整返回表格、字段排序、50 行分页，以及证据 / 统计口径展开。排序和切换仅操作已下载结果，不调用模型、不再次执行分析、不改变报告结果或覆盖状态。

## LLM 洞察与事实校验

模型复用既有 Provider / 环境配置，只接收有界证据与目标、任务概要、局限，不接收完整原始数据或全部结果表。提示要求优先关注 P0，不推断因果，不夸大样本代表性。

为避免“数字恰好出现在某条证据中却被张冠李戴”，V1 使用更严格的模型草案：模型选择 primary_evidence_id、evidence_refs、finding_type，并生成定性的 implication / recommendation / limitations；**最终 fact、finding 中的数值、排名、比例由代码从主要证据生成，不复制模型自由编写的事实句。** 对应关系为：

- highlight → metric / ranking / maximum / minimum。
- difference → difference / comparison。
- concentration → proportion。
- trend → change_rate。
- coverage → coverage。

校验引用存在、不重复、包含主要证据、证据类型匹配、单条洞察不混合不同任务的口径。已有 P0 证据时，模型不能只输出补充任务的洞察。

模型解释和建议中可识别的阿拉伯数字、常见中文统计数词、排名 / 比例 / 最高最低 / 显著性和确定因果断言会被拒绝。V1 不接受模型自行在解释中重复数字，即使数字看起来存在于别的证据中。合法的明确因果否定语句可保留。错误返回明确报告错误，不静默修补或伪造成功。

这不代表完成了自然语言的严格事实证明。解释可能含义和业务建议仍需人工判断，最终报告始终标记 `structured_facts_verified_interpretations_unverified`，页面也明确披露解释限制。约束 / defer 事项不会在报告阶段被悄悄标为已解决。

## 状态与部分成功

report_status 与 goal_coverage 分开：

- report_status=complete：有效内容生成完成；partial：有执行失败 / 未形成证据的任务；unavailable：没有有效证据。
- goal_coverage 根据原计划核心需求及实际有证据的 P0 重新计算 complete / partial / blocked，不复用模型完成声明。
- P0 失败且只有 P1/P2 成功时，保留有用内容，但目标为 blocked；总结明确核心问题尚不能回答。
- 仍有核心需求缺口、未验证约束或 defer 事项时，不将目标标为 complete。报告本身生成完整，也可以目标仅部分覆盖。
- failed / skipped / 无有效证据任务进入 uncompleted_tasks 并显示原因，不生成其图表、洞察或建议。

总结由确定性状态和任务数生成；LLM 无权改写“目标已完成”。发现和图表默认优先 P0。

## 页面与 API

页面顺序：分析概览与关键指标 → 主要发现与证据 → 交互图表 → 下一步建议 → 数据局限与未完成任务。

```text
POST /api/v1/reports                    生成并保存 V1 报告
GET  /api/v1/reports/{report_id}        读取 JSON，不触发模型或下载
GET  /api/v1/reports/{report_id}/download 可选离线 HTML 附件
GET  /reports/{report_id}              前端交互预览（Vite / 前端站点）
```

生成请求对象含 `intent`、`validated_plan`、`execution`，完整契约见 FastAPI `/docs`、[report-input.schema.json](report-input.schema.json)、[analysis-report.schema.json](analysis-report.schema.json)。服务端按 execution.dataset_id / dataset_version 读取画像，不接受用户手工提交 DatasetProfile。

例如上游已有真实计算结果时：

```python
import httpx
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=45) as client:
    response = client.post("/api/v1/reports", json={
        "intent": intent_result,
        "validated_plan": validated_plan,
        "execution": imported_execution_result,  # source 必须是 imported
    })
    response.raise_for_status()
    report = response.json()
    print("预览：", "http://127.0.0.1:5173" + report["preview_url"])
    print("可选下载：", "http://127.0.0.1:8000" + report["download_url"])
```

`preview_url` 需要由前端站点打开；直接访问后端根路径不会提供 SPA。读取 JSON 不会强制下载；仅用户点击下载才返回 attachment。离线 HTML 含结论、静态 SVG、完整返回表格、证据与局限，不依赖 CDN，不含脚本；完整交互使用预览。新建的报告不会自动覆盖旧报告。

错误沿用统一 error 约定，主要包括 REPORT_INPUT_INVALID / REPORT_INPUT_MISMATCH、REPORT_DENOMINATOR_INVALID、REPORT_INVALID_EVIDENCE_REFERENCE / TYPE、REPORT_UNVERIFIED_FACT、REPORT_CORE_FINDINGS_MISSING、REPORT_LLM_INVALID_OUTPUT、REPORT_NOT_FOUND。模型未配置、超时或上游失败均明确报错。没有有效证据的 unavailable 报告不需要模型配置。

## 验证方式

```bash
# backend
../.venv/bin/python -m pytest -q
# frontend
npm test
npm run build
```

测试由真实操作内核对合成招聘 / 通用数据执行，验证精确结果，不使用模型数值作为计算依据；洞察调用显式注入 scripted Provider 或受控错误，并明确标记为 Mock 解释。

覆盖完整与部分结果、核心目标未覆盖、无证据零调用、并列排名、极值、完整分母、Top N 禁止整体占比、同口径显式分母、错误筛选分母、不可加指标、负值与零分母、时间变化、引用 / 类型 / 数值 / 因果拒绝、版本与资格重验、持久化与重启、下载转义、图表切换无重复分析及表格排序。

实际浏览器验收使用隔离测试数据目录与临时端口，不触碰用户上传文件；截图见 [report-v1-preview.jpg](report-v1-preview.jpg)。

普通自动化测试及浏览器测试不能证明真实模型的解释质量。当前环境没有配置模型时，不声称完成真实模型语义评测。后续应连接真实 Engine，确认审批和来源链条，再使用真实模型评估业务解释与建议；无需扩展成对话式 BI。


## 真实主链路接入

现已接入真实 Workflow，内部入口只从服务端保存的 execution_id 加载完整执行结果与不可变批准快照，不接收客户端提交的 Engine 结果。公开 imported API 保持原契约。详见 [主链路说明](report-workflow-v1.md) 与 [真实验收记录](evaluations/report-workflow-v1/report.md)。
