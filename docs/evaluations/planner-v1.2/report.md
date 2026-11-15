# Analysis Planner V1：独立真实LLM交付

已复用现有Planner、Provider、计划契约、Registry和Validator完成独立服务补强。当前Prompt **planner-v1.2**，模型 **qwen3.8-flash**，保持单LLM Planner；未接线完整Workflow，未执行统计，未改HITL、Engine、Report业务规则。

**工程实现及真实评测已完成；用户已逐例确认32例、34项P0任务的范围及优先级。** 本次确认不更改自动评分、完整操作链稳定性或HITL批准状态，不扩大为通用语义可靠性保证。 原轮次、自动评分和实际输出全部保留。评分规则未根据第二轮结果放宽。

## 1. 真实评测结果

|评测|有效计划Schema|完整参考检查|显式约束检查|
|---|---|---|---|
|首轮planner-v1.1，原25例|24/24|19/25（76.00%）|68/71（95.77%）|
|当前原25例回归|24/24|24/25（96.00%）|70/71（98.59%）|
|当前独立未见8例|8/8|8/8（100%）|33/33（100%）|
|当前主评测合计33请求|32/32|32/33（96.97%）|103/104（99.04%）|

33个主请求包含1个clarify拒绝，未调用模型，计作正确门禁，不能把它当成第33个有效计划。另有5例各3次重复（15次），有效计划15/15、参考检查15/15。首轮与当前回归共用同一输入和评分器；独立8例在第二版Prompt冻结后首次调用，未用于本轮调优。

最终候选共48次服务请求、47次实际Provider调用；两轮累计86次真实调用，均未触发重试、无HTTP/超时失败、无Mock。32个主计划共有37项任务，技术资格F2=28、F1=2、F0=7。F0全部保留且不可执行。

约束百分比是冻结参考检查通过数/检查总数，包含字段、函数、分组、筛选、年份、Top N、禁止项及范围检查，不是通用自然语言语义准确率。无输出请求另计失败和不可评估；本轮没有这类未返回。不能用103/104掩盖下面的争议和未审阅项。

## 2. 剩余问题与语义复核

- **C06自动失败保留**：原请求未指定均值还是中位数，且有defer。首轮把两者都认定必需P0，属于不合理扩张；新版保留P0待确认口径、没有计算链，Validator=F0/blocked。冻结参考预期complete且应有类别分组步骤，因此仍报3项失败（覆盖、执行资格、维度），约束检查失1分。这个差异单列解释，未修改标签或自动分数。保守处理避免擅自选择口径，但现有HITL不支持在本轮自动解决该条件。
- **C04措辞风险**：操作链只有工单数量，确实没有响应分钟或人员排名；但问题/删除理由在部分运行中把“不要求计算响应分钟”表述为“不计算/明确排除”的限制。原句同时含“只统计数量”，需人工判断是合理描述本方案范围还是把非必选误称禁令。不能仅凭步骤正确宣称所有解释性文字可靠。实际文本已保留在审阅表。
- **探索式P0边界**：S03地区/品类、C02分布/整体响应统计各自P0是否真的都不可删除，需要业务判断。自动检查不证明删除测试成立。
- **可读性**：S01业务问题出现内部field_id；部分理由泛称支持决策，即使没有明确decision_goal。没有新增决策任务，但应进一步收紧用户可读文案与无依据决策措辞。
- **稳定性**：默认是否增加sort存在波动；不影响核心聚合指标，但操作链非完全稳定。
- **错误码粒度**：现有Validator把missing_inputs（缺字段、缺能力、待确认口径）统一判MISSING_FIELD。任务正文仍明确实际缺口，本轮未新增下游原因枚举或改契约。

代理已逐条复查32个主计划及重复输出，见[semantic-review.json](semantic-review.json)。代理复查不等于用户人工签字。P0共34项，用户已按32例逐例确认范围与优先级，确认原话为“已逐例复核，P0 范围及优先级均认可”。[确认记录](human-signoff.json)绑定原始材料及模型结果哈希；此前提示和自动分数保留。[人工审阅表](p0-human-review.md)、[状态记录](p0-human-review.json)。

## 3. 业务价值与操作链验证

- 单一城市计数、地区销售额、项目工时均只生成一个必要任务，没有为凑3–5个任务增加薪资/学历/技能等分析。
- S04真实输出按2026年半开日期区间、华东、已完成、排除硬件筛选，再地区sum(销售额)、排序、Top3；每个字段ID来自真实Profiler元数据，别名先生成再引用。完整原输出见[example-sales-plan.json](example-sales-plan.json)。
- C03按年份、VIP与已解决布尔值筛选后，按类别avg响应分钟、升序Top2。日期可用确定性派生或合法区间；当前回归为区间，技术F2；P03和U08的真实日期派生为F1。
- 利润率、薪资区间均值、JD技能、缺失满意度、无基准的今年等核心任务保留P0及缺口，未用可执行计数替代。
- 未见8例覆盖排除、时间、禁止、非排除、非必选、多指标与月派生，均通过参考检查；这8条规模很小，不足以外推真实业务总体质量。

## 4. 重复稳定性

规范化生成ID/别名，保留字段、函数、参数、顺序与优先级比较；不因措辞变化误判操作变化。

|案例|次数|任务数量一致|优先级多重集一致|完整操作链一致|
|---|---|---|---|---|
|S01|3|是|是|否|
|R01|3|是|是|否|
|C04|3|是|是|否|
|P02|3|是|是|否|
|P03|3|是|是|是|

任务数和P0分级5/5组稳定，但完整操作链仅1/5组稳定：S01/R01/C04/P02差异是是否附加sort；P03均为derive→group_aggregate。技术覆盖关联也需单独查看，首轮P03即使操作相同仍因需求ID遗漏导致partial。当前重复15次均未出现这种遗漏，不宣称永远不会发生。

## 5. 接口、Schema与复用

实现位置：backend/app/services/analysis_planner.py，方法await AnalysisPlannerService(provider, registry, timeout_seconds, max_attempts=2, enable_thinking=False).plan(intent, profile)。

HTTP沿用POST /api/v1/plans/generate：传完整IntentArtifact可自动取dataset_ref；仅传ParsedIntent六个业务字段时，另传已保存画像的dataset_ref。GET /api/v1/capabilities及POST /api/v1/plans/validate不变。API从Repository按版本取画像，不接受本地路径。clarify或Artifact版本不匹配在模型调用前拒绝。

|契约|复用方式/本轮变化|
|---|---|
|DatasetProfile|fields[].field_id/display_name/physical_type/logical_type及质量摘要；没有semantic_tags，不编造。版本是既有SHA256字符串。|
|IntentResult|ParsedIntent/IntentArtifact不变；defer/annotate完整保存在intent_snapshot。|
|PlannerDraft|LLM只输出tasks，严格拒绝F2/coverage/plan_id等额外声明。|
|AnalysisTask|既有task_id/title/business_question/priority/priority_reason/requirement_ids/depends_on/missing_inputs/steps全部复用。|
|AnalysisPlan|服务端生成ID/版本及core_requirements；C01业务目标，后续明确决策及四类原话约束登记，不新增字段。|
|ValidatedAnalysisPlan|原plan+逐任务F0/F1/F2+unmet+覆盖+审批要求+来源+intent_snapshot；Validator原样复用。|

领域Schema SHA256与首轮一致，见comparison和integrity-check。模型传输Schema仅将非空\S规范成等价的完整匹配表达式，以兼容Qwen结构化解码；领域Schema、Registry、HITL、Engine、Report均不修改。[实际模型输出Schema](provider-output.schema.json)。

核心约束登记不等于已验证映射：requirement_ids来自模型，代码不会补齐关联或改写操作链。技术complete无法证明自然语言目标充分性；原constraints依旧unverified，不会自动批准，也不绕过HITL/Engine的待解决事项检查。

## 6. Prompt、配置与错误

完整当前Prompt见[prompt.txt](prompt.txt)，版本planner-v1.2。首轮版本与所有实际结果仍在[首轮归档](../planner-v1/live.json)。评分器planner-reference-v1在首轮真实调用前冻结，第二轮未更改。四状态只为内部语义指导，没有新增输出字段或后处理伪造结果。

复用已有OpenAI-compatible Provider、模型地址、API Key管理：qwen3.8-flash；Planner enable_thinking=false；总超时30秒；最多2次尝试（范围1–3）；temperature/top_p/max_tokens省略，使用服务商默认。没有新增SDK、Agent或基础设施。

```bash
export INSIGHTFLOW_PLANNER_ENABLE_THINKING=false
export INSIGHTFLOW_PLANNER_MAX_ATTEMPTS=2
# 模型地址、模型名、API Key沿用本地安全环境；不要写进源码或报告。
```

应用与评测脚本不自动读取.env。当前评测安全加载已有本地配置，并只在本次进程设置Planner参数，没有修改或输出Key。现有Prompt及完整实际模型正文均已归档；评测记录对配置Key脱敏，生产日志仅记parse_id/版本/尝试/错误，不记正文或Key。

|错误/结果|行为|
|---|---|
|LLM_NOT_CONFIGURED/LLM_HTTP_ERROR/LLM_UNAVAILABLE/LLM_TIMEOUT/LLM_RATE_LIMITED等|明确调用失败，安全转译错误正文，不Mock。认证/网络/限流/超时不格式重试。|
|PLANNER_INVALID_JSON|语法、重复键、非JSON值或Unicode问题；有限重试。|
|PLANNER_SCHEMA_INVALID / PLANNER_OUTPUT_TOO_LARGE|字段/枚举/操作参数/唯一ID/大小错误；有限重试。|
|PLANNER_BUSINESS_INVALID|没有任何P0核心任务，明确业务错误，不启动修复循环。|
|合法草案的Validator F0|保留原任务、原因及unmet；不调用LLM修复，不删除任务冒充完整覆盖。|

错误外层仍是现有error契约，JSON/Schema/调用阶段有stage/attempts/parse_id/Prompt版本；原PLANNER_INVALID_OUTPUT统一码拆细，调用方应适配。所有尝试共享总超时，不倍增。

## 7. 自动化测试与实际文件

最新完整后端：**511 passed，1项既有Starlette TestClient httpx弃用提示**。新增17项覆盖总超时共享与取消、JSON/Schema/业务错误、重复ID、Provider错误脱敏、禁止额外指标、Schema等价兼容、约束/不确定性保留、稳定性归一化与四主题标签。原API上传→画像→受控Provider→Planner→Validator集成测试通过。受控测试不计作真实模型语义成绩。

修改：services/analysis_planner.py、planning/prompt.py、core/config.py、main.py（仅Planner配置注入）、.env.example、scripts/evaluate_planner.py、tests/test_analysis_planner.py（错误码断言适配）、README.md、docs/analysis-planner.md。

新增：planning/context.py、planning/output.py、planning/evaluation.py、evaluation/planner_cases_v1.json、planner_unseen_v1.json、tests/test_planner_v1_live_contract.py及本目录/首轮归档。没有新增依赖、数据库表、第二套执行器或领域模型。

冻结清单20项字节校验通过，83个保护模块哈希未变（含Intent、领域Schema、Registry、Validator、Engine、HITL、Report等），见[integrity-check.json](integrity-check.json)。前端未修改，未重新运行前端构建。

复现：先安全加载本地模型环境，再使用全新输出路径；拒绝覆盖历史文件。

```bash
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/evaluate_planner.py --live --cases evaluation/planner_cases_v1.json --output ../docs/evaluations/planner-v1.2/regression-rerun-NEW.json --repeats 3
../.venv/bin/python scripts/evaluate_planner.py --live --cases evaluation/planner_unseen_v1.json --output ../docs/evaluations/planner-v1.2/unseen-rerun-NEW.json
```

接口调用和画像字段映射见[Planner文档](../../analysis-planner.md)。重跑已用样本属于回归，不能重新称作独立未见测试。

## 8. 下一轮建议

P0逐例范围与优先级审阅已完成。后续可重点改善C04非必选措辞和C06待确认口径的表达与参考评分差异，再决定是否调整独立Planner。可在同一Prompt中约束无必要排序和用户文案中的内部ID，提高稳定性与可读性；若要修改评分规则，应另立版本、先冻结、再重评历史和全新样本。业务约束的结构化映射审计若需要新增契约，应另行提出最小兼容方案，本轮不擅改Validator/HITL/Engine。本次确认不自动启动完整Workflow接线；是否接线仍依照后续明确任务处理。

全部自动Bad Case（含首轮及重复运行）见[all-phases-bad-cases.json](all-phases-bad-cases.json)；代理额外发现的文字与优先级问题单列semantic-review，不用自动全绿掩盖。
