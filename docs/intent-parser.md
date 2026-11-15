# Intent Parser V1

独立理解用户想分析什么，输出结构化 IntentResult。本次是在已有实现上补齐上下文、有限重试、分阶段错误、日志和质量评测；没有新建第二套 Provider 或画像模型，没有开发 Planner、HITL AI 修订、统计操作或报告洞察。

**当前Prompt为 intent-v1.3.3，模型保持 qwen3.8-flash，IntentResult Schema 与单LLM节点不变。** 本轮优化四状态否定语义、最小完整约束、范围保留和输入主题不匹配时的澄清。确定性grounding仍拒绝虚构或非连续约束；没有关键词后处理补齐结果。实际评测、全部中间失败、独立样本与残留问题见 [V1.3交付报告](evaluations/intent-v1.3.3/report.md)。

用户已确认N07/N10/N11的参考语义及首轮实际返回，未将此扩大为全量Gold或最终候选全部输出已人工确认。评分协议在模型调用前冻结，原v1.1/v1.2输出及原始分数保留，按新规则重评另存。不能仅凭单项95%宣称完整语义验收。

## 开发前检查

| 项目 | 已有实现与本次处理 |
| --- | --- |
| LLM 基础设施 | `LLMProvider.generate(LLMRequest)`、CompatibleLLMProvider、配置与 API Key 管理、严格 JSON Schema、HTTP 超时、未配置错误均已存在。继续复用，不引入模型 SDK 或 Agent Runtime。 |
| DatasetProfile | 已有真实画像、不可变数据版本、fields[].field_id / display_name / physical_type / logical_type / samples。自动读取，用户不手工录入字段。 |
| Intent Parser | 已有服务、独立 API、Prompt、Schema、空输入守卫、原话依据校验、旧聊天澄清暂停/恢复。缺少有限重试、分阶段错误、四类业务质量评测与实际记录。 |
| 下游依赖 | HITL / Engine 使用不确定性 id；历史记录以 description / impact 保存。新增 issue / reason 的对外名称，保留内部规范存储及旧格式读取。 |

## 文件改动

修改：

- `backend/app/domain/intent.py`：复用 ParsedIntent，公开别名 IntentResult；不确定性字段兼容、nullable 目标规则、澄清问题上限、调用追踪元数据。
- `backend/app/intent/context.py`：补充 row_count 与 physical_type，保留实际 LogicalType 枚举及稳定字段 ID。
- `backend/app/intent/prompt.py`：独立 Prompt 与 PROMPT_VERSION，明确模式、目标、全部约束、否定决策、defer 及指令隔离规则。
- `backend/app/services/intent_parser.py`：有上限的输出重试、总超时、数据大小控制、安全日志、原始输入保留。
- `backend/app/core/config.py`、`main.py`、`backend/.env.example`：接入最大尝试次数配置。
- `backend/scripts/evaluate_intent.py`：固定评测集、逐项记录、指标分母、失败案例、模型缺配置记录。
- `backend/tests/test_intent_parser.py`、`test_intent_api.py`：适配新错误分类及扩展上下文。
- `frontend/src/types/contracts.ts`、`components/PlanReviewCard.tsx`：仅兼容新旧不确定性字段名称；审批逻辑不变。
- `frontend/src/tests/hitl-v1.test.tsx`：验证两种名称仍展示相同限制、保留相同 warning ID。
- README 和共享 JSON Schema：与当前接口保持一致。

新增：

- `backend/app/intent/validation.py`：严格 JSON、Schema、流程一致性与原话依据校验。
- `backend/app/intent/evaluation.py`：确定性评分、指标分母、目标比较；不调用裁判模型。
- `backend/evaluation/intent_cases.json`：40 条固定请求，覆盖四类业务及注入元数据变体。
- `backend/tests/test_intent_v1.py`：重试、错误分类、时间和大小限制、隐私、兼容及评分边界。
- `docs/intent-evaluation.md`、`intent-live-evaluation.json`，以及上下文、请求和完整响应的机器 Schema。

## 上下文映射与输入限制

外部 API 接收 user_query、dataset_ref 和可选 clarification_answers。服务端从保存的 DatasetProfile 按版本构建上下文，不接收外部 dataset_context。

| DatasetProfile 实际字段 | 模型上下文 |
| --- | --- |
| file_name | dataset_name |
| row_count | row_count |
| fields[].field_id | columns[].field_id |
| fields[].display_name | columns[].name |
| fields[].physical_type | columns[].physical_type |
| fields[].logical_type | columns[].logical_type |

实际 LogicalType 为 `empty / boolean / integer / number / date / datetime / time / text / mixed`，不改为示例中的 categorical 或 numeric。画像没有 semantic_tags，本阶段不编造语义标签。

sample_rows 固定为空。各列 samples 是分别去重的独立样本，不能拼成真实行。不会发送列样本、完整行、完整数据文件或 API Key；只传字段元数据和真实行数。字段名、文件名和用户输入以 JSON 数据发送，与独立 system_prompt 分离。数据中的“忽略系统规则”等文字没有工具执行入口；结构校验也会拒绝额外任务或代码字段。此设计降低注入面，不宣称对任何模型的所有注入实现绝对防护。

限制：

- 原始需求最多 2000 字符；最多 10 次澄清答复，每次最多 2000 字符，总文本最多 8000 字符。
- 字段上下文最多 64 KiB；发送的完整用户消息最多 96 KiB（不含固定系统提示与固定 Schema）；模型意图文本最多 64 KiB。
- 相对时间保留原话，不自动换算年份；无效 Unicode、重复 JSON 键、NaN/Infinity、额外字段均拒绝。

完整上下文见 [intent-context.schema.json](intent-context.schema.json)。

## IntentResult 与后置校验

`IntentResult` 是现有 `ParsedIntent` 的公开业务别名，没有另建不兼容模型。六个必填业务字段为：analysis_mode、next_action、analysis_goal、constraints、uncertainties、clarification_questions。

- goal_driven：有明确业务问题；exploratory：有可理解上下文下的开放探索；undetermined：无法确定分析意图，必须澄清。
- 三个目标字段都允许 null，不为了填满对象编造分析对象或决策目的。proceed 必须有 business_goal；clarify 可保留未知目标为 null。
- decision_goal 只有明确依据才能填写。本次采取保守策略：非空决策目的必须逐字摘录用户需求或某次澄清答复，不能来自字段、文件名或模型自行推测。
- 每项约束为 `{"raw_text":"用户原话片段","validation_status":"unverified"}`，覆盖 time_range、filters、metric_requirements、analysis_limits。没有匹配字段也不丢弃原话，不标成可执行条件。
- 每项不确定性对外为 `id / issue / reason / action / resolve_at`。id 保留给 HITL 与 Engine 追踪；内部描述对应旧 description，原因对应旧 impact。接受旧名称，拒绝新旧名称同时出现造成歧义。默认内部 model_dump / SQLite 仍用旧规范名称，HTTP 与 `model_dump(by_alias=True)` 用新名称；不会重写不可变审核记录。
- clarify 只能 resolve_at=before_planning，并强制 next_action=clarify；defer 只能在 plan_approval / before_execution 解决；annotate 不阻断。
- clarify 必须有阻断事项及问题；proceed 的问题必须为空。问题唯一，最多 3 个，Prompt 优先只问最关键的一项。

校验顺序：严格 JSON → 字段、枚举、null 与 constraints Schema → action/阶段及流程一致性 → 约束与决策的原话依据。结构错误和模型失败返回明确错误，不伪造有效意图；有效输出表达语义不确定时返回 clarify。原话校验只能证明可追溯，不能自动证明业务解释正确、约束无遗漏或否定语义被正确理解；这些仍需真实模型评测和人工复核。

业务 Schema：[intent-output.schema.json](intent-output.schema.json)。完整响应：[intent-artifact.schema.json](intent-artifact.schema.json)。

## 独立 API 与调用示例

先上传取得画像引用，再调用解析。以下示例使用项目真实 sales.csv，只有第二个请求调用已配置模型：

```bash
cd backend
../.venv/bin/python - <<'PY'
import json
from pathlib import Path
import httpx
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=40) as client:
    with Path("../examples/sales.csv").open("rb") as source:
        upload = client.post("/api/v1/datasets", files={"file": ("sales.csv", source, "text/csv")})
    upload.raise_for_status()
    profile = upload.json()
    response = client.post("/api/v1/intents/parse", json={
        "user_query": "比较各地区销售额，找出销售额最高的三个地区。",
        "dataset_ref": {key: profile[key] for key in ("dataset_id", "dataset_version")}
    })
    print(response.status_code)
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
PY
```

接口为 `POST /api/v1/intents/parse`，请求 Schema 见 [intent-request.schema.json](intent-request.schema.json)。clarification_answers 可选，使用原始答复列表重新解析。空输入不调用模型，明确返回 input_guard 澄清；没有配置模型时，非空需求返回 503 LLM_NOT_CONFIGURED，不返回示例成功数据。

内部调用：`await IntentParserService(provider).parse(user_query, dataset_profile, clarification_answers)`。原有 IntentParserNode 继续复用该服务。输出保留 user_query、答复、dataset_ref、LLM 来源、parser_version、prompt_version、llm_attempts、parse_id。原文不被规范化的 business_goal 覆盖。

此独立调用不创建分析任务、批准、执行或报告。已有旧聊天在 clarify 时仍暂停并保留历史；新的真实 HITL 人工导入流程本次不改线。后续接入时需保留原始 user_query 与规范化业务目标的区别，并逐项落实未经验证约束和 defer 事项，不能因为 Parser 返回 proceed 就认为已批准或可执行。

## Prompt、重试、超时与日志

业务 Schema 由 Python 模型生成，Prompt 独立放在 intent/prompt.py，当前版本为 intent-v1.3.3。机器 Schema 导出到 docs，避免维护第二份人工定义。

复用现有环境变量：

```bash
export INSIGHTFLOW_LLM_BASE_URL="https://your-provider.example/v1"
export INSIGHTFLOW_LLM_MODEL="your-model"
# 通过本地安全环境设置 INSIGHTFLOW_LLM_API_KEY，不要放进源码、评测集或日志。
export INSIGHTFLOW_LLM_TIMEOUT_SECONDS="30"
export INSIGHTFLOW_INTENT_MAX_ATTEMPTS="2"
# 可选，仅 Intent：当前 Qwen 实测配置为 false；其他接口留空以省略扩展参数。
export INSIGHTFLOW_INTENT_ENABLE_THINKING="false"
```

地址附加 /chat/completions，服务需支持 strict JSON Schema；不静默降级到 JSON mode 或 Mock。.env.example 是说明，应用和评测脚本不自动加载 .env，应在启动它们的终端导出配置。timeout 在 (0,300] 秒，max_attempts 为 1–3（默认 2，即最多重试一次）。

`INSIGHTFLOW_INTENT_ENABLE_THINKING` 留空时不发送供应商扩展参数；false / true（或 0 / 1）时仅 Intent 请求显式携带 `enable_thinking`。本次默认思考模式诊断约 50 秒，超出 30 秒总超时，因此当前本地 Qwen 配置为 false，严格 Schema 保留。参见 [阿里云参数说明](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)。修改配置后需重新加载环境并重启后端。

Intent 文本非空正则由 `\S` 改为 `[\s\S]*\S[\s\S]*`，保持“至少一个非空白字符”的含义，同时兼容按完整匹配处理正则的结构化解码器。实测该端点在旧规则下将目标和约束压缩为单字，修改后得到完整文本。单元测试同时覆盖多字符、多行及全空白；诊断结果见 [兼容性对照](intent-pattern-compatibility-check.json)。

格式、Schema、流程或原话依据错误，以及不完整输出，可按同一输入重新请求；只发送安全的错误类别、阶段及已知字段路径，不回传错误的模型正文。grounding错误额外提示摘录连续原话、避免拼接及不得补造未知筛选值；不修改模型返回。认证、连接、拒绝、限流等调用错误不作为格式重试。所有尝试共用一次总超时，不按次数倍增；超时取消当前调用。

日志沿用 Python logging 的 app.intent logger，记录 parse_id、Prompt 版本、尝试数、阶段及错误代码，不记录 API Key、用户全文、数据行或模型原文。Schema 错误的字段路径也会清理未知键名，不回显原始值。

## 错误分类

统一响应仍为 `{"error":{"code":...,"message":...,"details":...}}`。模型失败的 details 包含 stage、attempts、parse_id；Schema/规则错误可有清理后的字段路径。

| 错误码 | 阶段 / HTTP | 含义 |
| --- | --- | --- |
| DATASET_CONTEXT_REQUIRED / DATASET_CONTEXT_TOO_LARGE | 输入 / 422 | 画像缺失或元数据超限 |
| INTENT_INPUT_INVALID / INTENT_INPUT_TOO_LONG / INTENT_REQUEST_TOO_LARGE | 输入 / 422 | 文本类型、长度或请求体不合规 |
| LLM_NOT_CONFIGURED | call / 503 | 缺少模型配置 |
| LLM_TIMEOUT | call / 504 | 超过所有尝试共用的总时间限制 |
| LLM_UNAVAILABLE / LLM_CALL_FAILED / LLM_HTTP_ERROR | call / 502 | 连接、调用或 HTTP 失败 |
| LLM_RATE_LIMITED | call / 503 | 上游限流 |
| LLM_REFUSED / LLM_INCOMPLETE_OUTPUT / LLM_INVALID_OUTPUT | call / 502 | 既有 Provider 的拒绝、不完整或协议错误 |
| LLM_INVALID_JSON | json / 502 | JSON 语法、重复键、非 JSON 常量或 Unicode 错误 |
| INTENT_SCHEMA_INVALID / INTENT_OUTPUT_TOO_LARGE | schema / 502 | 字段、类型、枚举、结构或输出大小不合规 |
| INTENT_SEMANTIC_INVALID | semantic / 502 | action/resolve_at 或澄清流程不一致 |
| LLM_UNGROUNDED_OUTPUT | semantic / 502 | 约束或决策无法追溯到用户原话 |

旧调用方若按 LLM_INVALID_OUTPUT 统一处理全部意图输出错误，应适配新的 json/schema/semantic 分类。Provider 的协议错误码保持不变。

## 测试与实际验证结果

```bash
cd backend
../.venv/bin/python -m pytest -q
```

当前后端 494 项测试通过，包含四状态、最小约束、历史重评分、调用记录脱敏、独立样本与归档完整性检查；之前的思考参数与正则兼容回归保留。前次前端 24 项测试及生产构建通过，本轮未修改前端。覆盖四类实际 Profiler 上下文、隐私、注入数据隔离、有限重试、总超时、错误分类、非法 JSON、nullable 字段、Schema 与流程冲突、原话约束、新旧字段兼容、大小限制、调用追踪和评分分母。

单元测试使用显式受控响应或 HTTP MockTransport；它们证明代码契约，不证明模型理解正确率。HITL / Engine / Report 的既有回归全部保留。真实质量评测用独立脚本及固定数据集，见 [评测说明](intent-evaluation.md)。
