# Prompt Snapshot Foundation V0.1 — 审计与实施提案

日期：2026-10-29，Asia/Shanghai。关联 REQ-0049，承接 REQ-0048 的 Registry 审计。

**状态：仅审计和方案，等待用户确认；未实现快照表、Runtime、迁移或节点改造。** Registry 列表/Diff/UI 继续后置，本轮不顺带实现。

## 1. 审计结论

### 1.1 三个节点的真实定义与消息

| 节点 | System 与版本来源 | User 的实际组成 | 输出约束 |
| --- | --- | --- | --- |
| Intent Parser | backend/app/intent/prompt.py；静态 import；人工声明 intent-v1.3.3 | 服务中构建 user_query、clarification_answers、dataset_context 的 JSON；重试加入 validation_feedback。反馈 instruction 有普通重试和 grounding 失败两种静态文字 | ParsedIntent.model_json_schema() |
| Analysis Planner | backend/app/planning/prompt.py；静态 import；人工声明 planner-v1.2 | planner_context() 产生 intent、core_requirements、profile、capabilities；重试加入包含静态 instruction 的 validation_feedback | planning.output.request_schema(registry)，从能力参数 Schema 生成 |
| Insight Generator | backend/app/reporting/prompt.py；静态 import；人工声明 report-insights-v1.1.9 | 服务组装目标、约束、批准范围、字段、成功/失败任务、样本口径、选中证据、证据组和 limitations 的 JSON | InsightDraft 基础 Schema，加本次 Evidence ID 枚举与既有 pattern 适配 |

版本不是 Git 自动生成，也没有统一的版本登记/冲突检查。三个服务各自 `json.dumps(..., ensure_ascii=False)`；键顺序、空格、Unicode、空值与重试分支都可能影响实际消息。

Provider 最终发送恰好两个 messages：`system=request.system_prompt`、`user=request.instruction`；另带 response_format=json_schema(strict=true)、model、stream=false 以及按原规则有条件发送的 enable_thinking。没有额外 system/user message，也没有显式 temperature/top_p。模型名由现有配置注入，Runtime 不能偷偷增加采样参数。

**不仅 System 常量是 Prompt 内容。** 例如 Intent/Planner 服务中的重试指令、User JSON 字段布局和动态 Schema 组合规则也必须被快照覆盖。只存 System 或 Python 文件 SHA 不能称为完整静态模板快照。

### 1.2 Trace 现状与缺口

- 已有 Trace V0.3 和分层导航，不止 V0.1/V0.2，但实际持久化 Run 仍仅覆盖 ReportWorkflow。
- Report Manifest 在 enqueue 时保存 prompt_version、generation、schema、Validator/Registry 版本；新记录还可保存 System 单项指纹、源码 SHA、输入 SHA、Git 信息。
- Manifest 的 prompt_sha256 使用项目 digest() 的 canonical JSON 字符串哈希，不是原始 UTF-8 文本哈希，更不是完整模板包哈希。
- 没有 PromptSnapshot。已有 `TraceSnapshot` 是 Evidence/LLM 输出/报告的受控投影，不是 Prompt 模板；不能沿用同一个对象含糊命名。
- 目前没有任何 Prompt snapshot_id 被带入 LLMRequest；无法强制“实际消息来自该不可变快照”。
- NodeInput.run_id / NodeOutput.run_id 已有，但不是持久化 TraceRun；Intent 的 parse_id 也不是 TraceRun；Planner 的 parse_id 只出现在服务日志/错误元信息。
- IntentArtifact 有 prompt_version，Planner 只在 provenance.notice 写版本。计划进入审核时重新 Validator 校验会生成新的 ValidatedAnalysisPlan，不能假设 Planner 的 llm/provenance 会自动完整保留到批准快照。
- Report 没有证据时跳过 LLM，Manifest 却仍可带版本号；必须区分“已绑定待调用”“确实发起”“未调用”。
- Trace 写入当前 fail-open；同样做法不适合权威模板快照。模板存储、调用绑定和可降级观测必须分层。

### 1.3 Git 与历史恢复

本次在项目目录重新执行 `git rev-parse --show-toplevel` 和 `git rev-parse --verify HEAD`，都返回非 Git 仓库。没有可读取的 Commit/分支/Git 历史；不初始化 Git、不提交、不访问远程。

此前静态审计发现 13 个具名 System 全文版本（Intent 6、Planner 2、Insight 5），另有未声明版本的 Planner baseline。它们保存在评测/源码档案，不是 Git 恢复证据，也不证明每个历史完整模板包与实际部署对应。

因此，**目前只能实现“工作区源文件+源码指纹 → 不可变快照 → Runtime → 调用绑定/Trace”的可验证链路；Git 起点应为 unknown。** 未来用户建立 Git 后，可额外记录真实 HEAD、dirty 和文件指纹。HEAD 相同但有未提交变更时，不应把工作区内容假称为该 Commit 中的内容。

原始证据见 before-source.zip、before-manifest.json、git-observation.json，及先前 Registry 的 prompt-content-inventory.json。本轮不改写任何历史档案。

## 2. 最小一致性方案

推荐不再让服务“拿当前 System 字符串组请求，然后只给它贴一个版本号”，而是在调用前使用固定 snapshot_id 解析和渲染：

```text
现有三个 Prompt 源模块 + 完整静态组合声明 + Schema 规则
  ↓ 校验实际源内容；有 Git 时登记真实 Commit，没有则 worktree + SHA
登记不可变 PromptSnapshot（事务提交）
  ↓ 按 node_id + 显式版本解析，禁止自动找 latest
从快照读取 System / User 组合定义 / Schema 规则
  ↓ 注入现有业务代码已经生成的变量，不改变分析逻辑
渲染并核对最终 LLMRequest
  ↓ 在模型调用前持久化 PromptCallBinding
原有 Provider.generate(request)
  ↓
现有 Trace Span/Event + RunManifest 的已固定 snapshot 引用
```

### 2.1 动态 User Prompt 的最小处理

先给现有三个源模块补充受控的静态组合声明，不重写上下文处理、Planner、Engine 或洞察校验。

- `system_template`：保存实际完整 System 字符串。
- `user_template`：保存有序 JSON 字段绑定定义，而不是虚构一段历史字符串模板。例如字段 user_query 从 runtime.user_query 取值；dataset_context 从原函数得到的上下文取值。
- `composition`：保存调用 purpose、消息顺序、根字段顺序、JSON 序列化规则、可选字段条件及初次/普通重试/grounding 重试分支。重试 instruction 的静态文字从原服务迁入声明，文字保持逐字相同。
- `variables_schema`：定义需要的变量和类型，变量值来自原有业务计算，不进入静态模板快照。限制的校验不得擅自收紧原来合法输入范围。
- `output_schema_spec`：Intent 保存实际静态 Schema；Planner 保存所需真实能力 Schema/组合规则；Insight 保存完整基础 Schema和按实际 Evidence ID 绑定 enum 的明确规则。最终请求 Schema 另记录哈希，不冒称一个静态 Schema 就是所有历史请求的最终 Schema。
- Renderer 只支持本轮所需的取值、可选字段、JSON 序列化和 Schema 绑定操作；不执行任意 Python、SQL、Jinja 表达式，也不动态 exec 历史代码。

这里是**为新运行建立完整声明**，不是把现在新建的声明反向冒充旧版本原件。历史只保存 System 时仍是部分来源，不能标为“完整快照已恢复”。

要先对原组装逻辑建立固定输入基线，再迁移这三个很小的渲染接缝：System 和 User 的 UTF-8 内容逐字比较、JSON 字段顺序/空格比较、输出 Schema/模型请求参数比较；业务验证、原重试上限和总超时不改变。不能只用“JSON 解析后相同”代替 User 消息字节相同。

### 2.2 快照是运行时依据

- 三个服务不能使用未绑定的原始模板绕过 Runtime；配置指定 node/version，不允许 `latest` 自动回退。
- 实际请求的 System 和 User 必须由已解析的快照组合定义生成。用于渲染的 Schema 规则和 Renderer 版本也必须匹配；缺少支持的旧 Renderer 时明确失败。
- 快照读取后复核 content_hash；最终调用前再次校验绑定的消息/Schema 指纹与待发送请求一致，防止绑定后被改写。
- 同一逻辑调用的合法重试继续使用已固定 snapshot_id；每次尝试有独立 call_id/attempt 和实际请求哈希，反馈变化不产生新静态快照。
- 不改 Provider 的消息、model、stream、thinking、超时、输出校验或业务决策；Trace 元信息不作为模型消息发送。
- 空 Intent 的 input_guard、Report 无证据分支仍不调用模型，不为了展示 snapshot_id 人为新增一次调用。

## 3. PromptSnapshot 契约（提案）

```text
PromptSnapshot
  snapshot_id               持久化唯一 ID
  prompt_id / node_id        稳定的 Prompt 与节点身份
  version                   源模块明确声明的版本，不从目录名猜测
  definition_format         prompt-definition-v0.1
  system_template           完整真实 System 文本
  user_template             完整有序 JSON 组合定义
  composition               消息顺序、序列化配置、静态重试分支
  variables_schema          版本化的变量定义
  output_schema_spec        真实基础 Schema + 必要的确定性绑定规则
  renderer_version          对应受控 Renderer 的明确版本
  content_hash              完整静态定义包的 SHA256
  hash_algorithm            insightflow-canonical-json-v1
  source                    git/worktree/archived_source、真实 Commit 或 null、dirty、文件 SHA
  created_at                首次登记 UTC 时间，不冒充原始创作或上线时间
  change_summary            明确登记说明，不能用模型编造历史改动
```

新运行可用的 Snapshot 必须具备完整静态模板/组合/变量/输出规则，不接受“System 全文 + user_template=null”作为可执行完整快照；这与先前只读 Registry 展示残缺历史内容的提案不同。

### 3.1 稳定哈希

定义包仅包含 definition_format、System/User 定义、composition、variables_schema、output_schema_spec、renderer_version。序列化采用 UTF-8、ensure_ascii=false、sort_keys=true、separators=(',',':')、allow_nan=false；不做 trim、换行替换或 Unicode normalization。算法版本固定，不宣称等同 RFC 8785。

- 静态字典的键排序不改变哈希；**字段输出顺序写成数组**，顺序变化必须改变哈希。
- System/静态反馈文字的任何空格、换行变化都会改变哈希。
- 非 JSON 值、NaN、Infinity、导入重复键拒绝，不隐式转换后登记。
- version、snapshot_id、Git、创建时间、说明、运行变量、模型参数不进入内容哈希。版本标签不同但内容相同允许同 content_hash；不能强制产生非空 Diff。
- 另外保留命名清晰的单项 system_text_sha256 / rendered_user_sha256 等，不能与旧 Trace 的 canonical-string digest 混用。

### 3.2 幂等与冲突

按 `(node_id, version)` 解析。相同键、相同内容反复登记返回原 snapshot_id；同键不同内容返回冲突，不覆盖、不自动升级版本。同内容、不同显式版本可以分别保存不可变版本绑定，底层定义按 content_hash 去重。

若相同内容后来出现在另一个 Git Commit，不能改写旧 Snapshot 的首次来源；本次 RunManifest 可另外记录运行时实际来源，避免混淆登记来源与运行来源。增加新来源证据应采用追加记录，不能 UPDATE 旧快照。

## 4. PromptCallBinding 与 Trace 对接

PromptCallBinding 不是另一套工作流 Run，也不保存分析状态/结果；它只证明“发起调用前，哪个请求绑定了哪个快照”。

```text
PromptCallBinding（不可变）
  call_id / operation_id / attempt
  node_id / snapshot_id / version
  session_id / node_run_id / trace_run_id / span_id（无关联时 null）
  rendered_system_sha256 / rendered_user_sha256 / response_schema_sha256
  request_content_hash / purpose
  model_config_hash（不含密钥）
  created_at
```

不保存原始用户数据、完整数据集、API Key 或完整渲染请求。绑定记录存在只说明 prepared，不等于网络调用已经发生；调用开始、返回和中断继续通过已有观察事件表示。进程可能在绑定后、发送前退出，不能把 prepared 当成 returned。

### 4.1 Intent / Planner

复用现有 NodeInput.run_id 与 parse_id 作为关联标识，通过薄适配传入三个服务的 RuntimeContext；并发上下文不依赖全局可变变量。独立 API 没有 session 或 TraceRun 时仍有真实 call_id/operation_id，空关联保持 null，不创建假 execution_id。

当前它们没有持久化 Trace Span，因此 V0.1 **先提供调用绑定记录，已有 Trace 上下文存在时记录同一 snapshot_id；不把它们伪装为 Report Span**。不能仅从 Session 的当前 Intent 或 Planner provenance 文本回填旧 Report Manifest。若要把这两个阶段也完整显示成 Run Explorer 中的独立 Run，需要另行扩展现有 TraceRun 契约；本方案不隐含承诺已完成该扩展。

这是本次需确认的边界：三个节点都能持久化请求前绑定；现有 Report Trace 实际可跳转，前两个阶段可按既有节点调用标识追溯绑定。全流程阶段 Trace 后续再接，不在基础快照任务中创建平行 Run。

### 4.2 Report 的不可变 Manifest

Manifest 在 enqueue 时已不可变，不能等调用结束再 UPDATE snapshot_id。建议：

1. 新报告尝试在入队时先解析/固定完整静态 Snapshot，并持久化与 `(execution_id, report_attempt)` 的关联；不需要提前执行 Evidence Builder 或调用模型。
2. 新 RunManifest 保存固定 snapshot_id/content_hash，明确是 reserved 引用。
3. Worker 使用该 ID 渲染，不重新取当前最新模板；实际调用前写 Binding，并在 Insight Span/Event 保存 call_id/snapshot_id，验证与 Manifest 固定 ID 一致。
4. 后续无证据跳过时记录 not_called；Manifest 的引用不能被展示为已实际使用。
5. 服务重启后按持久化 attempt 绑定恢复；不悄悄改用新模板。新明确重试可以绑定新的已登记版本，并与旧 attempt 分开。
6. 旧 Manifest 不回填；旧排队任务若没有可核验固定绑定，返回明确缺失错误，让用户通过原明确重试流程产生新尝试，不伪造其旧版本。

此处只增加静态固定/观察接缝，不改审批和 Engine。即使报告快照失败，已成功 ExecutionResult 保留。

## 5. 数据库迁移与故障策略（提案）

### 5.1 推荐独立权威快照库

新增 `<data_dir>/prompt_snapshots.sqlite3`，不把权威模板放入当前 best-effort `observability/trace.sqlite3`。原因是两者故障语义不同：Trace 关闭/降级不应决定是否可以忽略模板绑定。不是新服务或新 Run 存储。

仅增表，不删除/迁移原业务或 Trace 数据：

- `prompt_snapshot_contents`：content_hash PK、definition_json、hash_algorithm；静态定义去重。
- `prompt_snapshots`：snapshot_id PK、node_id、version、content_hash FK、source_json、created_at、change_summary；UNIQUE(node_id,version)。
- `prompt_call_bindings`：call_id PK、snapshot_id FK、operation/attempt/context/hash 等；只追加。
- `report_prompt_bindings`：UNIQUE(execution_id,report_attempt)，固定本次报告模板；只追加。不复制执行结果、计划或审批记录。
- 小型 schema_version 记录，迁移事务提交。快照内容/版本/绑定表拒绝 UPDATE/DELETE；普通读写操作有超时，不能无限等锁。

并发登记用数据库唯一约束与事务判定，相同内容返回同一版本绑定，冲突不吞掉。快照表与固定绑定提交成功后才允许模型调用。Trace 是跨库观察，不宣称多库强一致事务；绑定库是事实依据，Trace 可能有缺口。

### 5.2 明确故障语义

| 情况 | 建议错误代码 / 行为 |
| --- | --- |
| 快照缺失 | PROMPT_SNAPSHOT_NOT_FOUND；不调用模型，不找 latest |
| 同版本内容冲突 | PROMPT_VERSION_CONFLICT；不覆盖 |
| 读取内容与哈希不符 | PROMPT_SNAPSHOT_INTEGRITY_ERROR；不调用模型 |
| 模板/变量/Schema 规则渲染失败 | PROMPT_RENDER_FAILED；不调用模型 |
| 待发送消息与绑定不一致 | PROMPT_REQUEST_MISMATCH；不调用模型 |
| 快照库读写或调用前绑定提交失败 | PROMPT_SNAPSHOT_STORAGE_UNAVAILABLE / PROMPT_BINDING_STORAGE_UNAVAILABLE；不调用模型 |
| Renderer 不支持该快照格式 | PROMPT_RENDERER_UNSUPPORTED；不执行旧 Python 源码 |
| Trace 写入失败但快照/Binding 已提交 | 仍使用已固定正确快照；沿用 Trace 降级，记录受控日志/追踪缺口 |
| 模型失败 | 原 LLM 错误与重试规则保留，绑定照实存在，不伪装为成功 |

这是**需要明确接受的新增可用性门槛**：快照与调用前绑定采用 fail-closed，Trace 保持 fail-open。不能把权威快照错误放进原观测吞错函数，也不能用 Mock 或当前模板兜底。快照错误不属于 LLM 输出格式重试，不反复调用模型；对外保留明确代码而非被 Provider 错误包装掩盖。

本轮不改变业务判断，但存储不可用时会比原系统更早拒绝模型调用，属于本任务要求的可靠性策略；不能一面 fail-closed，一面声称故障时仍完全等同旧行为。

## 6. 历史恢复分类

单独输出 HistoricalPromptRecovery，不把残缺来源硬塞成可执行 PromptSnapshot：

- verified：完整模板/组合/变量/Schema 规则可恢复，并有可靠证据证明对应版本与实际部署/调用；写明证据与验证范围。只有源码/版本标签/Commit 还不够。
- reconstructed：从真实 Git Commit 恢复完整定义，但部署关系未证实；不得自动升级 verified。
- unavailable：无法恢复完整定义，保留原因和仍可读取的部分组件。

当前无 Git，Git 恢复结果为 unavailable / GIT_HISTORY_UNAVAILABLE。已有档案中的 13 个 System 原件继续保存并展示 available_components，不能据此自动标为完整模板 verified，也不能按用户给定定义冒称“从 Git reconstructed”。未声明版本的 baseline 也不擅自命名。

以后有 Git 时只读固定 Commit/path，记录 HEAD/dirty/文件指纹；不 checkout、不修改工作区、不执行历史 Python，也不以提交时间充当部署证明。

新运行的请求前绑定可以提供后续实际使用证据，但证明范围是模板/消息绑定；默认未保留原始变量与全文请求，不能宣称将来一定能逐字复现每次历史用户数据输入。

## 7. 拟修改文件

新增：

- `backend/app/domain/prompt_snapshot.py`：Snapshot、Binding、Recovery 契约。
- `backend/app/prompts/definitions.py`：三节点静态完整定义、版本与受控来源封装。
- `backend/app/prompts/rendering.py`：固定版本 Renderer 与 Schema 绑定。
- `backend/app/services/prompt_runtime.py`：解析、哈希校验、请求前绑定、调用一致性检查。
- `backend/app/storage/prompt_snapshot_repository.py`：权威库、迁移、事务、幂等/冲突、不可变保护。
- `backend/scripts/register_prompt_snapshots.py`、`recover_prompt_history.py`：固定来源登记与只读历史恢复报告。
- 专项测试：Snapshot/Renderer/Runtime/Trace 集成与旧行为基准。

最小调整：

- 三个现有 Prompt 源模块：补齐 User 组合/变量/Schema 声明，System 原文与版本标识不擅自改变。
- 三个 LLM Service、对应 Node 适配器及 llm/base.py：统一绑定接缝与可选 RuntimeContext；保留现有业务输入输出契约，内部 Prompt 元信息不发送给模型。
- main.py：注入 Snapshot Repository/Runtime；权威快照初始化失败按明确调用错误处理，健康/已有结果查询不伪装模型可用。
- workflow/reporting.py：报告 attempt 固定模板与恢复规则；不改 Engine 执行结果。
- domain/tracing.py、observability/recorder.py：新 Manifest 可选快照引用、Span/Event 白名单中的 ID；旧记录默认 unknown，不修改旧 Manifest。
- 仅必要的只读查询/展示接入，用于查看已登记快照和调用绑定；不提前做 Prompt Registry 列表、Diff、在线编辑、发布或 Playground。

不修改 HITL 审批资格、计划版本算法、Validator 可行性规则、统计计算内核、Report 事实校验规则或 LLM 参数。

## 8. 确认后实施顺序与测试

1. 冻结当前三个服务最终 LLMRequest 的本地行为基线：固定四领域合成上下文，覆盖初次调用、Intent 两类反馈、Planner 反馈、Report 动态 Evidence/空证据、Unicode/空值/键顺序。
2. 实现 Snapshot 契约、稳定哈希、事务迁移、同键幂等/冲突、并发和不可变保护；导出三个当前真实模板的快照示例。这是实际源码快照，不冒充已调用真实模型。
3. 小步引入 Renderer/Runtime，逐字比较旧/新 System、User；比较 Schema、Provider payload 和参数保持一致。无需以外部模型输出“碰巧相同”证明请求未改变。
4. 接入三个服务的调用前绑定；断言缺快照、损坏、渲染失败、存储失败等场景 Provider 调用次数为 0。重试、并发上下文、独立 API、非 LLM 分支不得串版本或新增调用。
5. 接入现有 Report Manifest 的入队固定与实际 Span 绑定，测试重启、重试、旧缺失、跳过、Trace 断写但模板正确、快照断写不调用模型。旧 JSON/审批/ExecutionResult 不变。
6. 历史恢复报告严格区分 verified/reconstructed/unavailable；当前真实目录应报告 Git 不可用，另用临时测试 Git 仓库验证恢复逻辑，不初始化用户项目。
7. 后端全量测试、相关 Admin 类型/构建验证；保存真实源码快照、请求对照与 Binding/Trace 示例，所有失败记录保留。

除非后续明确授权具体数据与外部目的地，本轮基础设施验证不额外触发真实外部 LLM 调用。受控 Provider 仅用于请求契约/故障注入，报告明确标为测试替身，不伪装模型质量评测。

## 9. 待确认的四点

1. 当前无 Git：先以 worktree + 文件 SHA 完成新运行链路，Commit 显示 unknown；Git 历史恢复如实 unavailable，不擅自初始化 Git。
2. 完整新快照覆盖 System、User 有序组合、静态反馈、变量定义和输出规则；先建立请求逐字基线，再做最小渲染接缝调整。
3. 权威快照/调用前绑定 fail-closed；Trace 仍 fail-open，独立存储、明确缺口。
4. 三节点均有真实请求前 Binding；Report 写入现有 RunManifest/Span，Intent/Planner 复用已有 node_run_id/parse_id，不在本轮伪造或扩建全流程 Run 体系。

确认后再进入实现；以上所有表、错误代码、文件路径与扩展字段当前均是提案，尚未写入应用代码。
