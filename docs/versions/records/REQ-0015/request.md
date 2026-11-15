# InsightFlow — Intent Parser V1 开发任务书

## 一、开发背景

InsightFlow 当前已完成：

- Data Profiler V1：真实数据画像与持久化。
- Plan Validator V1：结构化计划校验。
- HITL V1：真实任务审核、删除、重新校验、不可变版本及服务端审批。
- Analysis Engine V1：真实数据执行、ExecutionResult 持久化。
- 六类确定性计算操作。

当前缺口：

用户自然语言分析需求尚未通过真实 LLM 稳定转换为结构化 IntentResult。

本阶段目标是实现 Intent Parser V1，并为后续 Analysis Planner 提供可靠的输入。

## 二、核心职责

Intent Parser 负责理解用户想分析什么，而不是决定具体如何计算。

输入：

- 用户原始自然语言请求。
- DatasetProfile 的轻量上下文。

输出：

- 分析模式。
- 分析目标。
- 用户明确提出的约束。
- 不确定性。
- 是否需要澄清。
- 必要的澄清问题。

Intent Parser 不负责：

- 生成 AnalysisTask。
- 选择计算操作。
- 判断任务的最终可执行性。
- 计算指标。
- 生成图表或报告。
- 修改原始数据。

## 三、输入设计

建议输入：
```json
{
  "user_query": "分析这份销售数据，看看哪些地区表现最好",
  "dataset_context": {
    "dataset_name": "sales.csv",
    "row_count": 150,
    "columns": [
      {
        "field_id": "field_region",
        "name": "地区",
        "physical_type": "string",
        "logical_type": "categorical",
        "semantic_tags": ["region"]
      },
      {
        "field_id": "field_sales",
        "name": "销售额",
        "physical_type": "float",
        "logical_type": "numeric",
        "semantic_tags": ["revenue"]
      }
    ],
    "sample_rows": []
  }
}
```

实际字段必须复用已有 DatasetProfile Schema，不得另建不兼容的数据画像模型。

只传递必要的字段元信息和少量经过脱敏、截断的样本，不允许将整个数据集传给 LLM。

## 四、IntentResult 输出契约
```json
{
  "analysis_mode": "goal_driven",
  "next_action": "proceed",
  "analysis_goal": {
    "analysis_object": "销售数据中的地区销售表现",
    "business_goal": "比较不同地区的销售表现",
    "decision_goal": null
  },
  "constraints": {
    "time_range": null,
    "filters": [],
    "metric_requirements": [],
    "analysis_limits": []
  },
  "uncertainties": [],
  "clarification_questions": []
}
```

字段约束：

### analysis_mode

仅允许：

- goal_driven
- exploratory
- undetermined

### next_action

仅允许：

- proceed
- clarify

### analysis_goal

包含：

- analysis_object
- business_goal
- decision_goal

无法从用户表达中可靠识别的字段使用 null。

不得为了填满 Schema 而编造目标。

### constraints

包含：

- time_range
- filters
- metric_requirements
- analysis_limits

保留用户明确提出的约束。

对于尚不能映射到具体字段的约束，保留原始表达，不要擅自丢弃或强行匹配。

### uncertainties

每项应记录：

- issue
- reason
- action：clarify / defer / annotate
- resolve_at：before_planning / plan_approval / before_execution

### clarification_questions

只输出真正影响后续分析的澄清问题。

优先一次提出最关键的问题，不要生成冗长问卷。

## 五、模式识别规则

### goal_driven

用户有明确分析问题或业务目标。

例如：

“比较不同地区的销售额，并找出销售额最高的三个地区。”

应返回 goal_driven。

### exploratory

用户希望探索数据，但没有明确限定分析维度。

例如：

“帮我分析一下这份销售数据。”

如果数据画像足以理解数据主题，应返回 exploratory，允许 Planner 生成合理的探索性分析计划。

### undetermined

无法识别用户想完成的分析任务。

例如：

“帮我处理一下。”

如果结合数据画像仍然无法判断，应返回 undetermined，并请求澄清。

不要将所有开放式分析请求都判断为 undetermined。

## 六、目标识别规则

严格区分三个目标：

**analysis_object：分析对象**

例如：2026 年各地区销售记录。

**business_goal：业务分析目标**

例如：比较各地区销售表现，识别销售差异。

**decision_goal：决策目标**

例如：确定下一季度资源投入重点。

只有用户明确表达或上下文充分支持时，才能填写 decision_goal。

例如用户说：

“分析不同城市的 AI 产品经理岗位分布。”

不能直接推断用户一定要选择求职城市。

## 七、约束提取规则

需要识别：

- 时间范围。
- 地区、品类等筛选条件。
- 指定统计指标。
- 排序、Top N 等分析限制。
- 用户明确提出的统计口径。

例如：

“只看 2026 年华东地区的订单，按销售额排名，取前五名。”

必须保留：

- 2026 年。
- 华东地区。
- 销售额。
- 排名。
- Top 5。

不得遗漏显式条件。

但 Intent Parser 不负责最终判断字段是否存在，也不负责执行筛选。

## 八、不确定性处理

### clarify

缺少阻断后续规划的必要信息。

例如用户只说“帮我处理一下”。

### defer

可以继续规划，但需要在审批或执行前确认。

例如用户要求“计算利润率”，数据有收入和成本，但未明确是否需要包含其他费用。

### annotate

不阻断执行，但应保留重要限制。

例如用户上传的招聘数据来自个人收集样本，不能直接代表整个招聘市场。

注意：不得仅凭文件名推断样本的代表性。

## 九、LLM 接入

复用现有项目的模型配置、Provider、API Key 管理及日志体系。

如尚无统一 Provider，可建立最小可扩展封装。

要求：

- 支持结构化 JSON 输出。
- 使用严格 Schema 校验。
- 设置合理超时。
- 支持有限次数重试。
- 区分模型调用失败、JSON 解析失败和语义校验失败。
- 不得将失败结果伪装为有效 IntentResult。
- 不记录原始 API Key。
- 控制发送给模型的数据大小。
- 防止数据集内容中的指令影响系统行为。

Prompt 应独立管理，便于版本迭代与评测。

## 十、确定性后置校验

LLM 返回后必须执行：

1. JSON 结构校验。
2. 枚举值校验。
3. 必填字段与 null 类型校验。
4. constraints 结构校验。
5. uncertainties 的 action / resolve_at 合法性校验。
6. next_action 与阻断性不确定性的一致性校验。
7. clarification_questions 与 clarify 状态的一致性校验。

对于可修复的格式问题，允许有限重试。

对于语义无法确定的问题，应返回澄清状态，而不是编造业务信息。

## 十一、测试数据集

至少覆盖四类数据：

1. 销售订单数据。
2. AI 产品经理招聘数据。
3. 客户服务或工单数据。
4. 项目任务或运营数据。

测试请求至少包含：

- 明确目标。
- 开放式探索。
- 模糊请求。
- 多个筛选条件。
- 明确决策目标。
- 未明确决策目标。
- 缺失关键统计口径。
- 数据字段与用户请求不匹配。
- 包含无关指令的数据样本。
- 模型返回不合法 JSON。

## 十二、模型质量评测

建立固定测试集及人工标注的预期结果。

建议初始目标：

| 指标         | V1 验收目标    |
| ---------- | ---------- |
| Schema 合法率 | 100%（对外返回） |
| 分析模式判断准确率  | ≥90%       |
| 明确约束提取召回率  | ≥95%       |
| 不应编造的决策目标  | 0 个        |
| 阻断性问题识别召回率 | ≥95%       |

这些是初始工程验收目标，不代表模型已经达到。

需要输出实际测试样本量、通过率、失败案例和原因。

## 十三、与 Workflow 的关系

本阶段只实现独立可调用的 Intent Parser。

允许新增必要的服务接口，但不要求立即替换聊天主流程中的全部 Mock。

输入 DatasetProfile，输出 IntentResult。

当 next_action=clarify 时，Workflow 后续应暂停 Planner，等待用户补充信息。

当 next_action=proceed 时，后续由 Analysis Planner 接收 IntentResult。

不要让 Intent Parser 直接触发 Analysis Engine。

## 十四、开发交付要求

请先检查现有代码并输出：

1. 已有 LLM 调用基础设施。
2. DatasetProfile 实际 Schema。
3. Intent Parser 是否存在部分实现。
4. 需要新增或修改的文件。
5. Prompt 和 Schema 管理方式。
6. 测试方案。

然后实现并交付：

- Intent Parser 服务。
- Prompt。
- IntentResult Schema。
- 确定性后置校验。
- 单元测试。
- 真实 LLM 测试记录。
- 评测数据与 Bad Case 分析。
- 调用示例。

本阶段不开发 Analysis Planner、HITL AI 修订或 Report Insight Generator。
