# Prompt Registry V1 — 第一阶段审计与数据契约提案

日期：2026-10-29（Asia/Shanghai）。需求：REQ-0048。**本轮只完成审计和提案，未实施 Registry、API、页面或 Prompt 加载重构；等待用户确认。**

## 一、结论

1. 三个真实 LLM 服务均从各自 Python Prompt 模块导入 `SYSTEM_PROMPT` 和版本号，通过已有 `LLMRequest` / OpenAI-compatible Provider 发送。没有 Prompt Registry，也没有可查询 Prompt 的 Admin API。
2. **历史不是只有版本号**：源码快照及评测目录保存了可核验的 System Prompt 全文。静态审计确认 **13 个具名版本**：Intent 6、Planner 2、Insight 5。重复副本不计作新版本；只发现版本号/差异说明的版本不补造全文。
3. **User Prompt 不是独立静态模板**：三个节点都在服务内拼 JSON，且 Intent/Planner 有重试反馈；Report 的 Schema 会动态绑定 Evidence ID。没有统一保存每次完整渲染请求。因此 Registry 不能把当前 User Prompt 或 Schema 套到全部历史版本。
4. 现有 Trace 只覆盖 ReportWorkflow。RunManifest 的 `prompt_version` 是报告 Prompt，不是三个节点的完整 Prompt 清单；Intent/Planner 在该 Run 的实际调用版本不能据此确定。
5. 当前目录没有 Git；`source_commit` 必须为 null / UI unknown。文件 SHA、归档日期、版本号都不能替代提交记录。

## 二、当前三个节点

| node_id / 拟定 prompt_id | 文件、加载与当前版本 | User Prompt 实际组成 | 输出 Schema |
| --- | --- | --- | --- |
| intent_parser / intent-parser | app/intent/prompt.py，服务静态 import；intent-v1.3.3 | user_query、clarification_answers、dataset_context；重试可能加入 validation_feedback | ParsedIntent.model_json_schema()，不是包含调试字段的 IntentArtifact |
| analysis_planner / analysis-planner | app/planning/prompt.py，服务静态 import；planner-v1.2 | planner_context()：intent、core_requirements、profile 元数据、capabilities；重试可能加入 validation_feedback | planning.output.request_schema(registry)，包含受控操作参数，修正结构化解码的非空正则 |
| insight_generator / insight-generator | app/reporting/prompt.py，服务静态 import；report-insights-v1.1.9；generation=evidence-composition-v1.1.1 | analysis_goal、goal_coverage、original_query、constraints、constraints_confirmed、scope_context、fields、uncompleted_tasks、task_sample_context、tasks、evidence、evidence_groups、limitations | reporting.prompt.request_schema(selected)：以 InsightDraft 为基础，动态限制 primary_evidence_id / evidence_refs 为本次实际 Evidence ID |

Intent 上下文由 DatasetProfile.fields 构建字段元信息，目前不实际发送样本值。Planner 上下文不发送原始行；Report 仅发送受控选中的证据与统计口径，不发送全量数据集。Registry 登记的是静态来源和组装约定，不把请求中的用户目标、数据样本或实际 Evidence 当成模板变量默认值。

Provider 将两个消息发送为 system=`system_prompt`、user=`instruction`，输出要求 json_schema strict=true，stream=false。没有发送 temperature/top_p；不能为历史填默认值。现有适配器响应中的 model 仍为请求模型名，不证明供应商解析出的物理模型版本。

### 配置观察

只读取 backend/.env 中模型名、超时、重试和 thinking 的白名单键，没有复制或输出 API Key / Endpoint / 管理凭证。文件当前记录 qwen3.8-flash、30 秒、Intent 两次尝试和 thinking=false；Planner 默认两次尝试、thinking=null（未设置），Report 默认 thinking=false。**这是文件配置与代码默认值的观察，不证明当前后台进程已经加载这些值。** 模型配置按 Run 保存，不塞入不可变 PromptVersion 后再冒充全部历史运行配置。

证据：current-node-map.json、public-config-observation.json；当前审计源码已冻结为 audited-current-source.zip 与 SHA 清单。

## 三、已保存历史内容的范围

本次只对实际源码和 ZIP 内源码使用 AST + literal_eval 提取常量，**没有 import/exec 历史 Python 文件**。逐个保存来源路径、源文件 SHA、System 全文 SHA、与现有 Trace 兼容的 System 哈希。没有把评测名称当成源码中的版本常量。

| 节点 | 可核验完整 System Prompt 的具名版本 | 示例来源 |
| --- | --- | --- |
| Intent | intent-v1.1 / v1.2 / v1.3 / v1.3.1 / v1.3.2 / v1.3.3 | docs/evaluations/intent-v*/prompt.py、frozen-source/backend/app/intent/prompt.py、v1.3.3/prompt.txt 与 freeze-manifest.json |
| Planner | planner-v1.1 / planner-v1.2 | planner-v1/frozen-source/backend/app/planning/prompt.py；v1.2/prompt.txt、快照与 freeze-manifest.json |
| Insight | report-insights-v1.1.4 / v1.1.6 / v1.1.7 / v1.1.8 / v1.1.9 | insight-generator-v1.1 的 baseline/candidate-source；v1.1.1 的 candidate/candidate-02/final-source |

另有 Planner baseline 的完整 System 文本但没有 PROMPT_VERSION，不擅自命名为 planner-v1.0。未在本次可核验完整源码范围中找到的具名版本（如仅留在变更记录中的 Insight v1.1.5），不能根据当前文本推导后登记。后续如发现其他真实原件，可以独立追加来源核验。

以上 **13 是 System 文本版本数，不是“13 个完整 System/User/Schema 请求包已经全部恢复”**。没有验证过的历史 User 组装、变量 Schema、输出 Schema 仍缺失，登记时逐项标记。

重要事实：已保存的 report-insights-v1.1.7 和 v1.1.9 的 System 文本 SHA 都是 `0fb9fdb223e321234403eca792bd4421d80719469f028230cb4b31d2d5e551ef`。两者 System Diff 为零；这不证明 User 组装、Schema、校验器或模型效果相同。Planner v1.1→v1.2 的真实 System Diff 则包含高风险场景检查等新增规则。

清单见 prompt-content-inventory.json；两个只读文本对比例子见 real-v117-v119-system.diff、real-planner-v11-v12-system.diff。本审计扫描顶层源码 ZIP 与目录中的原件，没有递归解包 ZIP 内的 ZIP，不宣称找齐未知全部历史。

## 四、RunManifest、实际调用与关联缺口

- 历史 Report Run 保存 `versions.prompt_version`、generation/schema/Validator/Registry 标识及若干磁盘源码 SHA；V0.3 新 Run 增加 `versions.prompt_sha256`，由 `digest(SYSTEM_PROMPT)` 生成。
- `digest` 是 UTF-8 **canonical JSON 字符串**的 SHA256，不等同于原始文本 UTF-8 SHA256。解析时必须注明算法；不能直接拿 Registry 的整包 content_hash 比较。
- Manifest 在 **Report enqueue** 时建立，尚不是实际 LLM 请求时刻。服务内导入的常量、磁盘源码与重新导入模块若发生热修改，不能无条件声称一致。
- 没有证据时 Insight Span 会 skipped、没有模型调用，但 Manifest 仍可能有 Prompt 版本。UI 要显示“记录的版本；LLM 未调用”，不能称为“已使用”。
- IntentArtifact 有独立 prompt_version，但 Session 当前值可变；Planner 仅在 provenance.notice 中写 Prompt 标识，ValidatedAnalysisPlan 没有结构化 PromptVersion 引用。不能拿当前 Session、当前模块或报告节点的版本补历史上游调用。
- 在默认及两份既有验证 sidecar 中只读观察到 **6 条** Report Run，保存版本均为 report-insights-v1.1.9；这只是所检查目录的记录，不是全项目运行总量。没有更改这些记录。

V1 应先把已有 Report Trace 接到 Registry。三个节点的静态 Prompt 都能查；Intent/Planner 的 Run 关联缺失明确 unknown，不增加节点、不创建虚假的上游 Span。本轮可以仅在既有 Insight LLM 观察点记录实际 `LLMRequest.system_prompt` 的指纹和版本元信息，作为附加只读观测；不修改业务请求内容、审批、执行和 Prompt 加载。

## 五、最小 PromptVersion 契约（待确认，未实现）

所有用户要求字段均保留，增加少量来源与完整性信息。

| 字段 | 类型 / 含义 |
| --- | --- |
| prompt_id | 稳定 ID：intent-parser / analysis-planner / insight-generator |
| node_id | 对应已有节点：intent_parser / analysis_planner / insight_generator |
| version | 来源明确保存的原版本标识；不能由目录名或当前值猜测 |
| content_hash | `sha256(canonical JSON(已保存的静态内容包))`，算法固定并标明；不包含 version、创建时间、模型配置或变更摘要 |
| system_template | 非空的真实 System 全文；导入时从固定来源提取，不只保存一个版本号 |
| user_template | string 或 null；有真实静态模板时才填。现有三个节点没有独立静态模板，因此不捏造模板文本 |
| variables_schema | JSON Schema 或 null；只有依据对应版本的保存契约核实后填；历史无法核实时 null |
| output_schema_ref | 不可变 Schema 资产/生成器描述的内部引用或 null；不能指向会随当前代码变化的裸文件路径 |
| source_commit | string 或 null；没有真实提交证据即 null |
| change_summary | string 或 null；取已有版本说明并附来源，缺失则 unknown，不让 LLM 编造 |
| created_at | Registry **首次登记时间**（UTC）；不是假称 Prompt 原始创作或上线时间 |
| user_assembly_ref | 内部受控资产引用或 null：对应历史/当前真正保存的 User JSON 组装源码，作为“组装源码”单独展示与 Diff，绝不冒充实际渲染 User 消息 |
| source_refs | 来源列表：固定目录/ZIP 成员、来源文件 SHA、归档清单引用；后端内部 allowlist 解析，客户端不可指定任意本地路径 |
| completeness | system_only / system_with_assembly；细项缺失保留 null，不称为完整请求包 |

### User Prompt 的兼容决定

推荐 **保留 user_template，但允许 null；增补 user_assembly_ref**。原因：当前不存在独立字符串模板，直接把一份新 JSON 占位模板保存为所有旧版本，会制造不存在的历史。

详情页分别显示 System 全文、真实 User 组装源码、可核验的变量约定和输出 Schema；实际渲染请求没有保存就显示 unknown。若未来增加独立静态模板，可在新版本使用 user_template，不重构本轮业务加载方式。

### 动态输出 Schema

- Intent：保存本版本真实 ParsedIntent Schema 的不可变 JSON 资产；历史资产未保存时不填当前 Schema。
- Planner：保存 Schema 生成器及所需 Registry/模型契约的来源与哈希；当前资产可导出真实 Schema。历史缺依赖时明确不完整。
- Insight：保存真实基础 Schema 与“Evidence ID 枚举按本次调用绑定”的生成器描述。静态基础 Schema 不能冒充某个历史请求的最终 Schema；请求特定 Schema 未保存则未知。

### 不可变性与哈希

在既有 `<data_dir>/observability/trace.sqlite3` 追加独立的 `prompt_versions` 与不可变资产存储，由 PromptRepository 管理；不复制 Run 或改变业务库。唯一键 `(prompt_id,version)`；同内容重复导入幂等，不同内容同版本报冲突，禁止覆盖，不能自动悄悄升级版本号。登记元数据、静态内容和资产均不可修改；没有 Admin POST/PUT/DELETE。

首次登记通过受控离线导入命令，来源清单固定。导入历史文件只做静态解析，不执行历史代码；缺少原件的版本暂不登记为内容已存在。数据库更新/删除保护、读取时哈希复核、版本档案共同保留；不宣称能抵御有文件系统权限的管理员篡改或替代备份。

静态内容包哈希包括 System、真实 User 模板（可 null）、User 组装资产哈希（可 null）、变量契约及输出 Schema 资产内容哈希（可 null）。缺失标记参与哈希。另计算 System 单项哈希用于匹配既有 Trace；不把版本号不同强制变成文本不同。后续新增来源或补齐内容必须形成新的明确登记记录，不原位更改已登记 PromptVersion；同原标签冲突留待人工处理。

## 六、Run 关联返回契约（提案）

`GET /admin/runs/{run_id}/prompts` 返回 `items`，每项：

- node_id、span_id（如有）、prompt_id、recorded_version、registry_version_ref（可 null）。
- call_status：not_called / attempted / returned / unknown。skipped 无证据是 not_called，配置版本不冒充已调用版本。
- resolution：hash_verified / version_only / unknown / conflict / unregistered。
- recorded_hash、hash_algorithm、hash_capture_stage、verification_scope；来源可为 invocation、queued_manifest、saved_source_file，分别标明。
- reason：为何可关联、仅标签关联或不能关联。

优先使用请求点保存的版本/指纹；对原有 Run 只读取当时的 Manifest/Event/来源指纹。已有 queued_manifest 哈希仅证明入队时记录内容，不能升级为请求点验证。旧版本号能唯一命中登记内容时可跳转，但以 version_only 明示“未核验实际请求内容”；无版本则 unknown，不提供当前版本替身。

hash_verified 只在已有运行证据确实验证对应组件时使用，并写清 system_template_only 或完整包；不能把验证 System 扩成验证整个 User/Schema。冲突不可自动挑“最新”。不将 Registry 登记状态当成 Workflow 发布或模型质量验收。

## 七、只读 API 与页面计划

所有新查询复用现有管理员 Header/HttpOnly Cookie、403/503 默认关闭、AppError 和 no-store。可以提取共享鉴权依赖供 Trace 与 Prompt 路由复用，但保持旧鉴权行为与接口不变，不增加新的登录系统。

```text
GET /admin/prompts?node_id=...&limit=...&offset=...
GET /admin/prompts/{prompt_id}/versions?limit=...&offset=...
GET /admin/prompts/{prompt_id}/versions/{version}
GET /admin/prompts/compare?left_prompt_id=...&left_version=...&right_prompt_id=...&right_version=...&component=system_template|user_template|user_assembly
GET /admin/runs/{run_id}/prompts
```

继续提供 `/api/v1/admin` 别名前缀。比较静态路由放在动态 ID 路由之前。不存在的 Prompt/版本返回 404；旧 Run 的版本缺失是成功响应中的 unknown，而不是查询最新版本。跨节点文本比较允许明确标注跨节点，只比较文本，不暗示演进关系；默认 UI 在同一个 Prompt 内选版本。缺失 User 内容返回 unavailable，不能用空字符串当成“无差异”。

前端：

- `/prompts`：三个节点列表、按节点筛选、历史数量、缺失提示。
- `/prompts/:promptId`：该 Prompt 的真实版本历史。
- `/prompts/:promptId/versions/:version`：全文、来源、哈希、完整性、复制内容。
- `/prompts/compare?...`：左右并排逐行 Diff，保留版本和 URL，刷新可恢复。
- 原 `/prompts/versions` 保留为比较选择页的兼容入口，静态路由不被 `:promptId` 吞掉；Playground 继续后期占位。
- Run Detail 和 Insight Inspector 从 Run-Prompt API 展示关联；Intent/Planner 未采集时显示 unknown。所有未鉴权、空记录、请求失败、未登记和同文本 Diff 均分开处理；用文本渲染防止 Prompt 内容被当作 HTML/JS 执行。

## 八、确认后的文件变更计划

新增（拟定）：

- backend/app/domain/prompt_registry.py：PromptVersion、列表/对比、RunPromptBinding 契约。
- backend/app/storage/prompt_repository.py：同一 sidecar 中的只追加内容和资产。
- backend/app/services/prompt_registry.py：固定源导入、哈希、Diff、绑定解析。
- backend/app/api/admin_prompts.py：只读 API，复用鉴权。
- backend/scripts/import_prompt_registry.py：受控离线初始登记，不提供在线写入。
- backend/tests/test_prompt_registry.py、test_prompt_registry_api.py：不可变、真实来源与权限、关联、Diff。
- admin/src/api/prompts.ts、types/prompts.ts；PromptListPage / PromptHistoryPage / PromptVersionPage / PromptComparePage 和组件测试。

调整（仅必要接入）：

- api/admin.py / main.py：共享只读鉴权与挂载；旧 Trace 行为不变。
- 既有 Trace Recorder/Insight 观察点：可选记录实际请求的 Prompt 指纹，观测失败仍 fail-open；不新增 Run/LLM 节点，不改请求文本或业务决策。
- Admin navigation/routes：替换 Prompt 占位页并保持旧路由兼容。
- TraceShared / TraceDetailPage / NodeInspector：展示关联链接与核验层级，不用当前配置补历史。

不修改 Planner、Validator、HITL、Engine、Report 的业务规则与三个 Prompt 原文，不重构 Prompt 加载机制，不提供在线修改、发布、Playground 或自动评测。

## 九、验收设计

1. 对上面 13 个具名 System 版本逐个核对来源 SHA 和真实文本；缺源码/无原版标识不伪造登记，历史依赖缺失明确标识。
2. 同键同内容幂等，不同内容冲突；UPDATE/DELETE 拒绝；重启读取与哈希复核。
3. Intent、Planner、Insight 当前 Prompt 可查询；User 动态组装/动态输出 Schema 与缺失原始请求得到正确标签。
4. Planner v1.1→v1.2 确实有文本增量；Insight v1.1.7→v1.1.9 的 System Diff 必须为空；缺失 User 内容不能输出“文本完全相同”。
5. Report Run 入队版本、调用中版本、未调用 LLM、版本缺失、只有版本号、哈希不匹配/未登记分别返回对应关联状态；上游未知不补当前值。
6. 三类 Prompt 列表筛选、分页、版本选择、复制、深层路由刷新、旧路径兼容；无权限 403、未配置 503；Prompt 中指令/HTML 作为文本显示，不执行。
7. Admin 测试/类型/构建与现有后端测试通过。静态 Registry 查询和 Diff 不需要任何外部模型调用；不用真实 LLM 重试证明只读功能。

本次已经完成的是源码审计、真实原件清点、只读 Trace 版本观察和两个静态 Diff 核对，**不是上述 API/UI 实现验收，也没有运行新的 LLM 或冒用旧测试成绩**。

## 十、请确认的最小兼容方案

建议确认以下四点后进入第二阶段：

1. 保留当前 Prompt 加载方式，Registry 作为独立的只读历史目录，首次由固定来源离线登记。
2. user_template 允许 null；真实 User 组装源码作为 user_assembly_ref 单独展示，历史无法核验的变量/Schema 保持 unknown。
3. 只登记已核验原件的版本；created_at 是登记时间；Git 缺失为 null；同版本标签冲突不覆盖。
4. 先关联已采集的 Report Trace；区分版本记录、请求点核验和未调用状态；不替旧 Run 或 Intent/Planner 补造当前版本。
