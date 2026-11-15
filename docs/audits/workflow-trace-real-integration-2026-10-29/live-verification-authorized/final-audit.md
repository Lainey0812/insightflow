# Trace V0.3 真实前台接入审计：授权后的实测结论

日期：2026-10-29。需求：REQ-0056；真实链路数据发送授权：REQ-0057。

**结论：已完成真实前台触发和持久化核对；当前系统未通过完整工作流 Trace 验收。前台任务真实运行、澄清和失败，但 Admin 追踪不到报告之前的过程。**

本轮没有开发 UI、调整模型参数、修改 Prompt 或业务代码，也没有使用 Mock 模型返回。29 个相关源码文件的 SHA-256 与第一阶段一致。

## 一、实际验证结果

| 项目 | 真实结果 |
|---|---|
| 文件 | 用户提供的 insightflow_sales_orders_test.csv，60 行、12 列 |
| 模型 | 现有阿里云 OpenAI-compatible 服务，qwen3.8-flash |
| 前台分析任务 | 新建 2 个真实 Session |
| 外部模型实际调用 | 7 次：Intent 4 次，Planner 3 次，Insight Generator 0 次 |
| Provider 协议完成 | 4 次；其中有 1 次 Intent 输出触发 grounding 重试，不等于 4 次业务解析都一次成功 |
| Planner 调用 | 3 次均在约 30 秒时被总超时取消 |
| Admin Trace SQLite | Run 0、Span 0、Event 0 |
| 审批 / Engine / 报告 | 未到达；无批准计划、无执行记录、无报告；未构造假结果补齐链路 |
| 刷新恢复 | 前台重新加载后仍显示相同任务与真实超时错误；Admin 手动刷新仍为空 |

真实数据库基线原有 1 个 Session、0 Run、0 LLMCall。新增两条任务及 7 条模型记录均由本轮前台操作产生。业务记录、Prompt Registry 和只读 Admin 响应交叉核对一致。

## 二、案例 A：澄清 → 恢复 → 规划失败 → 检查点重试

Session：`7e88aba7721f4bd9bac25a32f0891ae2`。

1. 浏览器前台选择实际 CSV，输入“帮我处理一下。”，点击发送。
2. Data Profiler 从真实文件生成 60 行、12 列画像；Intent 模型返回澄清问题，Session 进入 WAITING_FOR_CLARIFICATION。
3. 此时 Admin /runs 返回 200、total=0；数据库也无 Run。不是请求失败，也没有产生上游成功 Span。
4. 在同一前台会话补充：“帮我分析 2026 年华东地区已完成订单的销售额，按照城市汇总并降序排名，取前三名。”
5. Intent 第二次解析发生 1 次真实内部重试，最后 next_action=proceed，继续 Planner。
6. Planner 超时，Session.error=LLM_TIMEOUT、retryable=true；NodeRun 保留 analysis_planner_v1/error，Admin 仍没有失败 Run。
7. 点击既有“重试准备”，同一 Session 从检查点再次进入 PLANNING，没有重复画像或 Intent；再次超时。旧 NodeRun 未删除。

业务数据库中保存的状态顺序：

```
CREATED → PROFILING → PARSING_INTENT → WAITING_FOR_CLARIFICATION
→ PARSING_INTENT → PLANNING → FAILED → PLANNING → FAILED
```

这是原应用 WorkflowEvent，不是补写的 TraceEvent。实时只读观察有界采样可能错过极短状态；observed-timeline.json 对观察快照和真实业务事件分开保存。

## 三、案例 B：简单统计对照

Session：`a762b2e69f0a41b88dffc1ad929b6423`。

另建新分析，上传同一文件并输入“按城市统计订单数量。”，排除复杂多条件需求为唯一触发因素的可能。

- 真实 Profiler 完成，Intent 一次返回 proceed。
- Planner 仍在约 30 秒时超时。
- 状态顺序为 CREATED → PROFILING → PARSING_INTENT → PLANNING → FAILED。
- 刷新页面后仍可恢复该任务、目标、画像及“规划调用超过总时间限制”错误。
- 没有进入 HITL，不存在未经批准执行。

## 四、真实重试与 ID 关联证据

### Intent 内部重试保留了独立 Attempt

同 operation_id：`0ab79af3ad6742538cb9357e8bae3b79`。

| 调用 | call_sequence / retry_index | 结果与关系 |
|---|---|---|
| call_036df2dac39a42679fc7311b05740d7e | 1 / 0 | Provider succeeded，随后业务 grounding 校验失败 |
| call_d36b8b048c294d7ab76ababae57ac2e1 | 2 / 1 | retry_of_call_id 指向前次；retry_reason=LLM_UNGROUNDED_OUTPUT；最后解析可继续 |

两条 CallRecord 都没有 run_id/span_id。这证明：调用级重试有真实记录，但不等于已接入 Workflow Trace。

### Planner 手动检查点重试缺少跨尝试 Trace 关联

- 第一次 operation_id：`e9c22a5690c14e26b2e0963302cccb4b`。
- 用户重试后 operation_id：`19755ca4abf94c659989e78766f6bc86`。
- 简单对照 operation_id：`1e7a5a29f7f5478eacf1412173d4c143`。

均是新的 sequence=1/retry_index=0，retry_of_call_id=null，run_id/span_id=null。前两次可通过业务 Session 的错误节点记录人工核对，但没有结构化根 Run 或统一节点 Attempt 链。

最后一次 Planner Call：`call_07d205ee6d414863b14e80317218bba7`。可在本地 Admin `/prompts/calls/call_07d205ee6d414863b14e80317218bba7` 查看实际调用元信息。

### 错误语义必须分层

业务 Session 保存 LLM_TIMEOUT；Provider Call 保存 cancelled / LLM_CALL_CANCELLED，因为服务层总超时取消了底层请求。两者是不同层级，不应替换成同一个“模型成功/失败”。同样，Provider succeeded 不代表后续 Schema 或语义校验成功。

## 五、四阶段覆盖的实测与静态边界

| 阶段 | 本轮实际到达 | 实际持久化 | Admin Trace |
|---|---|---|---|
| Understanding | 两次画像、一次澄清、一次恢复、三个 Intent 解析过程 | 画像、Intent 历史、业务事件、4 条 CallRecord | 无 Span/Event |
| Planning | 3 次 Planner 调用，均超时 | 3 条取消 CallRecord、3 条错误 NodeRun、Session 错误 | 无 Run/Span/Event |
| HITL / Validator 完成后审核 | 未到达 | 无本轮批准计划 | 不得标成功 |
| Execution | 未到达 | 无本轮 ExecutionResult | 不得标成功 |
| Reporting | 未到达 | 无本轮 AnalysisReport 或报告调用 | 本轮不能宣称已实时验证报告 Trace |

完整服务入口、报告阶段五个已有 Span、Manifest/Registry 绑定与生命周期的静态审计见上级 static-audit-v1.md。报告阶段现有自动化测试不替代本次真实模型验收。

## 六、当前真实链路与根 Run 判断

本次实际路径：

```
前台 POST /sessions(real_workflow=true)
→ 保存 CSV 和 Session
→ prepare_real → Data Profiler
→ Intent（可澄清，补充后在同 Session 恢复）
→ Planner → 30 秒超时 → Session FAILED
```

尚未到达的代码路径为：Planner 成功后确定性验证 → 保存不可变计划 → HITL → Engine → ReportWorkflow.enqueue → 报告 Run。**因为根 Run 建立时机在报告排队，当前流程在这之前失败就完全不会出现在 Admin Run Explorer。**

session_id 有贯穿业务过程的真实关联，但不是 Trace 根 Run。NodeInput.run_id 是每次节点调用的新 UUID，不等于 TraceRun.run_id。不能把最终报告、相似输入、Session 状态差值转换成没有发生过的节点事件。

## 七、本轮确认的 Bad Case 与优先级

### P0：上游真实失败对 Admin 不可见

证据：两 Session、7 实际调用、3 Planner 超时；Admin /runs 与 Trace SQLite 都为零。应在真实任务开始时建立同一套 Trace 的根 Run，而不是等报告排队。

### P0：实际 Planner 可用性阻塞

复杂需求及单一统计需求都超时。持久化请求显示 timeout=30，Planner 未显式发送 enable_thinking；Intent 显式发送 false。**这只能确认实际配置差异，不能据此断言供应商默认思考模式就是超时根因。**本轮不更改参数求通过；后续应独立检查模型响应耗时、有效模型参数及超时策略。

### P1：重试关联与消费者校验状态缺口

Intent 内部重试有准确链；用户触发 Planner 重试是新 operation_id，缺少根运行和节点重试关联。协议成功但 grounding 失败的情况已有真实实例，不能把 Call succeeded 直接显示成节点业务成功。

### P2：空状态文案误导

API 已接通且返回真实空数组，页面仍同时显示“数据接口尚未接入”。来源是 admin/src/components/EmptyState.tsx 的默认 statusLabel，TracesPage 没有覆盖。它没有伪造成功，但会让用户混淆“没有采集记录”和“API 未连接”。本轮仅记录，不修改 UI。

## 八、最小改造方案与测试顺序

1. **先补根关联及真实服务埋点。**复用 TraceRepository；对旧 report_generation kind 向后兼容扩展。不要为上传/HITL 等待填写虚构 execution_id，不修改旧 Manifest。
2. **把 Session、澄清、HITL、调用和执行绑定到同一根。**各次尝试有稳定 node_key、node_attempt、真实 pause/resume/failed 事件；Report Run 是可关联的子尝试。
3. **先覆盖失败路径再验证成功链。**上传、Intent、Planner 在失败时也必须已有 Run；Provider 协议与消费者校验分开记录；保持观测 fail-open、请求快照 fail-closed 的原边界。
4. **独立排查 Planner 超时。**不在 Trace 审计中偷偷调整模型或 Prompt；故障解决后再执行原销售 Top 3 和简单统计对照。
5. **后续再接入活跃状态刷新。**当前 Admin 为手动刷新；不通过前端计时或推测生成状态。

后续验收应覆盖：正常 CSV/XLSX、澄清恢复、审批等待/刷新/重启、任务删除与旧审批拒绝、F0/F1/partial、无证据跳过、协议成功但语义失败、节点重试/报告重试、并发隔离、观测故障、异常退出和历史缺失。详细检查点沿用上级静态审计测试表。

## 九、计算基准和未完成事项

独立 Pandas 仅用于预先建立核对基准：

- 原销售问题：筛选后 16 条；济南 21,250、南京 20,250、上海 5,760，前三名合计 47,260。
- 简单对照：60 条，10 个城市，每城 6 条订单。

**它们不是 Analysis Engine 本次执行结果。**没有将这些值写回执行表、报告或 UI。因 Planner 未产生可审批计划，当前无法完成 Engine 数值对照、Report Trace 实时观察和服务异常退出的真实端到端验证；未把未到达节点标为失败或成功。

## 十、记录与验证资料

- sessions-projected.json：两 Session 的业务事件、Intent 历史和错误节点，排除原始表格样本及访问凭证。
- llm-call-metadata.json：7 条实际 CallRecord 与请求快照元信息；不导出原始消息、API Key 或完整 CSV。
- observations.jsonl / observed-timeline.json：只读实时观察到的变化，明确它们不是应用 TraceEvent。
- planner-timeout-persisted.json：第一次超时的中间状态，后续重试没有覆盖本文件。
- admin-before-approval.json / admin-final-api.json：真实只读 API 的响应与版本调用列表。
- independent-pandas*.json：独立计算基准，无应用内核参与。
- source-unchanged.json：29 个文件内容未变。
- 截图：01 澄清、02 Admin 空列表、03 首次超时、04 重试超时、05 简单任务刷新后失败、06 Admin 仍无 Run。
- 第一阶段原有相关自动化测试 126 passed；本轮没有源码改动，未重复跑相同套件。自动化测试为脚本化传输，不算真实模型成功证据。

第一阶段“待授权”文档和自动审批拒绝原记录继续保留，属于当时状态。本轮授权后已实际提交；它们不表示当前仍有权限阻塞。
