# InsightFlow — Analysis Planner + Plan Validator V1 开发任务书

## 1. 开发目标

在现有 InsightFlow 工程中实现分析规划与计划校验能力。

系统接收 Intent Parser 的结构化分析意图和 Data Profiler 的数据画像，生成具有业务价值的分析任务，并校验任务是否能够由当前 Analysis Engine 执行。

本阶段只实现：

1. AnalysisPlan / AnalysisTask 数据结构
2. Capability Registry
3. Plan Validator
4. Analysis Planner LLM 接入
5. 单元测试及集成测试

暂不开发 HITL 页面、完整 Analysis Engine 或报告模块。

## 2. 模块职责

### Analysis Planner

输入：

- IntentResult
- DatasetProfile
- Capability Registry 摘要

输出：

- AnalysisPlan 草案

职责：

- 根据分析目标拆解候选业务问题
- 评估任务价值 P0/P1/P2
- 生成分析任务及结构化操作链
- 优先覆盖用户核心目标
- 识别重要但当前无法完成的需求

Planner 不执行统计计算，不生成自由 Python/SQL，也不决定最终执行可行性。

### Plan Validator

输入：

- AnalysisPlan
- DatasetProfile
- Capability Registry

输出：

- ValidatedAnalysisPlan

职责：

- 校验 Schema
- 校验字段引用
- 校验数据类型
- 校验操作能力
- 校验执行顺序与任务依赖
- 确定每个任务的 F0/F1/F2

Validator 必须使用确定性代码实现，不依赖 LLM 判断最终可行性。

## 3. 数据结构

### AnalysisTask
```json
{
  "task_id": "A01",
  "title": "城市岗位数量分布",
  "business_question": "不同城市的岗位数量有何差异？",
  "priority": "P0",
  "priority_reason": "直接回答核心分析问题",
  "depends_on": [],
  "steps": [
    {
      "step_id": "S01",
      "operation": "group_aggregate",
      "params": {
        "dimensions": ["field_city"],
        "metrics": [
          {
            "function": "count",
            "alias": "job_count"
          }
        ]
      }
    },
    {
      "step_id": "S02",
      "operation": "sort",
      "params": {
        "field": "job_count",
        "direction": "desc"
      }
    }
  ]
}
```

### AnalysisPlan
```json
{
  "plan_id": "plan_001",
  "dataset_id": "dataset_001",
  "dataset_version": 1,
  "plan_version": 1,
  "tasks": [],
  "unmet_core_requirements": []
}
```

`tasks` 存放 AnalysisTask。

`unmet_core_requirements` 由校验后对 P0/F0 任务的汇总产生，不能由 Planner 自行宣称已经解决。

### ValidationResult
```json
{
  "task_id": "A01",
  "feasibility": "F2",
  "reason_code": "READY",
  "validation_issues": [],
  "executable": true
}
```

最终的 ValidatedAnalysisPlan 包含原始计划和每个任务的校验结果。

## 4. Capability Registry

MVP 支持以下操作：

- `filter`
- `group_aggregate`
- `aggregate`
- `sort`
- `top_n`
- `derive`

聚合函数：

- `count`
- `sum`
- `avg`
- `median`
- `min`
- `max`
- `distinct_count`

初始确定性派生能力：

- `extract_year`
- `extract_month`

所有能力必须以实际实现和测试结果为准。

未实现的能力不能声明为 supported。

Registry 应明确各操作的参数 Schema、输入类型要求和输出字段规则，不能只维护操作名称列表。

## 5. 业务价值评估规则

Planner 采用 P0/P1/P2：

- P0：删除后无法充分回答核心问题或支持核心决策。
- P1：删除后仍可回答核心问题，但明显降低分析质量。
- P2：补充性分析，删除后对核心目标影响较小。

必须使用“删除该任务后的影响”判断优先级。

不得仅根据任务名称、分析方法或是否容易执行确定价值。

默认生成 3–5 个任务，但对于简单明确的需求允许生成更少任务。

## 6. 执行可行性规则

- F2：当前系统可以直接执行。
- F1：需要前置转换，且系统已经具备该转换能力。
- F0：缺少必要数据或系统不支持对应操作。

F1 的前置转换必须明确存在于可执行操作链中。

Validator 不得仅凭 LLM 声称“可以转换”而判定 F1。

建议原因代码：

- READY
- MISSING_FIELD
- INVALID_DATA
- UNSUPPORTED_OPERATION
- REQUIRES_TRANSFORMATION
- INVALID_FIELD_REFERENCE
- TYPE_MISMATCH
- INVALID_OPERATION_ORDER
- UNSUPPORTED_DEPENDENCY

## 7. Validator 五层校验

### V1 — Schema

检查必填字段、枚举、参数格式和唯一 ID。

### V2 — 字段引用

原始字段必须来自当前 DatasetProfile。

中间结果只能引用先前步骤生成的别名。

### V3 — 类型兼容

例如：

- 字符串类别字段可用于分组。
- 数值聚合必须使用可计算的数值字段。
- 时间派生必须使用有效时间字段。
- 不允许直接对薪资区间字符串求平均值。

### V4 — 能力匹配

每个操作和转换必须在 Capability Registry 中声明为已支持。

### V5 — 执行顺序与依赖

按照步骤顺序追踪字段集合与类型。

MVP 不支持跨任务依赖；非空 `depends_on` 应返回明确的不可执行原因。

## 8. P0 + F0 处理

当存在 P0 + F0 任务时：

- 保留任务及不可执行原因。
- 不允许执行该任务。
- 将其加入 `unmet_core_requirements`。
- 若剩余任务仍能提供有价值的部分分析，允许进入用户审核，但必须标记为部分覆盖。
- 若核心目标完全无法回答，则禁止将计划标记为可完整执行。

建议计划级增加：

- `coverage_status`：complete / partial / blocked
- `executable_task_ids`
- `blocked_task_ids`

覆盖状态应结合目标覆盖情况与任务校验结果计算，不能简单根据 F0 数量判断。

## 9. LLM 输出约束

Planner 必须输出符合 Schema 的 JSON。

禁止：

- 自由 Python/SQL
- 未声明的操作类型
- 虚构字段 ID
- 未经验证的语义派生能力
- 为凑任务数量生成无关分析
- 将系统无法执行的任务标记为已解决

模型输出无效时允许有限次数重试，重试失败必须返回明确错误。

## 10. 测试要求

至少覆盖：

1. 简单分组计数，P0/F2。
2. 多步骤 filter → group → sort → top_n。
3. 数值字段聚合。
4. 薪资区间字符串直接求均值，应被拒绝。
5. 已实现的确定性转换后聚合，可判为 F1。
6. 未实现的 JD 技能抽取，F0。
7. 引用不存在字段，F0。
8. 引用尚未生成的聚合别名，F0。
9. 非空跨任务依赖，F0。
10. P0/F0 仍保留在计划中。
11. 核心目标完全无法执行时，计划状态为 blocked。
12. 简单问题不强制生成 3–5 个任务。
13. 相同输入重复测试业务价值分级的一致性。

## 11. 实施顺序

第一阶段：检查现有工程结构、IntentResult、DatasetProfile 和 Engine 接口。

第二阶段：实现 Schema 与 Capability Registry。

第三阶段：实现确定性 Plan Validator，并完成单元测试。

第四阶段：接入 Planner LLM，设计 Prompt 和结构化输出校验。

第五阶段：使用招聘数据及其他通用业务数据测试，评估规划质量。

## 12. 验收标准

完成后应满足：

- Planner 输出可解析、可验证的 AnalysisPlan。
- Validator 能明确区分 F0/F1/F2。
- 不存在未经校验即可执行的任务。
- 不允许不存在的字段或未支持的操作进入执行计划。
- P0/F0 不会被静默删除。
- 简单分析需求不会被过度拆解。
- 所有核心规则均有自动化测试覆盖。

请先阅读现有项目结构，列出文件改动计划和现有接口需要调整的地方，再分阶段实施。不要自行扩展 MVP 范围。
