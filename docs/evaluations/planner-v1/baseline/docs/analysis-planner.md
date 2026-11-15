# Analysis Planner + Plan Validator V1

本阶段实现独立规划、能力目录和确定性校验，不替换现有 HITL 页面，不提供真实数据执行 / 报告接口。旧聊天中的 Plan、AnalysisTask、Mock Planner / Engine / Report 保持原演示行为。V1 计划没有通往旧 Mock Engine 的执行入口。现已另行实现 [Engine V1](analysis-engine.md) 和 [Report Module V1](report-module.md)；真实执行要求服务端 V1 批准快照，不复用 Mock 批准。

## 文件与依赖

```text
backend/app/
  domain/analysis_plan.py         V1 计划、任务、验证结果及覆盖状态
  planning/
    params.py                    六类操作的严格参数模型
    operations.py                小型确定性操作内核，不读取文件或调度任务
    capabilities.py              参数 Schema、类型规则、输出字段规则、内核引用
    validator.py                 字段 / 类型 / 能力 / 顺序 / 覆盖校验
    prompt.py                    业务价值、目标覆盖与输出约束
  services/analysis_planner.py    统一 Provider → 结构草案 → Validator
  nodes/planner_v1.py             供 Orchestrator 调用的统一节点契约
  api/plans.py                   独立生成 / 校验 / 能力查询
  main.py                        复用同一个 Provider，注册新服务和路由
backend/tests/
  planning_fixtures.py
  test_plan_validator.py
  test_planning_operations.py
  test_analysis_planner.py
  test_plan_api.py
backend/scripts/evaluate_planner.py  显式 --live 才运行的真实模型评测
```

依赖方向：API / Node → Planner Service → Registry / Validator → Domain。Registry 引用实际操作函数；Validator 只运行规则，不调用任何统计内核。没有新增依赖、独立 Agent Runtime、微服务或存储表。

## 与现有契约的映射

- IntentResult 对应现有 `ParsedIntent / IntentArtifact`，不重建意图模型。`clarify` 不允许规划；Artifact 的数据集引用必须与画像一致。
- DatasetProfile 仍使用 `fields`。Planner 接收稳定 `field_id`、显示名称、Physical / Logical Type、非缺失数、缺失率、唯一值数及有限质量标记。不发送样本值、整行数据或完整数据集。
- `dataset_version` 沿用画像的 64 位 SHA-256 字符串，不能改成任务书示意中的整数。
- 新的 `domain.analysis_plan.AnalysisTask / AnalysisPlan` 与旧 `domain.models.AnalysisTask / Plan` 分开；不将 V1 多步骤任务强行映射为旧销售分析枚举。
- 服务端生成 `plan_id`，独立生成每次为新草案 `plan_version=1`。该接口无状态，不保存 / 覆盖旧会话计划；未来接入 HITL 时再实现持久化修订版本。

## 计划与核心需求

业务草案至少包含一个任务，即使核心数据缺失也应保留说明缺口的 P0 任务。业务草案仅允许模型输出 `{"tasks":[...]}`。计划 ID、版本、数据集引用、核心需求列表、校验结果、需求缺口和覆盖状态由应用生成，模型不能提交 `executable` 或 `unmet_core_requirements`。

任务保留规格中的 task_id、title、business_question、priority、priority_reason、depends_on、steps，并增加：

- `requirement_ids`：关联应用给出的核心需求 ID。P0 必须关联，不能虚构。P1/P2 可为空。
- `missing_inputs`：必要数据缺失时记录明确描述。此时步骤可为空，Validator 必定返回 F0 / MISSING_FIELD；不需要编造字段 ID。正常任务为 []。

应用直接使用已解析的 business_goal 创建 C01；若有明确 decision_goal，另建 C02。没有决策目的时不自行添加。V1 不用第二次模型调用拆解“权威子目标”。原始结构化 Intent 保存在响应的 `intent_snapshot`，其中的未验证约束、defer / annotate 事项不会被默认为已解决。

priority_reason 要求说明“删除该任务后的具体影响”：核心目标所必需为 P0；明显提高分析质量为 P1；补充为 P2。简单城市计数只需一个任务，3–5 是常规建议，不是数量下限。Validator 不按名称或操作难易重写价值分级。

**覆盖是基于 Planner 提供的目标关联及 P0 必需任务进行确定性汇总，并非对自然语言目标充分性的数学证明。** 虚假的 P0 关联、业务问题遗漏、优先级合理性仍需真实模型与人工评测；结构通过不能证明业务规划优质。

## 能力目录

支持的六个操作都有实际函数和结果断言测试，不只是名称占位。它们已由独立 Engine V1 复用；规划模块本身不调度执行。参数模型见 `planning/params.py`，机器可读目录见 [capabilities.json](capabilities.json)。

| 操作 | 参数 | 输入要求 | 输出字段 |
| --- | --- | --- | --- |
| filter | conditions[{field,operator,value}] | AND；类型兼容的比较或空值判断 | 保留当前字段 |
| group_aggregate | dimensions, metrics | 唯一维度；指标符合聚合类型规则 | 仅维度与指标别名 |
| aggregate | metrics | 指标符合聚合类型规则 | 仅指标别名 |
| sort | field,direction | 当前可比较字段，asc / desc | 保留字段 |
| top_n | field,direction,n | 稳定排序后取前 n；1–1000 | 保留字段 |
| derive | function,field,alias | 仅 extract_year / extract_month，日期 / 日期时间 | 保留字段并新增整数别名 |

聚合：count / sum / avg / median / min / max / distinct_count。

- `count(field=null)` 为行数；指定字段为非缺失数，允许空列。distinct_count 排除缺失值。
- sum / avg / median / min / max 只接受逻辑数值列，不直接接受薪资区间、mixed 或空列。CSV 中已被 Profiler 全量识别为数值的列由内核严格转换，错误不能以丢弃或填零掩盖。
- 日期派生接受 Profiler 已识别的日期 / 日期时间，使用确定的 ISO / 原生日期解析；没有任意文本日期猜测或语义派生。
- 比较运算为 eq/ne/gt/gte/lt/lte/in/not_in/is_null/not_null。文本 / 布尔仅支持等值与成员比较；空值判断 value 必须为 null；空值不匹配普通比较。时间筛选值需合法 ISO 日期 / 日期时间。
- 缺失维度保留为独立分组；空结果的 count=0，数值聚合=null；稳定排序，缺失排末尾；top_n 不扩展同值边界。
- 原始 ID 与已使用别名都保留为不可重用名称，避免静默覆盖。

未知派生函数可在候选任务中记录“请求但未实现”的能力，例如 derive.function=extract_skills，Validator 必定 F0。这不加入 supported 列表，不执行、不解释为已验证能力。未知操作、自由 Python / SQL 不在模型允许的操作 Schema 中。

能力声明基于画像类型与内核约定。独立 Engine V1 会读取同一文件版本、验证实际运行时值与资源限制、验证审批并重新校验计划；V1 校验不是对源文件执行成功的保证，也不跳过 Intent 的后续待解决项。

## Validator 五层规则

1. Schema：必填字段、枚举、参数结构、唯一任务 ID、任务内唯一 step_id、唯一核心需求 ID；拒绝额外状态声明、非有限 JSON 数字、空操作链且无缺失数据说明。整体结构无效返回 422 / PLAN_SCHEMA_INVALID，不返回半个成功计划。
2. 字段引用：从真实画像 ID 初始化；中间别名必须来自先前步骤。引用不存在字段为 MISSING_FIELD，引用未来别名为 INVALID_OPERATION_ORDER，重新引用聚合后移除的字段为 INVALID_FIELD_REFERENCE。
3. 类型兼容：数值聚合、日期派生、筛选值均按确定性规则判断。不能对字符串薪资区间求均值。
4. 能力匹配：操作必须存在且有实现，参数需通过对应 Schema；未实现派生函数为 UNSUPPORTED_OPERATION。
5. 顺序 / 依赖：每个任务独立从原始字段开始，按步骤追踪输出字段和类型。depends_on 非空返回 UNSUPPORTED_DEPENDENCY，即使引用的任务真实存在也不允许执行。

任务检查采取首次阻断即返回，因此 validation_issues 表示首个确定阻断原因，不声称穷尽所有错误。任务仍完整保留在 plan.tasks。

- F2 / READY：当前操作链不需要前置派生。
- F1 / REQUIRES_TRANSFORMATION：显式、受支持的派生确实影响后续操作或最终输出；转换步骤本身也已校验。被丢弃且不影响结果的无关派生不产生 F1；基于派生值筛选后再计数仍为 F1。
- F0：字段 / 数据 / 参数 / 类型 / 操作 / 顺序 / 跨任务依赖有阻断；executable=false。

返回 `ValidatedAnalysisPlan` 包含：原始 `plan`、逐任务 `validation_results`、`unmet_core_requirements`、coverage_status、executable_task_ids、blocked_task_ids、fully_executable、Registry / Validator 版本、来源、可选 LLM 元数据与意图快照。`approval_required=true` 始终成立；F1/F2 是执行资格，不是审批凭证。

## P0/F0 与覆盖

- 每个核心需求关联的 P0 都视为必需，不将它们擅自解释为可互相替代。
- 所有 P0/F0 保留并进入需求缺口，包含错误 / 缺失目标关联的 P0；不能静默删除。
- 核心需求没有对应 P0 时记 CORE_NOT_COVERED。
- 所有核心需求已由可执行 P0 覆盖，且无必需 P0 阻断：complete。
- 有可执行 P0 提供部分核心答案，但仍有核心缺口：partial。
- 没有任何可执行核心 P0：blocked。即使存在可执行 P1/P2，也不能把补充输出冒充核心答案。
- 可选 P1/P2 的 F0 不自动降低核心覆盖，但会令 fully_executable=false。

尚未完成 V1 HITL 接线，所以规划接口只返回这些元数据，不自动执行或向用户展示新的审批页面。

## API

已有画像和完整 IntentArtifact 时，向 `POST /api/v1/plans/generate` 提交 `{"intent": 完整解析结果对象}` 即可自动读取数据集引用。若仅传 ParsedIntent 的六个业务字段，另需 dataset_ref。例如：

```json
{
  "dataset_ref": {"dataset_id":"替换为画像中的ID", "dataset_version":"替换为画像中的64位版本哈希"},
  "intent": {
    "analysis_mode":"goal_driven",
    "next_action":"proceed",
    "analysis_goal":{"analysis_object":"销售记录","business_goal":"比较各地区销售额","decision_goal":null},
    "constraints":{"time_range":null,"filters":[],"metric_requirements":[],"analysis_limits":[]},
    "uncertainties":[],
    "clarification_questions":[]
  }
}
```

完整 Artifact 的数据集引用若与另传的 dataset_ref 不一致则拒绝。`GET /api/v1/capabilities` 可读取能力目录。`POST /api/v1/plans/validate` 的请求体是 `{"dataset_ref": 引用对象, "plan": generate响应中的plan对象}`。

独立 validate 按版本读取画像、不调用模型；提交未知字段 / 未支持操作会保留任务并返回 F0。整体 Schema 错误为 422。生成服务没有暴露“跳过 Validator”或“直接执行”开关。

使用 Python 串接现有接口的完整示例（后端运行于本地，模型已配置）：

```python
import httpx
with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=75) as client:
    with open("examples/sales.csv", "rb") as file:
        response = client.post("/datasets", files={"file": ("sales.csv", file, "text/csv")})
    response.raise_for_status()
    profile = response.json()
    ref = {key: profile[key] for key in ("dataset_id", "dataset_version")}
    response = client.post("/intents/parse", json={"dataset_ref": ref, "user_query": "比较各地区销售额"})
    response.raise_for_status()
    intent = response.json()
    if intent["next_action"] == "clarify":
        print(intent["clarification_questions"])
    else:
        response = client.post("/plans/generate", json={"intent": intent})
        response.raise_for_status()
        validated = response.json()
        print(validated["coverage_status"], validated["validation_results"])
        # 独立重验：不调用模型
        response = client.post("/plans/validate", json={"dataset_ref": ref, "plan": validated["plan"]})
        response.raise_for_status()
```

错误使用现有 error 契约。缺少模型配置为 LLM_NOT_CONFIGURED；意图待澄清为 INTENT_CLARIFICATION_REQUIRED；版本冲突为 INTENT_DATASET_MISMATCH；整体无效计划为 PLAN_SCHEMA_INVALID；两次非法草案为 PLANNER_INVALID_OUTPUT；其余上游超时、认证、连接、拒绝错误沿用 Provider 错误码。

## LLM 与重试

复用现有环境变量、LLMProvider 和严格 JSON Schema HTTP 适配器。模型看到每项操作的参数 Schema 与类型 / 输出规则；独立 system message 隔离数据中的指令。

只对结构 / 参数无效、响应截断最多重试一次（最多两次调用）；不重试认证、限流、网络失败或超时，不回退 Mock。纠错提示不回显原始非法内容。合法 F0 只交 Validator 保留，不进行模型“可行性修复”。不默认指定模型，不宣称跨模型确定性。

## 测试与质量评估

从 backend 运行：

```bash
../.venv/bin/python -m pytest -q
```

专项测试覆盖任务书 13 项用例，以及 ID / 别名冲突、字段移除、不同核心需求覆盖、无 P0、空任务集、空列计数、空结果、布尔 / 日期筛选、重复输出一致性、JSON 重试边界、意图澄清阻断、版本绑定和端到端画像 → 意图 → 规划 → 校验。招聘与销售数据都是合成测试数据；各统计操作有真实数值结果断言，没有用模型数值做计算依据。

普通测试显式注入受控 Provider 或 httpx.MockTransport。**它们能验证业务契约、校验确定性和受控响应的分级保留，不能证明真实模型的业务价值判断或规划质量。**

配置真实模型后可显式运行（会向所配置服务发送合成元数据并产生模型调用）：

```bash
../.venv/bin/python scripts/evaluate_planner.py --live --repeats 3
```

包含城市计数、薪资区间无法求均值、JD 技能未支持、地区销售额、按年汇总销售额。检查覆盖状态、核心任务、简单问题任务数、时间派生，并比较重复运行的优先级和操作链。输出 `var/planner-evaluation.json` 供审阅；退出非零表示错误 / 不稳定 / 未达预期，必须查看具体业务问题和“删除影响”理由，不能只看通过数。

真实语义评测不能被受控结果替代。运行环境若没有配置模型，应明确记录未完成真实模型质量验证；不伪造语义通过结论。后续接入 HITL / Engine 前还需验证多任务核心目标的拆解充分性、约束落实和未解决不确定性。
