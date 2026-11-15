# InsightFlow — Intent Parser V1 开发规格

## 1. 模块目标

Intent Parser 负责理解用户的数据分析需求，将自然语言转换为结构化的分析意图，供 Analysis Planner 使用。

它不负责生成分析任务、执行计算或判断所有任务的数据可行性。

## 2. 输入

- `user_query`：用户原始分析需求。
- `dataset_context`：由 Data Profiler 提供的轻量级数据上下文，包括数据集名称、字段名称、逻辑类型和必要的脱敏样本行。

不向 LLM 传输完整数据集。

## 3. 输出
```json
{
  "analysis_mode": "goal_driven",
  "next_action": "proceed",
  "analysis_goal": {
    "analysis_object": "AI产品经理招聘岗位",
    "business_goal": "比较不同城市的招聘情况",
    "decision_goal": "确定优先投递城市"
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

## 4. Analysis Mode 规则

- `goal_driven`：用户提出明确的业务问题或分析目标。
- `exploratory`：用户希望探索数据中的规律、趋势、差异或异常，但没有限定具体分析问题。
- `undetermined`：结合输入和数据上下文，仍无法判断用户希望开展什么分析。

判断时优先识别是否存在明确分析问题，不能仅依赖关键词。

## 5. Next Action 规则

- 当 `analysis_mode = undetermined` 时，返回 `clarify`。
- 当缺少制定合理分析计划所必需的信息，且无法从上下文可靠确定时，返回 `clarify`。
- 其他情况返回 `proceed`。

不因缺少图表类型、非必要筛选条件或可在计划审核阶段确定的统计口径而过度澄清。

## 6. Analysis Goal 提取规则

- `analysis_object`：分析对象。依据用户输入和数据上下文提取。
- `business_goal`：希望通过分析回答的问题或达到的分析目标。
- `decision_goal`：希望支持的业务决策；没有明确依据时返回 `null`。

不得仅根据数据字段推断用户的职业、商业或其他决策目的。

对于探索式分析，允许将 `business_goal` 规范化为探索数据的主要特征、规律和异常。

## 7. Constraints 提取规则

支持：

- `time_range`：时间范围。
- `filters`：筛选条件。
- `metric_requirements`：指标和统计口径。
- `analysis_limits`：分析范围或输出限制。

保留用户原始约束。可以规范化明确的表达，但不得编造字段、过滤值或日期范围。

尚未验证的约束不能标记为可执行条件。

## 8. Uncertainties 规则

每项不确定性包含：

- `id`
- `description`
- `impact`
- `action`：`clarify`、`defer`、`annotate`
- `resolve_at`：`before_planning`、`plan_approval`、`before_execution`

处理原则：

- `clarify`：阻断规划，必须用户补充。
- `defer`：允许规划，但后续必须解决。
- `annotate`：记录重要风险或假设，不阻断。

不记录无实际影响的细节缺失。

若存在阻断性 `clarify`，则 `next_action` 必须为 `clarify`，并生成针对性问题。

## 9. 工程要求

1. 复用现有 FastAPI 项目结构与统一 LLM Provider。
2. 使用结构化 Schema 校验模型输出。
3. 对非法枚举、缺失字段和流程规则冲突进行处理。
4. LLM 调用失败时返回明确错误，不伪造识别成功结果。
5. 保留原始用户输入，便于调试与追溯。
6. 将 Intent Parser 作为独立业务模块供 Workflow Orchestrator 调用。
7. 不在本模块实现 Analysis Planner 或 Analysis Engine。

## 10. 验收要求

至少覆盖以下测试：

| 测试输入                    | 预期模式         | 预期决策                         |
| ----------------------- | ------------ | ---------------------------- |
| 分析各城市岗位数量               | goal_driven  | proceed                      |
| 探索招聘数据的主要规律             | exploratory  | proceed                      |
| 帮我分析一下这份数据（已有可理解的数据上下文） | exploratory  | proceed                      |
| 帮我处理一下                  | undetermined | clarify                      |
| 比较指定城市的薪资，但没有指定城市       | goal_driven  | clarify                      |
| 分析薪资情况，但没有指定均值或中位数      | goal_driven  | proceed                      |
| 分析招聘数据（未说明用于什么决策）       | goal_driven  | proceed，decision_goal 为 null |

还需验证结构化输出错误、空输入、数据上下文缺失、LLM 超时及不确定性与流程决策的一致性。

## 11. 开发步骤

请先检查当前工程结构及 DatasetProfile 的实际 Schema，确认字段映射方式。datasetProfile最理想获得途径是从dataprofiler中的columns获得，而不是要用户手动输入提供

随后输出需要新增或修改的文件、模块实现方案、测试计划。

先完成 Intent Parser V1，不扩展其他模块。
