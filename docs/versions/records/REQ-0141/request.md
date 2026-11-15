# InsightFlow Evaluation Platform — Phase 1-B 实施任务

## 角色与目标

你是一名资深 AI Agent Evaluation Engineer、Python 后端架构师。

基于现有 InsightFlow 仓库及 Phase 1-A 技术设计，实施统一评测数据契约和兼容适配层。

核心目标：

1. 统一 Golden Set 与 TC Regression 的基础数据结构。
2. 区分 Agent 执行状态、Evaluator 判定状态和 E2E 任务结果。
3. 支持可插拔 Evaluator。
4. 保证历史评测数据不可被改写。
5. 为后续 Admin、Bad Case、Regression Comparison 提供统一数据基础。

**本任务要求真实代码实现、自动化测试及验证报告，不接受仅提供设计文档。**

## 一、实施前检查

首先检查实际仓库结构，确认：

- Golden Runner 和 `score_case` 的实现。
- TC Regression Runner 与评分逻辑。
- Golden 和 TC 运行结果的实际 JSON Schema。
- 现有 Trace 和 Prompt Snapshot 的记录方式。
- 现有测试和运行目录隔离机制。

如发现 Phase 1-A 与实际源码不一致，以真实源码为准，并在最终报告中说明。

## 二、统一数据契约

实现以下核心对象：

### EvaluationRun

包含 Run ID、Agent ID/Version、Dataset ID/Version/Hash、Evaluator Manifest、运行配置、运行状态和 Case Execution 引用。

### CaseExecution

包含 Execution ID、Run ID、Case ID、Attempt、Execution Status、Workflow ID、执行时间、执行记录引用、最终业务输出引用、Trace 引用、Error Code 和 Blocking Stage。

Execution Status 至少支持：

- PENDING
- RUNNING
- WAITING_APPROVAL
- COMPLETED
- BLOCKED
- FAILED
- TIMEOUT
- CANCELLED

明确终态与非终态，不能将正常等待人工审批直接解释成 Agent 崩溃。

历史字段缺失时保留 null，并记录数据来源。

### EvaluatorResult

包含 Evaluator ID/Version、配置哈希、执行引用、评测范围、Verdict、可选 Score、Failure Code、Reason、Evidence References。

Verdict：

- PASS
- FAIL
- NOT_EVALUATED
- EVALUATOR_ERROR

Evaluator 自身异常不得归因为 Agent 业务失败。

### E2E Summary

采用 Hard Gates 聚合。

必须明确：

- Agent 执行失败与 Oracle 未评判可以同时存在。
- 必选 Evaluator 失败时 E2E FAIL。
- 必选 Evaluator 无法评判时不得 E2E PASS。
- 非必选 Evaluator 的错误不应自动导致 E2E FAIL。
- 仅当任务完成条件满足且所有必选检查 PASS 时，才允许 E2E PASS。
- 若业务用例明确规定阻断即正确，按该用例的预期行为判定。

对评测基础设施异常和业务失败保留不同结果。

## 三、Evaluator 接口

实现最小 Python Protocol 或 ABC：

- `evaluator_id`
- `evaluator_version`
- `scope`
- `applicable()`
- `evaluate()`

接口不直接依赖 InsightFlow 专用的 Planner、Engine 或 Workflow 类型。

首先适配现有 Golden Oracle。

保留现有 Oracle 规则，不修改 RF-01～RF-05 的预期结果。

无 Engine 最终结果时，Oracle 必须返回 `NOT_EVALUATED`，不得生成新的 `F-GOAL-SUBSTITUTED`。

现有节点级评分器可以提供适配层，但不得影响 E2E 的最终判定。

## 四、历史兼容

实现 Golden 和 TC 两套只读适配器。

必须遵守：

1. 历史原始结果放在 `legacy`。
2. 新的解释性状态放在 `projection`。
3. 每个推导状态记录依据和来源。
4. 证据不足时返回 null/UNKNOWN，不得猜测。
5. 不用当前源码常量回填历史 Evaluator Version。
6. 不从模型名或 Prompt Snapshot 推断 Agent Version。
7. 不改写任何历史 `summary.json`、`run.json`、`result.json` 或 Trace。

特别验证：

- RF-01、RF-03：历史 Trace 显示等待审批，投影为 BLOCKED，Oracle NOT_EVALUATED，E2E FAIL。
- RF-04：Planner 业务校验失败，投影为 FAILED，Oracle NOT_EVALUATED，E2E FAIL。
- RF-02、RF-05：COMPLETED，Oracle PASS，E2E PASS。

原始失败标签必须保留。

## 五、Manifest 持久化

继续使用现有独立文件目录，不引入 SQLite 迁移。

采用两阶段不可覆盖写入：

### Run Config Snapshot

在运行开始前写入，包含：

- Run ID
- Schema Version
- Dataset ID/Version/Hash
- Evaluator ID/Version/Config Hash
- Agent ID/Version
- Model 配置
- 环境标识
- 运行策略
- 创建时间

### Run Final Manifest

在运行结束后写入，包含：

- Run ID
- Config Snapshot 引用和哈希
- 执行结果文件引用
- Trace 引用
- 实际观察到的 Prompt Snapshot
- 完成状态
- 完成时间

使用原子写入与禁止覆盖策略。

如果运行中断，应保留启动配置，读取端能够识别不完整运行。

不要把 Final Manifest 写成必须在运行中不断修改的文件。

## 六、统一评测指标

实现或定义可复用的纯函数，至少支持：

- E2E 确认成功率：PASS / 全部有效且已启动用例。
- 可判定样本通过率：PASS / (PASS + FAIL)。
- 评测覆盖率：(PASS + FAIL) / 全部有效且已启动用例。
- 执行完成率。
- 已执行结果正确率。
- 阻断率。
- 运行失败率。
- Evaluator 错误率。

分母为零时返回 null，不得返回虚假的 100%。

未启动用例单独统计，不得混入已执行分母。

## 七、测试与验收

至少覆盖：

1. RF-01～RF-05 的历史兼容投影。
2. 未执行用例不再产生新的错误业务标签。
3. 必选检查 NOT_EVALUATED 时 E2E 不得 PASS。
4. 必选检查 FAIL 时 E2E FAIL。
5. Evaluator 抛错时记录 EVALUATOR_ERROR。
6. 可选 Evaluator 抛错不污染 E2E 业务结果。
7. 缺少 Trace 时不伪造 BLOCKED。
8. 新运行包含 Config Snapshot 和 Final Manifest。
9. 中断运行保留 Config Snapshot。
10. 历史文件 SHA-256 前后完全一致。
11. Golden 与 TC 可以通过统一接口读取。
12. 原有 TC 回归和 Admin Trace 测试继续通过。

测试优先使用 Mock、Fixture 和临时目录，不调用真实 LLM，不写入历史评测目录。

## 八、严格范围控制

本轮允许：

- 新增统一契约。
- 新增 Evaluator Protocol。
- 新增 Golden / TC 兼容适配器。
- 新增 Manifest 写入。
- 对 Golden Runner 做必要的最小集成。
- 新增聚合逻辑、指标纯函数和测试。

本轮禁止：

- 修改 Agent 业务逻辑。
- 修改 Planner、Engine、HITL 审批规则。
- 修改 Golden Set 或 Oracle 预期。
- 改写历史评测结果。
- 修改 TC Runner 的执行与超时行为。
- 新增数据库迁移。
- 开发 Admin 页面。
- 开发 Bad Case 回流。
- 引入 LLM-as-Judge。
- 实现第二种 Agent。

## 九、交付报告

完成后提供：

1. 实际新增和修改的文件清单。
2. 核心数据契约与接口。
3. 新旧运行记录的映射方式。
4. E2E Hard Gates 规则。
5. Manifest 写入与中断恢复行为。
6. 测试命令、测试数量和实际结果。
7. 历史文件未改变的验证证据。
8. 已知限制与下一阶段依赖。

如果某项要求无法在当前仓库安全实现，不得伪造完成。说明阻碍、影响和建议替代方案。

**验收完成后停止，不自动进入 Phase 2。**
