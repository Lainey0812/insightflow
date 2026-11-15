# Intent Parser V1.2 针对性优化与真实评测

已完成一次Prompt优化及真实模型回归。保持qwen3.8-flash，未增加LLM节点、未改IntentResult Schema，未用关键词后处理补齐输出。主要提升为完整指标保留和常见否定表达；仍存在范围遗漏、混合分类、原话拼接及否定目标扩写，未完成语义验收。

## 评测前交付与冻结

- [完整Prompt、Gold复核与设计](design.md)、[Prompt文本](prompt.txt)、[调用前冻结清单](freeze-manifest.json)。
- [原v1.1基线](../intent-v1.1/live-evaluation.json)及对应Prompt/标签/评分器保留原字节与哈希。历史旧口径约束召回为37/47=78.7%；下表重评为42/58=72.4%，差异来自评测前补齐9条参考标签及新评分范围，不是重新调用旧模型。
- [逐条Gold复核](../../../backend/evaluation/intent_gold_review_v12.json)：原40条请求不变，9条补充标签。由Codex做语义审阅，human_reviewed=false，未取得独立人工确认。

## 模型与样本

|配置|实际值|
|---|---|
|模型|qwen3.8-flash；Provider为现有compatible|
|Prompt|intent-v1.2；完整文本及SHA256随每批结果保存|
|结构输出|严格JSON Schema；Schema SHA256与v1.1相同|
|思考模式|enable_thinking=false|
|超时/尝试|每个请求总30秒，最多2次尝试|
|采样参数|未显式设置temperature/top_p/max_tokens，沿用供应商默认；不宣称输出确定性|
|主评测|原40条回归 + 28条未见样本，各一次，共68次Parser请求、70次真实模型尝试|
|主评测有效返回|67/68；C07两次尝试后原话校验拒绝。无Mock成功替代|
|补充诊断|C07再调用一次Parser、两次模型尝试，仍失败；未替换主成绩|
|发送数据|来自Profiler的轻量字段元数据和行数；不发送样本行或完整数据|
|自动化回归|460 passed；一项既有Starlette弃用警告；无前端修改|

## 冻结自动评测结果

下表严格保留评测前的标签及评分器，包含评分器的保守误报，不按评测结果修改标签或Prompt。召回按必需语义单元计数，精确率按模型实际预测项计数；不能混为同一个分母。

|指标|v1.1保存输出重评 / 原40条|v1.2原40条回归|v1.2未见28条|
|---|---:|---:|---:|
|约束召回率|72.4%|87.9%|96.9%|
|约束项精确率|75.0%|78.8%|87.7%|
|自动完整请求通过率|60.0%|67.5%|67.9%|
|显式指标完整率|75.0%|96.4%|100.0%|
|模式正确率（错误调用留分母）|100.0%|97.5%|96.4%|
|排序专项严格对齐率|25.0%|25.0%|45.5%|
|自动否定错误数 / 专项样本|5 / 5|0 / 5|2 / 12|
|合法返回 / 全部请求|40 / 40|39 / 40|28 / 28|
|自动整例通过数量|24 / 40|27 / 40|19 / 28|

分母：回归召回51/58、精确41/52；未见召回62/64、精确57/65；基线召回42/58、精确36/48。对外Schema合法率均为100%（只以返回的有效Intent为分母），不能将本轮39/40返回率写成40/40全成功。

## 语义复核修正及评分局限

**否定错误实际观察到3条，而非自动检出的2条：N07、N10、N11。** N10的constraints是正确的，但business_goal把未指定中位数扩写为需要探索的目标。这说明仅检查指标列表和原话子串会漏掉目标文本中的语义反转。

|补充口径|基线40条|本轮回归40条|本轮未见28条|
|---|---:|---:|---:|
|否定专项：自动检查加本轮语义复核|5 / 5|0 / 5|3 / 12|
|保守完整请求通过率|24/40，60.0%|27/40，67.5%|18/28，64.3%|

保守完整通过率保留所有自动失败，只从自动通过中扣除新增N10错误，没有给评分争议补分。合计45/68=66.2%；本轮否定错误3/17。旧基线否定5条包含未指定说明误分类及禁令遗漏，不是5条均发生直接文字反转。

自动精确率也不是语义精确率的无偏估计：S01/S04及O01/O04/O05/O07/O08都已分别保留指标和排序限制，只因限制原话带指标上下文被纯净类别规则拒绝；O03的“展示前四类”在目标中有明确工单类别，但未匹配完整参考片段。这些作为评分器争议单列，保留原分数，不冒充真实统计错误或偷偷修改Gold。完整请求通过率只覆盖已定义检查，不能视作任意自然语言的严格事实证明。

排序专项语义观察：旧3个典型排名链S04/C04/P04都漏分类；本轮S04/P04分别保留指标与排名，C04仍错。8条独立O系列均把排序依据保留为指标并在限制中保留排序；O03的Top N对象片段略写，自动规则仍报缺失。单轮观察不能证明排序分类已稳定解决。

## 所有剩余案例与争议

以下列出13条回归自动失败、9条未见自动失败，以及额外发现的N10，共23条。包含真实缺陷与评分争议，未静默删除任何一条。[完整实际JSON与错误](remaining-bad-cases.json)，[逐条语义复核](semantic-review.json)。

|案例|归类|实际问题或复核结论|
|---|---|---|
|S01|scorer_limitation|指标已单独保留；限制中的“找出销售额最高的三个地区”带有排序依据上下文，自动纯净类别规则过严，不能简单断言模型语义错误。|
|S04|scorer_limitation|销售额已在指标、排名及前五名已在限制；同一句限制带指标上下文被自动评分拒绝。另有按订单排名的粒度解释，可在审批阶段明确。|
|S08|missing_scope|AI产品经理只在目标，不在filters；按评测前复核规则，已知岗位子集仍需保留。|
|S10|annotation_boundary|按地区比较在analysis_limits；是明确比较维度但冻结标签没有该可选单元，属分类边界争议，不能称作虚构用户条件。|
|R05|missing_scope|已正确澄清城市，但指定城市原话未同步保留为未验证范围。|
|R08|missing_scope|AI产品经理岗位子集未进入filters。|
|C04|classification_error|排名仍只在metric_requirements，analysis_limits只有前五名；时间和子集复制同一整句，类别边界仍混杂。|
|C07|grounding_error|主回归两次尝试后LLM_UNGROUNDED_OUTPUT；补充两次调用再次失败，拼成非原话的“指定客户还没告诉你”。原文为“指定客户的响应时长，具体客户还没告诉你”，这不是连续子串。校验拒绝正确，不能补齐伪造成功。|
|C08|missing_scope|招聘薪资已保留，AI产品经理岗位子集仍仅在目标。|
|P04|mixed_scope_and_scorer_limitation|指标与排名分别存在；filters复制包含时间的完整句造成跨类混杂，限制带指标上下文也触发了过严规则。|
|P06|over_extraction|将裸动词“比较”另作analysis_limits；未提供真实新增限制。|
|P08|annotation_boundary|将比较维度“比较各地区”作为analysis_limits；冻结标签未覆盖此可选表达，保留争议。|
|P09|classification_error|今年已在time_range，又将“只看今年的任务”作为filters；时间/子集边界不够清晰。|
|O01|scorer_limitation|销售额单独保留，限制带销售额上下文；排序和末尾两名均存在。|
|O03|fragment_matching_limitation|限制为“展示前四类”，完整对象在analysis_object=工单类别及business_goal中；严格完整片段“前四类工单”未匹配，语义对象并未完全丢失。|
|O04|scorer_limitation|任务数量、实际工时合计都在指标，按实际工时合计排名在限制；纯净类别评分过严。|
|O05|scorer_limitation|库存件数独立在指标，排名和前六项在限制；带指标的排名上下文被评分拒绝。|
|O07|scorer_limitation|成本独立保留，降序和前两条订单在限制；带指标上下文不等于漏分。|
|O08|scorer_limitation|实际工时独立保留，升序展示在限制；带指标上下文触发评分限制。|
|N02|mode_mismatch|销售额分布被分类为exploratory，冻结标签为goal_driven；均值/中位数未被误加为指标。此模式边界仍值得独立人工复核。|
|N07|negation_semantic_error|business_goal将“不要求计算成交金额”改为“明确排除成交金额的计算”，将非强制要求强化为禁令；analysis_limits也保存了该非约束说明。|
|N10|negation_semantic_error_missed_by_automation|指标列表只有平均响应分钟，但business_goal新增“并探索响应分钟的中位数分布特征”，把未指定中位数升为分析目标。冻结自动规则仅查constraints未检出，语义复核新增一条错误。|
|N11|negation_classification_error|business_goal保留不排除北京，未出现排除北京的直接文字反转；但该完整否定范围被放入filters而非analysis_limits，存在后续误作筛选的风险。计入否定处理错误，区分于直接语义反转。|

## 实际输出对照

- R01“分析各城市岗位数量”：旧结果指标为空；本轮metric_requirements完整保留“岗位数量”。
- C06“统计各类工单数量”：旧结果只有“数量”；本轮保留“工单数量”。
- R10“分析薪资情况，但没有指定均值或中位数”：旧结果把“均值或中位数”列为指标；本轮指标为“薪资”，业务目标忠实说明统计口径未指定，留defer而不阻断。
- S04：本轮metric_requirements=销售额，analysis_limits=按销售额排名，取前五名；不再仅把排名塞进指标。
- N07：实际business_goal“计算点击次数，明确排除成交金额的计算”；把不要求强化成排除，仍需修复。
- N10：实际business_goal“计算平均响应分钟，并探索响应分钟的中位数分布特征（口径未指定）”；不能因括号写未指定就视为已正确理解。

## 原始记录与复现

- [本轮40条回归](regression-live.json)、[28条未见输出](heldout-live.json)、[旧输出按同一标签重评](baseline-rescored.json)。
- [C07补充实际输出](c07-supplementary-trace.json)：只记录合成需求的模型正文，Key已检查未出现在交付文件；生产日志仍不记录原文。原主回归失败输出未记录正文，无法追溯其确切字段，补充复现不能冒称原先两次的正文。
- [结构化对比](comparison.json)。冻结清单涵盖Prompt、标签与评分器；本轮结束后逐项复核哈希未变化。

在已安全加载模型环境变量的终端，从backend运行；以下命令会调用真实模型，应用与脚本不会自动读取.env。为保留本轮记录，重跑使用新的输出文件：

```bash
../.venv/bin/python scripts/evaluate_intent.py --live --cases evaluation/intent_cases_reviewed_v12.json --output ../docs/evaluations/intent-v1.2/regression-rerun.json
../.venv/bin/python scripts/evaluate_intent.py --live --cases evaluation/intent_heldout_v12.json --output ../docs/evaluations/intent-v1.2/heldout-rerun.json
../.venv/bin/python scripts/rescore_intent.py --source ../docs/evaluations/intent-v1.1/live-evaluation.json --cases evaluation/intent_cases_reviewed_v12.json --output ../docs/evaluations/intent-v1.2/baseline-rerescored.json
../.venv/bin/python -m pytest -q
```

## 尚未解决

1. 未指定/不要求与禁止之间仍有边界错误，且错误可能仅在business_goal出现。
2. 已知范围在目标、filters、不确定性间保留不一致；长原话复制会混合时间、筛选和排序。
3. C07非连续原话拼接不能靠当前只返回错误类别的重试稳定纠正。
4. 精确率评分需在下一版设计时纳入合法上下文与等价片段，先冻结新规则、重评两版保存输出；本轮未据成绩修改评分器。
5. 本轮只有每样本一次、工程合成数据、代理审阅，未完成人工Gold确认、重复稳定性及真实业务泛化评估。新增未见样本在后续Prompt迭代中已属于可见集，应另建独立保留集。

不以96.9%的未见约束召回或任何单个95%分数宣称语义验收完成；主流程、审批、执行和报告逻辑保持本轮范围外。
