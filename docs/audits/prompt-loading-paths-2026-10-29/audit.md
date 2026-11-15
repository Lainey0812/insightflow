# 三个 LLM 节点实际 Prompt 来源与动态拼接审计

审计日期：2026-10-29。需求：REQ-0050，承接 REQ-0049。范围：现有代码的加载、调用、序列化、重试和版本记录。没有创建 Prompt 数据表，没有调整 Prompt、模型参数或业务逻辑。

## 结论

三个节点均没有从数据库、Markdown 模板库或 Admin 加载 Prompt。System 是 Python 模块中的字符串，服务在导入时绑定；User 是服务执行时构造的 JSON 字符串；输出 Schema 是第三个独立来源。Provider 将它们转换为两条消息和 `response_format` 后发送。

因此，**当前 `prompt.py` 文件、版本号或 System 哈希都不等于完整的实际模型请求**。可信版本对比至少要区分：静态 System、User 组合规则及重试指令、动态输入、实际输出 Schema、模型请求配置。现有 Trace 对这些来源的记录不完整。

本审计在独立 Python 进程中，经真实业务服务和真实 CompatibleLLMProvider 截取了 13 种场景的 12 个 HTTP 请求体，30 项断言通过。HTTP 响应是本地脚本预设，不是模型生成；没有访问外部模型，没有 SQLite 连接，没有读 `.env` 或真实用户上传数据。不能把这些检查称为真实模型质量评测，也不能推定已有服务器进程已经加载了同样代码。

## 1. 实际加载与调用路径

以下文件均相对于仓库根目录 `/Users/lainey/Desktop/vibe-coding/insightflow`，完整源码保存在本目录 `audited-source.zip`，108 个文件的 SHA 在 `audited-source.sha256.json`。

| 节点 | 实际 System 定义 | 服务层绑定与请求 | 当前代码版本 |
| --- | --- | --- | --- |
| Intent Parser | `backend/app/intent/prompt.py:1–3` | `backend/app/services/intent_parser.py:11,98–120` | intent-v1.3.3 |
| Analysis Planner | `backend/app/planning/prompt.py:1–3` | `backend/app/services/analysis_planner.py:17,55–64` | planner-v1.2 |
| Insight Generator | `backend/app/reporting/prompt.py:1–4` | `backend/app/services/analysis_report.py:20,104–129` | report-insights-v1.1.9；generation=evidence-composition-v1.1.1 |

三个服务均使用 `from ...prompt import SYSTEM_PROMPT`。Python 在导入时绑定字符串，不是每次请求读取磁盘。修改磁盘文件不等于正在运行的服务立即使用新 Prompt；需要适当的进程重载。没有运行时 Prompt Registry 或快照解析。

`backend/app/main.py:35–61` 创建共享 Provider，再注入三个服务。模型设置取自 `Settings.from_env()` 的进程环境；应用不会自动读取 `.env`。默认应用在 `main.py:100` 导入时创建。本审计没有导入 main，避免初始化业务存储。配置文件中的值、代码默认值、已经运行的服务实例的值应分别看待。

主流程入口：

- Intent：`WorkflowOrchestrator.prepare_real()`，`workflow/orchestrator.py:214–233` → `nodes/intent_parser.py:24–25` → `IntentParserService.parse()`。
- Planner：同一 Workflow 的 `236–247` → `nodes/planner_v1.py:24–25` → `AnalysisPlannerService.plan()`。
- Report：`workflow/reporting.py:26–46` → 从 Repository 读取完整执行结果、批准快照、画像、会话原始目标 → `AnalysisReportService.generate()`。
- 独立 API：`api/intents.py:18–24`、`api/plans.py:25–39`、`api/reports.py:24–33` 复用相同服务。独立报告入口仅接收 imported 结果，不传批准快照、原始 query 参数或 Report Trace，上下文与主流程有明确差别。

`NodeInput` 的会话/运行标识由 Node 外层管理，节点 `process()` 仅把 payload 传给服务；它们不自动进入 LLM 消息。`LLMRequest.purpose` 是结构化输出名称，不是 Prompt 版本。

## 2. Intent Parser：真实 User 内容与重试分支

组合代码：`services/intent_parser.py:98–120`。User 实际为 `json.dumps(..., ensure_ascii=False)`：

```text
user_query                 用户原始需求，保留字符串
clarification_answers      已保存的用户补充答复列表
 dataset_context:
   dataset_name            DatasetProfile.file_name
   row_count               DatasetProfile.row_count
   columns[]               field_id / display_name→name / physical_type / logical_type
   sample_rows             恒为 []，当前版本禁止发送样本行
```

数据上下文由 `intent/context.py:6–19` 和 `domain/intent.py:ContextColumn/DatasetContext` 共同定义。没有发送 Profiler 的列样本、完整行数据或自动推断的 semantic_tags。字段名、文件名及用户原话仍然是模型输入数据，不是可信系统指令；“无样本”不等于完全不含敏感元信息。

Schema 来自 `ParsedIntent.model_json_schema()`，并非 prompt.py 中的独立静态文件。当前不确定性输出 Schema 用 issue/reason 别名；Planner 会按别名序列化输入，Report 默认 model_dump 的相关对象可能使用存储字段名。审计应保存实际序列化结果，不能仅凭公开示例重构。

首次请求无 feedback。解析/Schema/语义/溯源等可重试错误后，下次 User 增加 `validation_feedback`：

```json
{
  "previous_error_code": "实际失败代码",
  "stage": "实际阶段",
  "instruction": "按同一用户原话和系统规则重新生成完整 JSON；不要补造信息，不要输出解释。"
}
```

当代码是 `LLM_UNGROUNDED_OUTPUT`，instruction 改成服务层的另一段静态字符串：

> 约束raw_text只摘录一段真实连续原话；不要改写或把两处片段接成新句。未知筛选值留在uncertainty，不补造值。目标和不确定性解释允许忠实改写。重新生成完整JSON，不输出检查过程。

**这两段有效指令都不在 intent/prompt.py。** 重试仍是 system+user 两条消息，不附上轮 assistant 原始响应。默认最多 2 次，允许设置 1–3 次，共享总超时；连接失败等非可重试错误直接失败。

边界：上下文最大 64 KiB；实际 User 最大 96 KiB。空白需求在已有画像有效时返回 input_guard 澄清结果，0 次调用，但 Artifact 仍带 prompt_version。缺失画像先报 DATASET_CONTEXT_REQUIRED，0 次调用。不能以版本号存在证明发生过 LLM 调用。

## 3. Planner：能力说明也是模型指令的一部分

组合路径：`planning/context.py:9–43` → `services/analysis_planner.py:55–64`。

User 根对象按顺序包含：

- `intent`：从已有 IntentResult 取业务字段，`model_dump(mode='json', by_alias=True)`；IntentArtifact 的 parse_id、prompt_version、LLM 元信息不会传给 Planner。
- `core_requirements`：C01 是 business_goal；有 decision_goal 时追加；四类显式约束按 raw_text 组合为要求。不是自由改写的业务推断。
- `profile`：dataset_id、dataset_version、file_name、row_count；字段 ID/名称/物理与逻辑类型/非空数/缺失率/唯一值数；质量问题仅 code、field_ids。没有样本行。
- `capabilities`：来自 `CapabilityRegistry.summary()`，包括每种操作的参数 Schema、输入规则、输出规则、null_policy、logical_input_policy、支持函数和执行范围。

Registry 的英文规则字符串会进入 User，具有指令作用；修改 Registry 说明、params 模型或上下文组合器也可能影响模型行为，即使 planner/prompt.py 与其版本号没变。

输出 Schema：`planning/output.py:9–26` 调用 `CapabilityRegistry.request_schema()`，从 PlannerDraft 与六类参数模型构造受控操作分支；补全 required、去除 default、禁止额外字段，并把非空 pattern 改为适配约束解码器的表达。**请求 Schema 与直接导出 AnalysisPlan Schema 不同**，不能混为同一内容。

重试时增加：

```json
{"validation_feedback":{"code":"实际失败代码","instruction":"同一输入重新输出完整JSON；严格遵守参数Schema，不增加分析目标。"}}
```

这段也定义在服务层。默认最多 2 次；next_action=clarify 时 0 次调用。业务校验失败不进入无条件修复，Validator 的 F0 不触发 LLM 自动改计划。上下文上限 128 KiB，添加反馈后的实际请求上限 132 KiB。

Planner 返回的 VAP 包含 llm 和 provenance.notice 的 Prompt 标签；无单独 snapshot_id。会话保存 planner_result，但生成审核版时 `plan_review.validate_v1():113–120` 重新创建验证结果，仅复制 intent_snapshot；批准计划不能据此自动证明上游完整 Prompt 内容，亦不能断言会话中的原始规划元信息完全丢失。

## 4. Insight Generator：动态证据、范围文案与 Schema

实际路径：`reporting/contracts.prepare()` 校验输入 → EvidenceBuilder → `reporting/selection.select_evidence()` → `services/analysis_report.py:107–129` → Provider。

User 有 13 个顶层字段：

| 字段 | 实际来源/动态行为 |
| --- | --- |
| analysis_goal | Intent.analysis_goal.model_dump() |
| goal_coverage | 计划可行性、有效证据、未完成任务及未确认约束共同计算 |
| original_query | 显式参数或 business_goal 或空串，取前 2000 字符 |
| constraints | Intent.constraints；保留 unverified 信息，不因展示而宣称已验证 |
| constraints_confirmed | 默认 false；主流程核验批准快照后才使用其确认值 |
| scope_context | 全部任务，由 PlanPresentationMapper.steps() 把步骤转为业务文案 |
| fields | 全部画像字段 ID、名称、逻辑类型、上传范围缺失数 |
| uncompleted_tasks | 失败、跳过或无证据的任务及原因 |
| task_sample_context | 执行状态、有效样本数、样本定义、指标非空数 |
| tasks | 已有证据的任务 ID、优先级、业务问题 |
| evidence | 经选择与数量限制的证据，不是 EvidenceBuilder 的全部输出 |
| evidence_groups | 按 task_id/data_ref/result_field 分组的已选证据 ID |
| limitations | 服务层按实际输入拼接的固定边界、质量问题、失败及 Top N 等说明 |

容易遗漏的依赖：

1. `review/presentation.py:37–72` 的中文操作说明与 FUNCTIONS/OPERATORS 映射会进入模型输入，不只是前端显示。修改这些文案也影响 Prompt 组合。
2. `reporting/selection.py:2–25` 按任务优先级及 change_rate、comparison、difference、ranking 等排序；有业务证据时忽略 coverage 作为候选；按指标轮转，每任务最多 20 条、总共最多 80 条。证据顺序/限额变化会影响模型看见什么。
3. `services/analysis_report.py:78–96` 的固定说明与条件说明直接进入 limitations。数据质量消息、任务标题及失败原因也会影响 User。
4. `reporting/prompt.py:55–75` 从 InsightDraft 生成 Schema，并把当前 selected evidence IDs 写入 primary_evidence_id 和 evidence_refs 的 enum。同一 System、同一代码版本，不同证据对应不同实际 Schema。本地单/双任务截取已验证这一点。
5. Report User 最大 160 KiB；它不发完整原数据，但 Evidence 含真实结果值、类别和计算来源，不可一律按公开数据保存。字段与范围说明也应受控。

ReportService 没有内部模型重试循环；主流程重试是新的 Report attempt/Trace Run。无有效证据时返回 unavailable，Insight/Fact Validator 标记 skipped，0 次模型调用。HTTP/模型失败返回错误，不用模板伪造洞察；本地脚本的成功响应只是为了检验组装过程。

独立接口默认 query=business_goal、confirmed=false，并增加 imported 提示；主流程传 session.user_goal 和已核验批准快照。因此对比两条路径必须记录入口及确认状态，不能把差异归因于 System Prompt。

## 5. 最终 Provider 发出的内容

唯一组装处：`llm/compatible_provider.py:20–37`。实际 JSON 为：

```text
model: Provider 实例的 model
messages:
  - role: system; content: 服务已绑定的 SYSTEM_PROMPT
  - role: user; content: 服务生成的 JSON 字符串 instruction
response_format:
  type: json_schema
  json_schema:
    name: request.purpose
    strict: true
    schema: 服务当次生成的 response_schema
stream: false
enable_thinking: 仅 request 值不是 None 时发送
```

没有隐藏的 assistant 消息、额外提示词或 SDK 自动补充模板；本地 HTTP 截取与上述结构一致。Authorization 仅在请求头，不属于 Prompt；审计产物未保存请求头或密钥。

Provider 没有发送 temperature、top_p、seed 或 max_tokens；这些参数在供应端的实际默认值 unknown，不能记成 temperature=0。超时是客户端/服务设置，不是消息正文。`LLMResponse.model` 使用本地 `self.model`，没有采用响应体 model，因此目前记录的是**请求的模型名**，不能证明供应商内部物理模型版本。请求模型名本身也不保证重复运行确定性。

三个服务默认 thinking 配置并不相同：Intent/Planner 为 None（省略），Report 为 false；main 可用进程环境覆盖。本次截取显式使用 Intent=false、Planner=None、Report=false，模型名用 qwen3.8-flash，均是受控审计配置，不是对当前在线进程配置的观测。

## 6. 当前版本与 Trace 能证明什么

| 当前记录 | 能证明 | 不能证明 |
| --- | --- | --- |
| IntentArtifact.prompt_version / 日志 | 该服务结果带有的标签；parse_origin/attempts 可辅助判断调用 | 完整模板、每次 retry User、Schema 与实际消息正文 |
| Planner provenance.notice / 日志 | 服务返回的标签、尝试次数；原始结果可保存在会话 | 独立不可变 Prompt 内容；审批快照不自动保留全部上游来源 |
| Report RunManifest | 队列创建时的报告 Prompt 标签/System 哈希、代码磁盘 SHA、输入指纹、模型请求配置 | 全部三个节点的 Prompt 历史；实际 User 与 Schema；每次调用的不可变绑定 |
| Trace 的 evidence/llm_output/report 快照 | 已保存的受控结果投影与哈希 | 未保存的完整请求；脱敏投影不能倒推完整 User |

`observability/recorder.py:150–176` 在入队时局部导入 report prompt；ReportService 在模块导入时绑定 System；`workflow/reporting.py:49–56` 在完成后再次取 Prompt 标签。正常同进程无重新加载时三者可一致，但缺乏“实际请求内容 == 已登记快照”的强制验证。混合热重载/单独模块 reload/内存替换，以及磁盘文件先改而进程仍使用旧绑定时，都有记录与实际执行来源分离的风险。**这是代码层面的风险，不是已经证明历史记录发生了错绑。**

当前 `prompt_sha256 = digest(SYSTEM_PROMPT)` 的算法是：先把字符串按 JSON 编码，再做 SHA256；不是对裸 UTF-8 System 文本直接 SHA256。销售/招聘用户输入等指纹使用同一 digest 的对象编码规则。不能拿裸文本哈希与它直接比较并报冲突。

本次读到的 System 哈希（完整值见 `captures-v3/summary.json`）：

| 节点 | 裸 UTF-8 SHA256 前缀 | 当前 digest(System) 前缀 |
| --- | --- | --- |
| Intent | 9504f36790ff | 9366d0073183 |
| Planner | 42594e5314dc | 8bab1eaa6bee |
| Insight | 0fb9fdb223e3 | f81d3ed3d29f |

Git 检查：当前目录不是 Git 仓库，不能提供真实 source_commit。已有本地 ZIP 与部分历史 System 内容可追溯，但不可据当前代码补齐历史 User、Schema 或实际部署对应关系。前两轮盘点见 `../prompt-registry-v1-phase1-2026-10-29/audit-and-contract.md` 与 `../prompt-snapshot-v0.1-phase1-2026-10-29/audit-and-plan.md`；本轮没有覆盖这些结果。

## 7. 本地验证记录与限制

完整输入/输出请求及脚本预设响应保存在 `captures-v3/`，每份标记 synthetic_local_transport_capture、not_real_llm。Approved 分支用内存构造的批准夹具，不是对真实上传/审批/Engine 链路的验收。

| 案例 | 调用次数 | 实际观测 |
| --- | ---: | --- |
| I01 首次 Intent，含澄清答复 | 1 | 完整三段 User、画像元信息、空 sample_rows |
| I02 非法 JSON 后重试 | 2 | 第二次增加普通 validation_feedback |
| I03 溯源失败后重试 | 2 | 第二次改为真实连续原话修复指令 |
| I04 空输入 | 0 | input_guard |
| I05 缺画像 | 0 | DATASET_CONTEXT_REQUIRED |
| P01 首次 Planner | 1 | 含能力说明、6 个 Schema 操作分支；返回已验证计划 |
| P02 JSON 重试 | 2 | 原上下文保持，追加 Planner 专用 feedback |
| P03 待澄清 | 0 | INTENT_CLARIFICATION_REQUIRED |
| R01 独立 imported | 1 | query 回退、未确认状态、实际证据 |
| R02 内存批准上下文 | 1 | 使用传入原始 query 和确认标识 |
| R03 全部任务无有效结果 | 0 | unavailable，无模型调用 |
| R04 Provider HTTP 错误 | 1 | LLM_HTTP_ERROR，无内部重试 |
| R05 两任务 | 1 | 证据 ID enum 随选择集合改变 |

执行 `capture_requests.py` 最终结果：13 场景、12 请求、30/30 断言。SQLite connect 被禁止；没有导入 app.main。108 个业务源码的审计前后哈希全部相同。未运行完整 pytest，没有宣称现有全部业务测试通过。

前两次审计脚本运行的原始结果保留在 `captures/` 与 `captures-v2/`：第一次是脚本场景数量断言写错；第二次是无证据夹具错误地把 count 结果改为 null，业务 prepare 正确拒绝。说明和原脚本分别保留在 capture-attempt*-failure.txt、capture_requests.attempt*.py；不算模型质量 Bad Case，也不隐藏审计错误。

## 8. 后续快照设计应据此收敛的边界（尚未实施）

1. **静态版本包**：System 原文 + 各服务的 User 组合规范 + 静态 retry 指令 + 能力说明/Schema 生成器依赖 + 版本来源。仅给 prompt.py 建表不足。
2. **实际调用绑定**：在每次 Provider 请求前，绑定该次 System、已渲染 User、实际 response_schema、模型请求配置和 attempt。Report 动态 enum 必须属于当次绑定，而不能伪装成固定模板 Schema。
3. **输入内容与版本内容分开**：版本包不含完整用户数据；实际输入存受控引用/哈希，遵循权限与脱敏边界。只保存脱敏投影时明确不能精确重放。
4. **调用与跳过分开**：空输入、clarify、no_evidence 不能因为有版本标签就创建虚假的模型调用证明。
5. **哈希标明算法和范围**：裸文本、规范化模板包、实际请求应分别命名。保证有序消息、字符串内容、Schema、retry 阶段参与相应指纹。
6. **当前与历史分开**：无法证明历史部署关系时只能 reconstructed/unknown；不能用现在的 User 组合器和 Schema 填补旧版本。

本轮到来源审计为止；未创建 PromptSnapshot 表、未改造运行时，也未扩展 Admin 页面。
