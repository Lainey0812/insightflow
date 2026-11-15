# Codex 执行任务：REQ-0059 — InsightFlow Lifecycle V1.0

## 一、你的角色

你是一名资深 AI Agent 架构师、Python/FastAPI 后端工程师和可观测性系统工程师。

你需要基于 InsightFlow 现有代码，实现完整分析任务的生命周期管理与 Trace 关联能力。

本次开发必须遵循：

- 先审计真实代码，再进行设计。
- 优先复用现有业务状态机和 Trace 基础设施。
- 不引入新的 Agent Runtime。
- 不修改现有 Prompt、模型参数、数据分析算法。
- 不改变正常业务执行结果。
- 不允许根据业务状态伪造节点执行记录。
- 所有新能力必须具备自动化测试和验收证据。

## 二、项目背景

InsightFlow 是一个面向普通业务人员的数据分析 Agent。

现有业务流程：

```text
Session Created
    ↓
Data Profiler
    ↓
Intent Parser
    ↓
Analysis Planner
    ↓
Plan Validator
    ↓
HITL Approval
    ↓
Analysis Engine
    ↓
Evidence Builder
    ↓
Chart Builder
    ↓
Insight Generator
    ↓
Fact Validator
    ↓
Report Assembler
    ↓
Report Persistence
```

上述为主流程，不代表所有节点每次都必然执行。

当前系统：

- 使用 FastAPI、BackgroundTasks 和现有业务状态机。
- 已存在 Session、PlanVersion、Approval、ExecutionResult、ReportGeneration 等业务对象。
- Reporting 已具备部分 TraceRun / TraceSpan 能力。
- Intent Parser、Analysis Planner 和 Insight Generator 已具备 LLM CallRecord 基础。
- 尚无统一的 Workflow Root TraceRun。
- 准备阶段、HITL 和 Engine 尚未完整接入 Trace。
- Admin 尚不能展示真实全链路节点 Progress。

现有 REQ-0058 审计可作为参考，但必须以当前代码为最终依据。

## 三、最终目标

实现三级生命周期：

### L1 — Workflow Lifecycle

一次用户分析任务对应一个稳定的 Workflow Root Run。

生命周期包括：

- created
- running
- waiting_input
- waiting_approval
- succeeded
- partially_succeeded
- failed
- interrupted

注意：这些是目标语义状态，不要求直接替换现有 Session.status 或 TraceRun.status 枚举。

### L2 — Node Lifecycle

每次真实节点执行对应一个独立 Span。

基础状态：

- running
- complete
- failed
- skipped
- interrupted

如现有 Trace 支持 partial，则保留其语义。

pending 主要是 UI 根据流程定义与实际记录计算的展示状态，不应为未执行节点创建虚假 Span。

### L3 — Attempt Lifecycle

记录节点内部实际调用和重试。

例如：

```text
Analysis Planner Node
    ├── Span A（第一次真实执行）
    │      ├── LLM Call 1 timeout
    │      ├── LLM Call 2 timeout
    │      └── failed
    │
    └── Span B（用户重新执行）
           └── LLM Call 3 succeeded
```

要求：

- 每次真实执行独立记录。
- 内部 LLM 重试关联所属节点 Span。
- 人工重新执行生成新的 Span。
- 不能覆盖历史失败记录。

## 四、阶段 0：代码审计与生命周期设计

**优先级：P0**

第一阶段只允许只读审计和文档设计，不允许修改业务代码。

### Task 0.1 — 审计现有生命周期

检查：

1. Session 创建、更新和终态。
2. Data Profiler 的真实调用入口。
3. Intent Parser 的执行、澄清与恢复。
4. Analysis Planner 的执行、重试和失败。
5. Plan Validator 的所有实际调用点。
6. HITL 的计划修订、审批、拒绝和版本冲突。
7. Analysis Engine 的执行、部分成功和恢复。
8. ReportGeneration 的创建、执行和重试。
9. 现有 TraceRun、TraceSpan、TraceEvent。
10. LLM CallRecord 与 Prompt Registry 的关联方式。

重点确认：

- 哪些状态已由业务数据库持久化？
- 哪些状态仅存在于内存或请求上下文？
- 哪些执行路径没有 Trace？
- 哪些状态会跨 HTTP 请求变化？
- 哪些流程允许重试？
- 哪些流程可以中断并恢复？

### Task 0.2 — 输出 Lifecycle 状态流转表

为每个节点定义：

| 字段 | 说明 |
|---|---|
| node_id | 稳定节点标识 |
| trigger | 真实开始条件 |
| input | 输入契约 |
| success_condition | 执行成功条件 |
| business_outcome | 业务结果 |
| failure_condition | 执行失败条件 |
| retry_policy | 重试机制 |
| resume_policy | 恢复机制 |
| trace_boundary | Span 创建与结束位置 |
| related_records | 关联业务记录 |

必须明确：

- Intent clarify 是正常业务结果。
- Plan Validator F0 不自动代表系统失败。
- Engine partial_success 是业务执行结果。
- Fact Validator 拒绝候选不自动代表节点失败。
- HITL 等待不能作为持续计算耗时。
- ReportGeneration 与 Report TraceRun 不属于同一种对象。

### Task 0.3 — 设计 Workflow 状态聚合规则

制定明确的状态推导规则。

不能直接使用：

```python
workflow_status = session.status
```

需要结合：

- Session
- Intent 澄清状态
- Plan Review / Approval
- ExecutionResult
- ReportGeneration
- Trace 完整性

特别处理：

- Engine 成功但报告失败。
- Engine 部分成功且报告成功。
- Intent 等待用户输入。
- HITL 等待审批。
- 报告重试中。
- 服务中断后恢复。
- Trace 数据缺失。

要求区分：

1. 业务生命周期状态。
2. Trace 采集状态。
3. UI 展示状态。

### Task 0.4 — 设计 Root Run 生命周期

明确：

- Root Run 创建时机。
- Root Run 与 Session 的关联方式。
- 唯一性约束。
- 并发创建处理。
- 跨请求上下文传递。
- 等待和恢复时的状态变化。
- 终态条件。
- 后续重试时是否允许重新打开 Root Run。
- 历史数据兼容策略。

注意：不能简单地把 Root Run 在第一次失败时永久结束，否则后续恢复会产生生命周期冲突。

### 阶段 0 交付物

输出：

- `REQ-0059-lifecycle-audit.md`
- `REQ-0059-lifecycle-state-machine.md`
- `REQ-0059-trace-data-contract.md`
- `REQ-0059-implementation-plan.md`

文档需包含实际代码路径、函数名称、当前行为、设计变更和风险。

**完成后停止开发，提交设计结果供评审。**

---

## 五、阶段 1：Workflow Root Run

**优先级：P0**

阶段 0 通过评审后执行。

### Task 1.1 — 数据结构扩展

在现有 Trace 数据模型上扩展：

- Workflow Root Run 类型。
- Session 与 Root Run 的稳定关联。
- Root Run 与 Report TraceRun 的显式关联。
- 必要的索引和唯一性约束。
- 数据迁移与历史兼容。

不允许删除现有 Report TraceRun。

### Task 1.2 — Root Run 创建

在 Session 成功创建后，建立或获取 Root Run。

要求：

- 幂等。
- 并发安全。
- 不重复创建。
- 不影响 Session 创建结果。
- Trace 写入失败可检测。

### Task 1.3 — Root Run 状态更新

建立受控状态更新机制。

支持：

- created → running
- running → waiting_input
- waiting_input → running
- running → waiting_approval
- waiting_approval → running
- running → succeeded / partially_succeeded / failed
- interrupted → 恢复或终止

具体转移必须经过阶段 0 的状态机评审，不能直接照搬以上示例。

### 阶段 1 验收

- 同一 Session 不重复创建 Root Run。
- 澄清后仍关联原 Root Run。
- 审批后仍关联原 Root Run。
- 重试保留原任务关联。
- 历史 Report Trace 查询不受影响。
- Trace 失败不改变业务执行结果。

---

## 六、阶段 2：准备阶段 Node Span

**优先级：P0**

### Task 2.1 — Data Profiler

在真实执行入口创建 Span。

记录：

- start
- finish
- duration
- status
- error

### Task 2.2 — Intent Parser

记录：

- 真实执行 Span
- LLM CallRecord 关联
- clarify 业务结果
- timeout / error
- 澄清后重新执行

要求：

Intent 返回 clarify 时，Span 可以正常完成，Workflow 进入 waiting_input。

### Task 2.3 — Analysis Planner

记录：

- 真实执行 Span
- LLM 调用
- 内部重试
- Schema 错误
- 超时
- 人工重新执行

要求：

内部重试不重复创建主进度节点。

### Task 2.4 — Plan Validator

记录所有真实调用。

必须区分：

- 规划阶段校验
- 计划保存校验
- 修订/审批校验
- 报告输入校验

每次实际执行保留独立记录，不能将后续校验结果覆盖到前一次。

### 阶段 2 验收

- 正常准备流程完整记录。
- Planner 超时能定位真实 Span。
- LLM CallRecord 可关联 Planner Span。
- Intent clarify 正确显示等待。
- 用户重新执行产生新的 Span。
- 未执行节点没有伪造 Span。

---

## 七、阶段 3：HITL 生命周期

**优先级：P1**

### Task 3.1 — 等待审批

记录：

- 进入审批等待
- 对应 PlanVersion
- 等待开始时间

不创建长期保持 running 的计算 Span。

### Task 3.2 — 计划修订

记录：

- 删除任务
- 新计划版本
- 重新校验
- 原审批失效

### Task 3.3 — 审批结果

记录：

- approval accepted
- approval rejected
- approval conflict
- resume requested

需要关联真实 Approval 和 PlanVersion。

### 阶段 3 验收

- 等待审批状态准确。
- 用户修订后版本关联准确。
- 版本冲突不会显示为节点计算失败。
- 用户等待时间不计入计算耗时。
- 审批后能够继续原 Workflow。

---

## 八、阶段 4：Analysis Engine 生命周期

**优先级：P1**

### Task 4.1 — Engine Span

在真实 Engine 执行入口接入。

记录：

- 执行开始
- 数据加载
- 任务执行
- 结果持久化
- 执行结束

### Task 4.2 — Task 诊断关联

主 Progress 展示一个 Analysis Engine 节点。

Node Inspector 可查看：

- task_id
- task.status
- operation
- duration
- error
- ExecutionResult

### Task 4.3 — 异常路径

覆盖：

- 任务部分成功
- skipped
- 执行失败
- 幂等重放
- 中断恢复

### 阶段 4 验收

- Engine 成功有真实 Span。
- partial_success 语义正确。
- 跳过任务有真实业务依据。
- 重复请求不产生虚假执行。
- Engine 失败可定位具体 Task。

---

## 九、阶段 5：Reporting Lifecycle

**优先级：P1**

### Task 5.1 — 关联现有 Report TraceRun

建立：

- Workflow Root Run ID
- ReportGeneration ID
- Report TraceRun ID
- Report Attempt ID

保持既有 Reporting Trace 兼容。

### Task 5.2 — 补充 Chart Builder Span

确保以下节点有真实追踪：

- Evidence Builder
- Chart Builder
- Insight Generator
- Fact Validator
- Report Assembler
- Report Persistence

### Task 5.3 — 报告状态聚合

区分：

- 报告执行成功
- 报告内容完整
- 报告部分可用
- 报告不可用
- 报告重试中
- 报告执行失败

### 阶段 5 验收

- Report TraceRun 可归属 Workflow Root Run。
- Report Retry 不生成新的用户分析任务主记录。
- Chart Builder 有真实 Span。
- 报告失败不会被 Session.COMPLETED 掩盖。
- Fact Validator 的业务拒绝不被误判为系统异常。

---

## 十、阶段 6：Admin 生命周期可视化

**优先级：P1**

### Task 6.1 — Run Explorer

一条用户分析任务对应一条主记录。

展示真实节点：

1. Data Profiler
2. Intent Parser
3. Analysis Planner
4. Plan Validator
5. HITL Approval
6. Analysis Engine
7. Evidence Builder
8. Chart Builder
9. Insight Generator
10. Fact Validator
11. Report Assembler

### Task 6.2 — 节点状态映射

颜色：

- 灰色：pending / skipped
- 蓝色：running
- 绿色：succeeded
- 黄色：waiting_input / waiting_approval
- 红色：failed / interrupted

使用图标或文本进一步区分同色状态。

### Task 6.3 — Node Inspector

点击节点展示：

- 执行状态
- Span ID
- Attempt 历史
- 执行耗时
- LLM CallRecord
- Prompt Snapshot
- 错误信息
- 业务结果

### Task 6.4 — 自动刷新

- Run Explorer：5–10 秒。
- Trace Detail：2–3 秒。
- 终态停止轮询。
- 接口异常显示不可用，不伪造状态。

### 阶段 6 验收

- 正常任务显示真实节点链路。
- Planner 失败显示红色节点。
- HITL 等待显示黄色。
- 重试可查看历史 Attempt。
- Report Retry 关联同一 Workflow。
- 历史无 Trace 显示未采集。
- 不根据节点顺序推断成功。

---

## 十一、测试要求

每阶段至少包括：

### 单元测试

- 状态转换
- Span 生命周期
- 幂等性
- 业务结果映射
- 错误处理

### 集成测试

- Session → Root Run
- Node → Span
- Span → LLM Call
- Approval → Workflow
- ExecutionResult → Engine Span
- ReportGeneration → Report TraceRun

### 异常测试

- LLM timeout
- Schema error
- HITL conflict
- Engine partial_success
- Report failure
- Report retry
- Process interruption
- Trace persistence failure

### 真实验收

使用现有真实 CSV 数据与真实业务流程验证。

不得将 Mock 结果当作真实模型运行结果。

---

## 十二、实施约束

1. 不修改 Prompt 和模型参数。
2. 不修改分析算法。
3. 不重构业务编排。
4. 不新增通用 Runtime。
5. 不直接删除历史 Trace 数据。
6. 不根据 Session.status 回填虚假 Span。
7. 不将业务拒绝等同于系统异常。
8. 不将用户等待计入计算耗时。
9. 不覆盖历史 Attempt。
10. 不在未经评审时直接实施所有阶段。

## 十三、执行与汇报方式

严格按照以下顺序：

```text
阶段 0：代码审计与设计
        ↓
设计评审
        ↓
阶段 1：Root Run
        ↓
阶段 2：准备节点
        ↓
阶段 3：HITL
        ↓
阶段 4：Engine
        ↓
阶段 5：Reporting
        ↓
阶段 6：Admin UI
        ↓
端到端验收
```

每阶段完成后输出：

- 变更文件清单
- 数据库变更
- 新增接口或数据契约
- 自动化测试结果
- 真实验证结果
- 已知风险
- 下一阶段建议

**当前执行指令：仅执行阶段 0。完成代码审计、生命周期状态机设计和 Trace 数据契约后停止，等待评审，不要直接修改代码。**