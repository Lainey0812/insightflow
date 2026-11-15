# InsightFlow — Report Module V1 真实接入任务书

## 一、任务目标

当前真实 Workflow 已完成：

Data Profiler → Intent Parser → Analysis Planner → Validator → HITL → Analysis Engine。

Analysis Engine 已能生成真实 ExecutionResult，但主流程尚未生成业务分析报告。

本轮目标是实现：

**Analysis Engine → Report Module → AnalysisReport → 前端报告页面**

## 二、先审计现有实现

开发前检查：

1. Report Module 是否已有实现。
2. 是否已有 Evidence Builder、Insight Generator、ChartSpec Builder。
3. AnalysisReport Schema 是否已经定义。
4. 是否已有报告生成及查询 API。
5. Workflow 是否有报告生成状态。
6. 前端是否已有报告页面或组件。

复用现有实现，不创建第二套 Report Module 或重复数据契约。

先输出审计结论，再进行最小必要开发。

## 三、Report Module 的输入

以真实 ExecutionResult 为主要计算依据，同时读取：

- 原始用户分析目标。
- 已批准的 AnalysisPlan。
- ValidatedAnalysisPlan。
- DatasetProfile。
- ExecutionResult 及其任务结果。

不得直接根据 Planner 的预期任务生成未经执行的数据结论。

## 四、Evidence Builder

从真实计算结果提取：

- 指标数值。
- 分组及排名。
- 差异与占比。
- 筛选条件和统计口径。
- 任务执行状态。
- 数据来源及引用。

所有派生数值必须由确定性代码计算，并能追溯到 ExecutionResult。

## 五、Insight Generator

使用现有 LLM Provider，根据 Evidence Builder 的证据生成：

- 分析摘要。
- 核心发现。
- 业务含义。
- 下一步分析建议。
- 数据局限性。

要求：

1. 每项核心发现关联证据引用。
2. 不允许编造数值。
3. 不允许将相关性表述为因果关系。
4. 不允许把推测写成已证实事实。
5. 不能仅凭销售额排名判断利润或经营效率。
6. 如果核心任务失败，不能生成完整覆盖的结论。
7. LLM 失败时明确返回报告生成失败或降级状态，不伪造洞察。

## 六、Chart Builder

根据真实结果确定性生成 ChartSpec。

MVP 支持：

- KPI。
- 柱状图。
- 折线图。
- 饼图。
- 数据表格。

图表必须与真实数据一致。

图表类型不适用时，回退为数据表格。

不使用 LLM 直接生成任意 ECharts JavaScript 代码。

## 七、Workflow 集成

HITL 批准后：

1. Analysis Engine 执行。
2. 保存 ExecutionResult。
3. Report Module 读取执行结果。
4. Evidence Builder 构建证据。
5. Insight Generator 生成洞察。
6. Chart Builder 生成图表配置。
7. 保存 AnalysisReport。
8. 前端展示报告。

保留 ExecutionResult 查询入口，不能用报告覆盖原始计算结果。

报告生成失败不得篡改已成功的 Engine 执行状态。

## 八、前端报告页面

建议展示：

1. 报告标题与分析范围。
2. 核心摘要。
3. 关键指标卡片。
4. 分析方向对应的图表和发现。
5. 业务含义与下一步建议。
6. 数据限制及未满足目标。
7. 查看原始计算结果。

普通用户默认看到业务分析内容，而不是 execution_id、步骤日志和内部 JSON。

技术信息可以放在可展开详情中。

## 九、验收测试

使用已有销售订单测试数据。

用户问题：

“帮我分析2026年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。”

预期数据：

- 济南：21,250。
- 南京：20,250。
- 上海：5,760。
- 前三名合计：47,260。

要求验证：

1. 报告数值与 ExecutionResult 一致。
2. 图表与数据一致。
3. 洞察有可追溯证据。
4. 不产生没有数据支持的因果解释。
5. 报告与执行结果均可持久化查询。
6. 页面刷新后可恢复报告。
7. LLM 报告生成失败时不丢失执行结果。
8. 原有 Planner、Validator、HITL、Engine 测试不得退化。

## 十、交付物

- 现有 Report Module 审计结论。
- 修改文件清单。
- 实际报告生成流程。
- AnalysisReport 示例。
- 真实 LLM 生成结果。
- 前端报告页面截图。
- 端到端测试结果。
- 剩余 Bad Case。

本轮不重新设计 Planner、Validator、HITL 或 Analysis Engine。
