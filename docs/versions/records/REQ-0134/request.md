请检查并完善 InsightFlow Admin 的 Analysis Planner 节点详情展示。

保留当前运行追踪页面的左右布局：左侧为完整 Workflow 节点列表，右侧为当前选中节点的详情。

Analysis Planner 是 LLM 节点，右侧采用 Input、Output、LLM 三个 Tab，不新增 Diagnostics Tab。

首先检查 InsightFlow 中 Analysis Planner 的真实输入输出 Schema、业务规则、任务分级逻辑、LLM 调用记录及 Admin 现有组件，列出已实现、未展示、未持久化和缺失的字段。

**Input Tab：**

展示本次 Planner 实际接收到的需求理解结果、用户分析目标、分析模式、显式约束、数据集 Schema、数据质量信息及已有规划配置。

重点让管理员能够核对 Planner 的输入是否完整、是否保留用户原始约束。

**Output Tab：**

根据实际 Planner Schema 展示计划概览、分析任务列表、任务优先级、价值分级、可行性分级、所需字段、分析方法、任务依赖、规划风险及待确认事项。

任务采用可展开的卡片或列表，优先展示任务名称、核心/补充属性、价值和可行性；展开后展示详细分析逻辑。

保留查看原始结构化 Plan JSON 的能力。

不得将 Planner 自评的可行性标记为 Validator 已校验通过，也不得将生成计划标记为用户已审批。

**LLM Tab：**

复用现有 LLM 调用详情组件，展示真实 Call ID、模型、Prompt 版本、调用参数、耗时、Token、请求和响应，以及重试记录。

**数据补齐：**

已有字段直接复用；运行时存在但未持久化的必要信息，补充到现有 Trace 机制；完全不存在的字段先评估必要性，不为了 Admin 展示而修改 Planner 的核心规划逻辑。

保持现有 AnalysisPlan 业务契约与下游 Validator 的兼容性。优先通过独立 Trace 元数据扩展可观测信息。

历史记录缺失字段时显示未采集，不推断或伪造历史输出。

**验收：**

使用真实 Workflow 验证 Input、Output、LLM 三个 Tab，确保能追踪用户目标、约束、数据字段、规划任务和实际模型调用；确保左侧节点切换正常、右侧数据对应正确 Run，并且不影响现有规划、审批和执行流程。

请先检查代码并给出差距清单，再实施最小必要修改，最后提供修改文件、测试结果及剩余风险。
