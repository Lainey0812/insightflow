# InsightFlow — Report Module V1 开发规格

## 1. 产品目标

面向没有专业数据分析经验的业务人员，将经过验证的计算结果转换为易于理解、可交互、可追溯的分析报告。

报告需要回答：

1. 数据呈现了什么现象？
2. 哪些发现最值得关注？
3. 这些发现对业务目标意味着什么？
4. 用户可以采取哪些下一步行动？
5. 哪些结论受到数据质量或分析范围的限制？

## 2. 模块输入

- `IntentResult`：原始分析目标及约束。
- `ValidatedAnalysisPlan`：分析任务、优先级和可行性。
- `ExecutionResult`：真实计算结果、执行状态和统计口径。
- `DatasetProfile`：数据集信息及质量问题。

禁止 Report Module 自行修改计算结果或补造缺失指标。

## 3. 模块结构

### 3.1 Evidence Builder

使用确定性代码从 ExecutionResult 提取证据。

支持：

- 排名和 Top N
- 最大值、最小值
- 占比
- 数值差异和变化率（分母有效时）
- 已计算指标的比较
- 数据覆盖率与有效样本量

每项证据必须绑定来源任务、结果字段及统计口径。

不能从截断的 Top N 结果推断整体占比，除非同时提供经过验证的总体分母。

### 3.2 Visualization Builder

使用规则选择默认图表，输出受控的 `ChartSpec`，由前端转换为 ECharts 配置。

| 分析意图      | 默认图表                       |
| --------- | -------------------------- |
| 类别数量比较    | 排序条形图                      |
| 时间趋势      | 折线图                        |
| 少量类别的整体构成 | 饼图或条形图                     |
| 单一指标      | KPI 卡片                     |
| 多字段明细     | 表格                         |
| 关键词热度     | 词云（V1.1，需 Engine 支持文本频次统计） |

图表选择应综合分析意图、字段类型、类别数量、标签长度和统计口径。

类别过多时，优先使用 Top N 条形图及完整表格，不自动改成词云。

V1 支持用户切换兼容的图表类型、查看结果数据和基础排序。

### 3.3 Insight Generator

由 LLM 基于结构化证据生成洞察。

每条洞察采用：

- `fact`：客观数据事实。
- `finding`：值得关注的规律或差异。
- `implication`：对用户业务目标的可能含义。
- `recommendation`：有依据的行动建议。
- `limitations`：相关局限性。

LLM 只能引用 Evidence Builder 提供的证据，不能自行计算或虚构统计值。

不得将相关性表述为已验证的因果关系。

## 4. AnalysisReport 数据结构
```json
{
  "report_id": "report_001",
  "execution_id": "exec_001",
  "plan_version": 2,
  "report_status": "partial",
  "goal_coverage": "partial",
  "summary": {
    "headline": "招聘机会主要集中在部分城市",
    "overview": "基于已完成任务的分析摘要",
    "evidence_refs": ["E01"]
  },
  "key_metrics": [],
  "insights": [],
  "charts": [],
  "recommendations": [],
  "limitations": [],
  "uncompleted_tasks": []
}
```

其中 `report_status` 表示报告生成状态，`goal_coverage` 表示业务目标覆盖程度，两者必须分开。

## 5. Evidence 数据结构
```json
{
  "evidence_id": "E01",
  "task_id": "A01",
  "result_field": "job_count",
  "evidence_type": "ranking",
  "value": {
    "category": "上海",
    "count": 42,
    "rank": 1
  },
  "scope": "用户上传的招聘样本",
  "calculation": "按城市分组计数后降序排名"
}
```

上述数字仅为示例。

每项 Evidence 必须能够追溯到真实 ExecutionResult。

## 6. Insight 数据结构
```json
{
  "insight_id": "I01",
  "fact": "上海在当前样本中有42条招聘记录",
  "finding": "上海的样本岗位数量排名第一",
  "implication": "上海可以作为进一步评估的候选城市",
  "recommendation": "结合薪资与岗位匹配度继续比较",
  "evidence_refs": ["E01"],
  "limitations": [
    "样本数量不代表整个招聘市场"
  ]
}
```

关键数值必须与 Evidence 一致。

建议实现两级校验：

1. 结构校验：引用存在、字段合法、证据类型匹配。
2. 事实校验：所有可识别的关键数值、排名和比例均与证据一致。

对于无法自动验证的解释性陈述，应采用谨慎表达；不应宣称已完成严格事实验证。

## 7. ChartSpec 数据结构
```json
{
  "chart_id": "C01",
  "task_id": "A01",
  "title": "各城市招聘岗位数量",
  "chart_type": "bar",
  "dimension": "city",
  "metrics": ["job_count"],
  "data_ref": "R01",
  "supported_chart_types": ["bar", "table"],
  "evidence_refs": ["E01"]
}
```

ChartSpec 只描述数据映射和图表类型，不允许包含任意 JavaScript 函数。

前端负责转换为 ECharts Option。

## 8. 报告页面结构

按照以下顺序：

1. Executive Summary：核心结论、目标和关键指标。
2. Key Findings：主要发现、业务解释和证据。
3. Interactive Charts：图表、切换、查看数据。
4. Recommendations：有依据的下一步建议。
5. Data Limitations：数据质量、样本范围、统计口径、失败任务。

默认优先展示与 P0 任务直接相关的发现。

不要单纯按照图表生成顺序排列内容。

## 9. 部分成功处理

当 ExecutionResult 为 `partial_success`：

- 保留成功任务的图表和洞察。
- 展示失败任务及原因。
- 不生成失败任务对应的事实或图表。
- 重新评估目标覆盖程度。
- 如果核心目标未被回答，不允许生成声称目标已完成的总结。

对于完全没有有效证据的情况，返回明确的报告不可生成状态，不调用 LLM 编造总结。

## 10. 交互范围

V1：

- 图表悬浮提示。
- 兼容图表类型切换。
- 查看底层聚合结果表格。
- 展开证据和统计口径。
- 查看分析局限性。

V1.1：

- 通过自然语言继续追问。
- 识别已有结果可回答的问题。
- 对新分析需求重新进入规划和审核流程。

V1 不实现完整对话式 BI。

## 11. 开发顺序

第一阶段：定义 Evidence、ChartSpec、Insight、AnalysisReport Schema。

第二阶段：实现确定性 Evidence Builder。

第三阶段：实现图表推荐规则及 ECharts 渲染适配。

第四阶段：接入 LLM Insight Generator。

第五阶段：实现证据引用和事实校验。

第六阶段：完成交互式报告页面及集成测试。

## 12. 验收标准

- 所有核心指标来自真实 ExecutionResult。
- 图表使用正确的维度和指标。
- 词云不会被错误用于普通分类频次比较。
- 洞察引用可追溯到有效证据。
- 无法验证的统计事实不能作为确定结论输出。
- 部分成功的报告明确披露未完成任务。
- 图表切换不触发重复分析。
- 普通业务人员可以理解结论及其依据。

请先检查现有工程的数据结构与接口，提出需要新增或调整的文件，再按阶段实施。不要自行扩大 MVP 范围。
