# InsightFlow Trace V0.3 实施计划

**项目：** InsightFlow Admin  
**版本：** Trace V0.3  
**设计依据：** REQ-0058 Runtime 节点审计  
**实施原则：** 增量改造、真实埋点、业务无侵入、逐阶段验收

## 一、项目目标

### 1.1 核心目标

建立覆盖完整数据分析任务的统一可观测性体系：

- 一次用户分析任务对应一个稳定的 Workflow Root Run。
- 每个真实执行节点具有明确的执行状态和时间记录。
- LLM 调用、重试、异常能够关联到实际节点。
- HITL 的等待、审批和恢复过程可追踪。
- Analysis Engine 的任务执行和部分失败可追踪。
- Reporting 的现有 Trace 能关联至 Workflow Root Run。
- Admin Run Explorer 展示真实的节点级 Progress。

### 1.2 非目标

本版本不进行以下改造：

- 不重构现有 FastAPI、BackgroundTasks 和业务状态机。
- 不新建通用 Agent Runtime 调度器。
- 不修改 Prompt、模型参数或分析算法。
- 不强制 Engine、Report 改用旧 Node 包装器。
- 不根据历史业务结果伪造 Trace。
- 不引入 WebSocket 或复杂分布式追踪平台。
- 不立即删除已有 Report TraceRun。

## 二、总体架构

### 2.1 目标关系

```text
Session
  └── Workflow Root TraceRun
        ├── Data Profiler Span
        ├── Intent Parser Span
        │     └── LLM Call Records
        ├── Analysis Planner Span
        │     └── LLM Call Records / Retries
        ├── Plan Validator Spans
        ├── HITL Events / Approval
        ├── Analysis Engine Span
        │     └── Task Execution Records
        └── ReportGeneration
              └── Report TraceRun（暂时保留）
                    ├── Evidence Builder
                    ├── Chart Builder（新增）
                    ├── Insight Generator
                    ├── Fact Validator
                    ├── Report Assembler
                    └── Report Persistence
```

### 2.2 核心设计约束

1. Workflow Root Run 代表完整分析任务，不代表一次 HTTP 请求。
2. Session 与 Workflow Root Run 建立稳定关联。
3. 业务状态与 Trace 状态分离，Trace 不参与业务决策。
4. 节点 Span 由真实执行入口创建，不从 Session.status 推断。
5. Report TraceRun 暂时保留，通过显式关联归属 Workflow Root Run。
6. 重试记录属于真实执行 Attempt，不应覆盖之前的失败记录。
7. Trace 写入失败遵循既有 fail-open 策略，但必须可检测和诊断观测缺口。
8. 不允许 Admin 根据节点顺序推断尚未执行节点的真实状态。

## 三、阶段一：V0.3.1 — Root Run 与准备阶段追踪

**优先级：P0**

### 任务 1：扩展 Trace 数据契约

需要实现：

- 新增 `workflow` 类型的 TraceRun。
- 建立 Session 与 Workflow Root Run 的稳定关联。
- 支持报告 TraceRun 与 Workflow Root Run 的父子关联。
- 明确 Run、Span、Event 的 ID 关系。
- 兼容既有 `report_generation` Run 和历史数据。

需要先确定：

- Root Run 在 Session 成功创建后何时创建。
- Root Run 创建失败时如何记录可观测性缺口。
- 同 Session 的澄清、重试和恢复如何复用 Root Run。
- 多请求并发如何避免重复创建 Root Run。
- 历史 Session 无 Trace 时如何显示为未采集，而不是未执行。

**验收标准：**

同一 Session 多次恢复或重试后，仍只对应一个 Workflow Root Run；历史 Report Run 读取不受影响。

### 任务 2：统一 Node Span 生命周期

为真实节点执行入口增加统一的 Trace 边界：

- `span.started`
- `span.finished`
- failed / interrupted 终态
- started_at、finished_at、duration_ms
- error_code、error_message（脱敏）
- operation_id、attempt 信息

首批接入：

1. Data Profiler
2. Intent Parser
3. Analysis Planner
4. Plan Validator（真实调用点分别记录）

注意：

- 不改变 Node.run 的业务返回语义。
- 不把 Validator 返回 F0 自动标记为执行失败。
- 不把 Intent clarify 标记为模型失败。
- 内部 LLM 重试不重复生成主进度条节点。

**验收标准：**

每次真实执行都有可关联的节点 Span；成功、失败和中断能够区分；重复执行不会覆盖之前的执行记录。

### 任务 3：LLM Call 与 Node Span 关联

需要实现：

- Intent Parser CallRecord 关联 Root Run 和 Intent Span。
- Analysis Planner CallRecord 关联 Root Run 和 Planner Span。
- 保留原有 operation_id、call_sequence、retry_index、retry_of_call_id。
- 支持查看 Prompt Template、Request Snapshot、模型协议结果。
- 明确 Provider 请求成功与业务节点成功的区别。

**验收标准：**

能够从 Planner 失败 Span 找到全部真实 LLM Call、超时错误及重试链。

### 任务 4：异常与恢复

需要覆盖：

- LLM timeout
- 模型协议错误
- JSON/Schema 错误
- 节点执行异常
- 服务中断
- Trace 写入失败
- 检查点人工重试

要求：

- 已记录的失败 Attempt 不得被后续成功覆盖。
- 服务中断不能伪造 finished_at 或实际执行耗时。
- 恢复后的执行与原 Root Run 保持关联。
- Trace 缺失时明确标记观测不完整。

### V0.3.1 验收场景

使用真实 CSV 和真实前台分析流程，重点验证：

**场景 A：正常准备流程**

Data Profiler → Intent Parser → Analysis Planner → Plan Validator 的真实 Span 可查询。

**场景 B：Planner 超时**

Planner Span 失败；能找到真实 CallRecord 和错误原因；下游没有虚假成功记录。

**场景 C：Intent 澄清**

Intent 返回 clarify，Session 进入等待；提交澄清后重新执行 Intent，历史记录保留。

**场景 D：准备阶段重试**

同一 Root Run，新增真实 Attempt，不覆盖先前失败。

**阶段交付物：**

- Trace 数据契约及迁移
- 准备阶段真实 Span
- LLM Call 关联
- 自动化测试
- 真实前台验证报告

---

## 四、阶段二：V0.3.2 — HITL 与 Analysis Engine

**优先级：P1**

### 任务 5：HITL 生命周期追踪

记录真实业务动作：

- 进入等待审批
- 计划版本修订
- 修订后重新校验
- 审批成功
- 审批拒绝或冲突
- 审批后恢复执行

需要区分：

- `waiting_input`：等待用户澄清
- `waiting_approval`：等待用户审批
- `failed`：真实执行异常
- `rejected`：业务规则拒绝，不必然是系统异常

HITL 等待应表现为持续的业务等待状态，不应把等待时长计入 LLM 或计算耗时。

### 任务 6：Analysis Engine 追踪

在真实 AnalysisEngineService 入口接入：

- 执行前置校验
- DatasetLoader
- Execution claim
- TaskRunner
- Task Result Persistence
- Execution finish

建议主 Progress 只展示一个 Analysis Engine 节点。

Node Inspector 中展开：

- task_id
- task.status
- 操作步骤与真实结果
- 执行耗时
- 失败原因
- ExecutionResult.execution_status

必须保留 success、partial_success、failed 的真实业务语义。

### V0.3.2 验收场景

- 正常审批后执行成功。
- 删除任务、创建新计划版本后重新审批。
- 审批版本冲突，不生成虚假成功 Span。
- 多任务部分成功。
- 任务跳过。
- Engine 中断恢复。
- 重复 execution_request_id 不产生虚假执行。

**阶段交付物：**

- HITL Trace 事件
- Engine Node Span
- Task 诊断数据
- 真实执行验证报告

---

## 五、阶段三：V0.3.3 — Reporting 关联与 Admin Progress

**优先级：P1**

### 任务 7：Reporting 关联

保留现有 Report TraceRun。

新增：

- workflow_run_id 关联
- report_generation_id / attempt 关联
- Chart Builder Span
- 报告重试归属
- Root Run 与报告结果的状态聚合

需要保持：

- 现有五个 Report Span 的行为
- 原有 RunManifest
- ReportGeneration 业务状态
- Report Retry 机制
- 已有 Admin Trace Detail 查询兼容

### 任务 8：Admin Run Explorer

每条分析任务展示一条节点级 Progress：

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

状态颜色：

- 灰色：未执行 / 跳过（用图标进一步区分）
- 蓝色：执行中
- 绿色：执行成功
- 黄色：等待澄清 / 审批
- 红色：执行失败 / 中断（用标签区分）

点击节点进入 Node Inspector。

主进度条显示逻辑节点的当前执行情况；详情保留多次执行、重试、失败和恢复历史。

### 任务 9：Node Inspector

展示：

- Node ID / Node Name
- 当前执行状态
- 执行时间和耗时
- Attempt 历史
- 关联的 LLM Call
- Prompt Template / Request Snapshot
- 输入输出的受控投影
- Error Code / Error Message
- 业务结果与校验结果

权限、脱敏和大小限制沿用已有安全策略。

### 任务 10：实时更新

V0.3 不引入 WebSocket。

采用轮询：

- Run Explorer：活动任务约 5–10 秒刷新。
- Trace Detail：活动任务约 2–3 秒刷新。
- 终态任务停止自动轮询。
- 接口失败时显示数据暂不可用，不修改节点状态。

### V0.3.3 验收场景

- 一条分析任务展示完整节点链路。
- Planner 失败时准确定位失败节点。
- HITL 等待显示黄色。
- Engine 部分成功显示真实业务结果。
- Insight Generator 重试能查看对应 Call。
- Fact Validator 部分拒绝不被误标为系统失败。
- Report Retry 能关联原始 Workflow Run。
- 历史无 Trace 任务明确显示未采集。
- 不存在根据流程顺序伪造成功节点。

**阶段交付物：**

- Reporting Root Run 关联
- 节点级 Progress
- Node Inspector
- 自动轮询
- 全链路真实验收报告

---

## 六、质量与安全要求

每个阶段都必须满足：

1. 保持既有业务接口兼容。
2. 不改变实际分析结果和审批决策。
3. 不修改模型参数与 Prompt。
4. Trace 失败不能阻断正常业务流程。
5. 不记录未经授权的完整敏感数据。
6. 所有新增数据库结构提供兼容迁移方案。
7. 单元、集成、回归测试通过。
8. 对异常、中断、重试、幂等进行专项测试。
9. 不把测试模拟结果当作真实运行验收。
10. 每阶段提交代码变更清单、测试结果和已知限制。

## 七、实施顺序与验收门槛

| 阶段 | 优先级 | 进入下一阶段的条件 |
|---|---|---|
| V0.3.1 | P0 | Root Run、准备节点、Planner 超时与 LLM 关联真实验证通过 |
| V0.3.2 | P1 | HITL、Engine 真实执行及异常路径验证通过 |
| V0.3.3 | P1 | 全链路节点 Progress 与 Report Trace 关联验证通过 |

**执行要求：先完成 V0.3.1，不得直接跳到 UI 开发。每阶段完成后先提交验收结果，确认通过再进入下一阶段。**