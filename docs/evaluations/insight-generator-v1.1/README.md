# Insight Generator V1.1 第二阶段实施与真实评测

日期：2026-10-28。**工程改造和评测完成；业务质量验收建议不通过。** 多证据生成链路已打通，但生成可用率退化，不能将证据利用提升等同于整体质量达标。没有更换 qwen3.8-flash、增加模型节点或修复循环；Planner、Validator、HITL、Engine、主 Workflow 业务代码未修改。

## 1. 冻结基线和实施顺序

先保存 [原实现快照](baseline-source)、[冻结输入](frozen-inputs.json)、[A–G 评分规则](frozen-rubric.json)、[冻结哈希](freeze-manifest.json)，然后才运行基线和修改生产逻辑。12 条回归 + 4 条独立未见，共 16 条，覆盖销售、招聘、客服、项目运营、单/多任务、Top N、时间变化、并列、负值、缺失和无法支持的利润解释。

冻结时 S03 的测试夹具把 count 结果置空，违反既有计数契约，首轮同时遭遇网络限制。两项失败都保留，没有覆盖旧文件。**在首次成功模型访问及生产修改前**，将 S03 修正为真实筛选后的数值均缺失均值场景，另存 [frozen-inputs-v2.json](frozen-inputs-v2.json) 和 [修正依据](fixture-correction.json)。评分规则没有变化。正式新旧对照都使用 v2，输入 SHA 均为：

`76ca457f269ba7e7b698c9c99ee084885c5bb045696c92bc1567e9931c8f5326`

S01 来自此前保存的真实用户销售文件、真实 Engine 执行与批准快照；其他案例为固定合成 CSV，通过实际 Profiler、Validator、受控 Pandas 内核生成结果，明确标记 imported，不冒充新用户审批或真实招聘市场数据。报告阶段全部调用真实模型，未使用 Mock 补齐。

最终 Report 代码在第一次优化版 holdout 调用前锁定：[candidate-lock.json](candidate-lock.json)。之后没有据 holdout 输出调整 Prompt、生成代码、校验规则或评分规则。末尾前端补充“候选拒绝原因/历史展示版本”的折叠技术详情，不改变生成结果或本次语义分数；交付文件哈希另存 delivery-manifest.json。

## 2. 实际修改文件

| 文件（相对项目根目录） | 内容 |
| --- | --- |
| backend/app/reporting/comparisons.py（新增） | 有界、确定性的相对差额、首尾比例、返回组内集中度 |
| backend/app/reporting/evidence.py | 接入比较证据；改进整数/Decimal 格式及可加合计的整数保真 |
| backend/app/reporting/selection.py（新增） | 比较/变化优先，按指标和任务轮转控制预算 |
| backend/app/reporting/prompt.py | 版本 1.1.6，多证据选择、具体建议与表达边界 |
| backend/app/reporting/fact_validation.py | 多证据事实表达、口径/对象/派生值核验、去重和候选级拒绝 |
| backend/app/services/analysis_report.py | 有界目标/约束/范围/缺失上下文，统一保存洞察、比较 KPI、生成版本和拒绝记录 |
| backend/app/reporting/presentation.py | 新报告只映射已保存洞察；历史报告走原逻辑 |
| backend/app/domain/report_presentation.py | 展示版本兼容新增 business-report-v1.1 |
| frontend/src/types/report.ts | 展示版本、生成版本和拒绝记录的类型 |
| frontend/src/reporting/ReportPage.tsx | 在折叠详情中显示拒绝原因和历史展示版本 |
| backend/tests/test_insight_composition.py（新增） | 29 项比较、组装、安全、来源与兼容测试（含参数化） |
| backend/tests/test_report_presentation.py / test_report_workflow.py | 更新已被本轮替代的展示来源、单任务条数断言，保留旧报告兼容检查 |
| frontend/src/tests/business-report.test.tsx | 新增统一洞察渲染及拒绝详情检查 |
| backend/scripts/evaluate_report_insights.py（新增） | 真实模型评测，记录三层结果和错误，不覆盖已有运行 |
| backend/scripts/assess_report_insights.py（新增） | 分层客观引用诊断，不充当语义验收 |
| README.md 与本目录 | 说明、冻结快照、真实记录、评分和复现资料 |

[保护模块 SHA](protected-sha256.json) 在交付时复核一致。公开 `AnalysisReport / Insight / Evidence / InsightDraft` 的字段和类型没有改动；未新增 Draft 字段，也未新建报告业务契约。Evidence 的新增语义使用已有 comparison 类型及 value 内的受控子类型，旧客户端仍可读取。

## 3. Prompt 和模型配置

- 旧版：`report-insights-v1.1.4`；中间实验版：`1.1.5`；最终：`report-insights-v1.1.6`。
- [旧版全文](baseline-source/backend/app/reporting/prompt.py)、[最终全文](candidate-source/backend/app/reporting/prompt.py)、[逐行对比](prompt.diff)。
- 删除“每任务最多一条”和按任务数计算的请求上限；建议整体 1–3 条，不凑数。保留原 Draft 的最多 8 条，以覆盖较多 P0；每个有证据 P0 都必须有合法洞察。
- 模型选择同任务、同结果、同指标口径下的相关证据；优先差额/比例/变化，避免排名和极值重复。模型不输出 fact/finding、不计算数字。
- 原始目标、Intent 约束、批准步骤、字段名称/类型、上传缺失计数、任务样本定义和失败任务进入有界上下文，不发送整份原始数据。
- 沿用原 OpenAI-compatible Provider、`qwen3.8-flash`、严格 JSON Schema、`enable_thinking=false`、30 秒超时。temperature/top_p 未显式设置，服务端默认未知；不能声称采样完全可复现。
- 单次生成只有一次模型请求，没有自动修复、第二模型或 Agent Loop。没有写入 API Key、请求授权头或完整环境变量。

## 4. 新增比较证据

仍使用公开 `evidence_type=comparison`，增加三种 `value.comparison_kind`：

| 子类型 | 计算 | 销售例结果 |
| --- | --- | --- |
| relative_lead | (返回首位值 − 第二位值) / 第二位值 × 100 | 1,000 / 20,250 = 4.9% |
| relative_ratio | 返回末位值 / 首位值 × 100 | 5,760 / 21,250 = 27.1% |
| returned_concentration | 返回数值最高两组之和 / 本次完整返回组之和 × 100 | 41,500 / 47,260 = 87.8% |

原差额 E0007 与合计 E0008 保留；新证据追加在原证据后，S01 为 E0009–E0011。不是无限生成两两比较，每任务每指标最多新增三项。

每条包含 task_id、data_ref、result_field、来源行，以及 value 中的 dimension_field、metric_field、left/right、left_value/right_value、分子、分母、percent、公式和 source_scope。使用 Decimal，百分比四舍五入一位小数；分母必须为正。时间维度仍走原时间变化证据，不用金额排名替代时间顺序。并列、预览截断、缺失类别/数值等不生成不明确的新比例；平均数、median、distinct_count 不求和为集中度分母。

returned_concentration 明确保存 `denominator_scope=returned_groups_only`，并在 scope/statement 中说明不是全部筛选范围或整体市场。图表不会因这些 comparison 子类型把 Top N 自动当作完整构成饼图。

[独立 CSV/Pandas/Decimal 对照](independent-sales-verification.json)：原文件 SHA 与原验收一致，60 行、筛选 16 行，三个城市和所有新增百分比一致。

## 5. 多证据事实组装与安全边界

流程：已有真实结果校验 → EvidenceBuilder → 有界选择 → 单 LLM 草案 → 引用/口径/派生值核验 → 确定性组合所选 statement → AnalysisReport。

`fact` 为“证据核对：”加组合事实，`finding` 为组合后的业务事实；不再只使用 primary。主要证据控制发现类型，辅助证据实际进入文本。模型的解释前缀为“待验证的业务解释”，建议明确标记“尚未执行”。现有公开字段足够，不需要新增 Draft 字段。

核验包括：引用存在、不重复、含主要证据；同任务、结果、指标和源筛选范围；类型兼容；比较对象对应真实结果行；分子/分母/比例与公式一致；返回合计分母覆盖完整结果表，不能用截断预览；全部已有有效证据 P0 至少形成一条合法洞察。

排名和极值的同一类别/数值按事实键去重，不以不同证据 ID 冒充不同发现。现阶段仍会出现差额与相对差额的重复表述，代码不会把不同信息全部自动压缩成专业分析师叙述。

没有删除数字正则。自由文本中的指标数值仍不接受为已验证事实；数字来自确定性组装。只对能绑定到当前比较对象、已批准 Top N、已知任务 ID 的有限范围指代以及明确的否定边界做识别，扩充了利润/原因/英文比例/已证实声明的拒绝检查。

**这不是完整语义事实验证。** 正则和有限上下文规则既有漏检风险，也存在明显误拦截；本轮 holdout 已实际暴露。解释标记待验证并不使错误陈述变正确，无依据的肯定断言仍应拒绝，不可仅凭标签宣称安全达标。

候选级隔离：不合规候选不进入事实或建议。剩余核心洞察合法时保存部分报告，`report_status=partial`，limitations 披露拒绝数量，execution_metadata 保存候选序号、主要证据和错误码；前端折叠详情可查看。若全部候选失败，或已有证据的核心任务没有合法洞察，整次明确失败。没有模板替换、Mock 成功或静默删掉核心任务。Engine 状态和原结果不受影响。

## 6. AnalysisReport 与展示层统一

新报告在现有 execution_metadata 中保存 `insight_generation_version=evidence-composition-v1.1`，不修改公开 Report 字段。

- 新 `business-report-v1.1`：findings 直接映射 report.insights，recommendations 直接映射保存建议；不创建 V001–V005，不重新写摘要或业务建议。KPI 只格式化已保存指标，默认突出首位/领先比例/返回组内集中度。
- 无该标记的历史报告继续使用明确的 `business-report-v1` 展示逻辑；没有改写其已保存 JSON、重新调用模型或覆盖旧内容。前端详情标明历史展示版本。
- 页面和 HTML 都调用同一 Presentation 映射，已核对 findings/建议与原保存报告一致。
- 新版 Report.insight.limitations 保留在 JSON；当前主业务视图主要显示 report.limitations，逐条解释局限的展示仍可完善，不能把它视为本轮 UI 已全面优化。

实际销售真实模型报告存入独立 SQLite 后重新打开读取，结果逐字段一致，展示额外证据数量为 0：[持久化验证](persistence-verification.json)。未覆盖用户当前历史 report_id。

## 7. 真实模型评测结果

### 调用与生成可用率

| 运行 | Prompt | 模型实际返回 / 调用 | 生成情况 |
| --- | --- | ---: | --- |
| 正式基线 | 1.1.4 | 15/15 | 回归 11/11，未见 3/4；另 1 例无有效证据不调用模型 |
| 中间回归实验 | 1.1.5 | 11/11 | 失败全部保留，不作为最终对照 |
| 中间回归实验 | 1.1.6 / 旧阶段校验 | 11/11 | 失败全部保留，不覆盖后续结果 |
| 最终冻结实现 | 1.1.6 | 15/15 | 回归 7/11，未见 1/4；另 1 例正确 unavailable |

正式对照共 30 次返回，加中间回归 22 次，共 **52 次真实模型返回**。另有首轮受限环境的 15 次连接失败，单独留在 baseline-live.json，不冒充模型返回。没有在失败后不断重采样到成功替换记录。

最终 16 案例：4 complete、4 partial、7 生成失败、1 unavailable。可生成案例成功保存 **8/15（53.3%）**，低于基线 **14/15（93.3%）**；不得只报成功样本的业务质量。

### 三层客观证据利用诊断

这里的“家族命中”仅表示引用了冻结关注的差额/比例/变化证据，不表示自由解释正确，也不是语义准确率。失败仍留在固定分母。

| 层 | 旧版回归 | 新版回归 | 旧版未见 | 新版未见 |
| --- | ---: | ---: | ---: | ---: |
| LLM 原始候选：重要证据家族命中 | 1/13 | 13/13 | 1/4 | 4/4 |
| 保存 AnalysisReport 的洞察 | 1/13 | 9/13 | 1/4 | 1/4 |
| 实际 Presentation 的发现 | 5/13 | 9/13 | 1/4 | 1/4 |

旧 Presentation 多出的四个家族来自销售例独立规则层，不能计为旧 LLM 能力；新 Presentation 与保存洞察一致。旧输入只具备回归关注家族的 10/13，新版补齐到 13/13，这部分提升来自确定性证据能力，而非全归功于 Prompt。

最终保存 12 条洞察都带多个有效引用；其中 C03 第二条排名/极值实际还是同一个事实，**多引用不等于每条都实现信息综合**。逐例评分已为该例降低 C，不能拿 refs 数量充当质量验收。

### A–G 逐例语义复核

[逐例、逐层评分与理由](semantic-review.json)，依据冻结的 0/1/2 规则；A/G=0 为硬失败。复核由本次开发代理完成，**不是用户人工认可或独立盲评**。没有改权重、设新阈值或用总分抵消硬失败。

- 原始候选：最终回归 11 例中有 4 例出现硬失败（无依据资源判断、时间段稳定推断或跨指标口径）；未见 4 例未发现同类硬失败，但仍有风险表述和拒绝问题。
- 保存报告：8 例中复核未发现数值错误、已确认无依据因果或 Top N 总体比例误读；**仅限这 8 例，不能证明校验完备**。另 7 例没有合法完整报告，不计成事实正确样本。
- 回归成功报告的 C（综合深度）均值从 0.091/2 到 1.857/2，E（建议关联）从 1.091/2 到 1.714/2；分母分别 11 和 7，有明显幸存者差异，必须与生成可用率一起看。
- 新版保存报告 F 仍约 1/2：确定性事实拼接偏长、排名与差额有重复。旧版销售 Presentation 原本已是规则生成的易读三条发现；新版没有被评为页面可读性全面提升。
- 未见集最终只保存 1 例，不能据此宣称通用业务质量达标。

## 8. 销售案例实际前后对比

旧版保存的事实：“济南的已计算指标值为 21,250。”引用 E0002。建议为继续结合订单结构和成本资料评估，缺少城市比较。

新版原始模型选择三条：济南—南京比较、上海—济南比例、返回组内集中度。其中第三条解释/建议未通过校验，**报告明确 partial，只保存前两条，不把它包装为三条全部成功**。

保存的核心事实包含：济南 21,250、南京 20,250、相差 1,000、相对领先 4.9%；上海 5,760、为济南 27.1%。建议比较相关城市订单数量、平均订单金额与产品构成；上海方向建议核查记录完整性和渠道/产品分布，均标记未执行，未给出利润或原因结论。

87.8% 已作为 E0011 与 KPI 统一保存，分母 47,260，语义仅为返回三组。没有另用展示层补上一条已被拒绝的模型业务洞察。

- [真实模型生成的 AnalysisReport](sales-report.json)
- [同源 Presentation](sales-presentation.json)
- [可直接打开的 HTML 报告](sales-report.html)
- [完整最终调用，包括原始候选](final-live.json)

## 9. 全部剩余 Bad Case 与建议

| 案例 | 最终状态 | 问题 |
| --- | --- | --- |
| S01 | partial | 集中度解释被拒；有效事实仍有重复，不能用 KPI 冒充第三条洞察成功 |
| S02 | partial | 资源集中推测被拒；保留建议仍有“高单量少订单”等不清晰措辞、效率方向偏宽 |
| R01 | partial | 岗位数不能推出资源策略，第二候选被拒 |
| R02 | partial | 已保留时间变化；其他构成候选因自由用语被拒，离散点/中间过程需更精确 |
| C01 | complete | 有效比较和建议，但叙述偏长；补充资料建议不代表当前系统能直接执行 |
| C02 | complete | 缺失/均值比较改善，仍需验证更多缺失机制场景，不能只靠单例 |
| O01 | failed | 首末相等被解释为区间稳定，且有“两个时间点”等误拦截；保留原始输出 |
| O02 | failed | 正确利润缺口警示中的 P0 标识被数字规则拦截，构成用语也有误拦截 |
| R03 | failed | “所有已返回分组相等”符合数据但被所有一词误拒 |
| C03 | complete | 第二项仍是单极值；建议范围偏宽，未验证数据规则/事件仅能作为待核查方向 |
| O03 | failed | 工时与数量跨指标混引；不能放宽口径校验伪造综合 |
| H01 | failed | 未设阈值的“绝大部分”及数量指代边界问题 |
| H02 | failed | 否定原因边界、“两个服务组”等合法指代被保守规则误拦 |
| H03 | failed | “两个批次”及构成用语被拦；仍需更好的元数据驱动范围识别 |
| H04 | complete | 比较有依据，但事实组合仍重复，建议是需补资料的后续方向 |

S03 正确返回 unavailable，不列为失败。所有中间轮次、旧版失败及原始返回也保留在下列原始文件中。

下一轮建议：优先解决有上下文的范围/否定边界误拦截，以及自由解释与已验证事实的边界，而不是继续加词表或展示模板。跨指标比较只有在确定性 Evidence 显式构建并验证同范围关系后再支持。优化后需另建新的未见集；H01–H04 自本轮首次运行后已成为已见回归。当前不建议先做大规模 UI 美化掩盖生成可用率问题；可在稳定生成后做事实文本压缩与逐条局限展示。

## 10. 自动化和复现

- 后端：**630 passed**，原 601 项基础上新增 29 项；[日志](backend-tests.txt)。
- 前端：**51 passed**，原 49 项基础上新增 2 项；[日志](frontend-tests-final.txt)。
- TypeScript/Vite 生产构建通过：[日志](frontend-build-final.txt)。
- 包含完整 Engine/Planner/HITL/Workflow 既有测试；只有既有 TestClient 依赖弃用提示。
- 对候选伪造数值、城市错配、分母/百分比/来源行篡改、跨范围/指标、负值/并列/截断、失败披露、每个 P0 覆盖、历史报告兼容、HTML 一致性都有检查。

项目根目录运行自动化：

```sh
.venv/bin/python -m pytest backend/tests -q
```

前端目录运行 `npm test` 与 `npm run build`。真实评测需现有 backend/.env 配置及网络访问；以下命令会产生新的真实调用，输出必须使用新文件名，不覆盖历史：

```sh
.venv/bin/python backend/scripts/evaluate_report_insights.py --live --inputs docs/evaluations/insight-generator-v1.1/frozen-inputs-v2.json --output /tmp/insight-report-new-run.json
```

模型调用记录：

- [正式旧版基线](baseline-live-network.json)
- [中间 1.1.5 回归及全部失败](candidate-development-live.json)
- [中间 1.1.6 回归及全部失败](candidate-v116-development-live.json)
- [已保存原始返回的离线诊断，非新调用](v116-offline-guard-replay.json)
- [最终固定实现与首次未见评测](final-live.json)
- [原环境连接失败记录](baseline-live.json)
- [旧版客观诊断](baseline-objective-scores.json)、[新版客观诊断](final-objective-scores.json)、[三层 A–G 审阅](semantic-review.json)

**验收建议：保留工程改造，暂不宣称 V1.1 语义可靠性通过或达到专业分析师水平。** 当前真实模型原始候选更会选择比较证据，但规则泛化和生成可用率仍是主要阻碍。
