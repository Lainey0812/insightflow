# InsightFlow Evaluation Platform — Phase 1-C 集成验收

## 任务目标

你是一名资深 AI Agent Evaluation Engineer 和软件测试架构师。

Phase 1-B 已完成统一数据契约、Evaluator Protocol、E2E Hard Gates、Golden/TC 兼容适配、Manifest 持久化和指标函数。

本轮任务是验证这些模块是否真正形成可运行的闭环，并调查现有回归测试失败的原因。

**本轮为验证任务，不修改任何生产代码、业务逻辑、测试断言或历史运行数据。**

允许在临时目录中运行测试、生成验证产物，并输出验收报告。禁止调用真实 LLM。

## 一、端到端集成验收

使用脚本化的 `run_one` 或等价 Mock，完整执行：

Golden Runner → Case Execution → Evaluator → E2E Aggregation → Manifest → read_run() → Metrics

验证：

1. Runner 实际调用新的 Evaluator，而非绕过它直接使用旧评分结果。
2. 每个 Case Execution 都有独立状态和评分结果。
3. `run-config.json` 在执行前生成。
4. `run-manifest.json` 在完成后生成。
5. Manifest 中的文件哈希与实际文件一致。
6. `read_run()` 能完整读取新运行。
7. Metrics 能根据读取结果计算，不依赖原始脚本中的临时变量。
8. 运行中断时能够识别 INCOMPLETE，不能误报 FINISHED。

至少覆盖一次正常完成和一次中断运行。

## 二、Hard Gates 与必选约束验证

重点检查 RF-04 的 `must_forbid`。

验证以下场景：

- Oracle PASS，必选禁止规则 PASS → E2E PASS。
- Oracle PASS，必选禁止规则 FAIL → E2E FAIL。
- Oracle PASS，必选禁止规则 NOT_EVALUATED → E2E NOT_EVALUATED。
- Oracle PASS，必选禁止规则 EVALUATOR_ERROR → E2E EVALUATOR_ERROR。
- Agent 执行 FAILED，Oracle NOT_EVALUATED → E2E FAIL。
- 可选 Evaluator EVALUATOR_ERROR → 不改变 E2E 业务判定。

必须核实实际代码是否将 RF-04 的禁止薪资分析约束注册为必选检查。

**禁止仅凭 `must_forbid` 字段存在，就声称该规则已被执行。**

如果现有实现无法真正验证禁止规则，明确标记为验收缺口，不允许通过修改测试断言掩盖问题。

## 三、历史兼容与数据保护

验证历史 Golden Run：

`gf_20261112-143406_cde1fd`

预期：

- RF-01、RF-03：BLOCKED / Oracle NOT_EVALUATED / E2E FAIL。
- RF-04：FAILED / Oracle NOT_EVALUATED / E2E FAIL。
- RF-02、RF-05：COMPLETED / Oracle PASS / E2E PASS。

原始失败标签仍保留在 legacy 字段。

重新核对历史文件 SHA-256，确认无变化。

如果实际历史文件不存在，不得生成同名假数据代替。

## 四、回归测试归因

调查 Phase 1-B 报告中的失败：

后端：

`test_failure_diagnosis.py::test_success_has_no_failure...`

Admin：

- Trace 相关 9 个失败。
- Comparison 相关 1 个失败。

要求：

1. 记录失败断言、实际输出和对应源码。
2. 使用 Git 历史、修改前副本或其他可信证据确认是否为历史问题。
3. 区分以下结论：
   - PRE_EXISTING
   - INTRODUCED_BY_PHASE_1B
   - INDETERMINATE
4. 不得仅因为失败模块没有直接 import 新代码，就认定与本次修改无关。
5. 不修改测试断言，也不顺手修复历史问题。

如果无法可靠复现修改前环境，必须标记 INDETERMINATE。

## 五、验收报告

请输出：

### 1. 总体结论

- PASS
- CONDITIONAL_PASS
- FAIL

### 2. 集成链路检查

逐项列出实际运行的验证、结果、证据文件和测试命令。

### 3. RF-04 必选规则检查

明确回答：

- 是否存在可执行的 must_forbid 检查？
- 是否被注册为必选 Evaluator？
- 是否能阻止错误的 E2E PASS？
- 如果不能，最小修复范围是什么？

### 4. 回归测试归因

列出每类失败的具体原因、证据和归因结论。

### 5. 数据完整性

记录历史文件哈希检查结果、Manifest 完整性检查结果。

### 6. 未解决问题

区分：

- 阻塞 Phase 2 的问题。
- 可以延后处理的技术债。

### 7. 下一步建议

明确是否可以进入 Phase 2。

如果存在阻塞项，给出最小修复建议，但不要自行修改代码。

**完成报告后停止，等待确认。**
