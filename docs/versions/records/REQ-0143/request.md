# InsightFlow Evaluation Platform — Phase 1-D 质量门禁与证据完整性修复

## 任务目标

基于 Phase 1-C 的验收结果，修复两个已确认缺口：

1. RF-04 的 `must_forbid` 没有作为独立必选 Evaluator 执行，导致证据缺失时可能错误地判定 E2E PASS。
2. `read_run()` 只校验 Config Hash，没有校验 Manifest 记录的全部结果文件哈希，导致被修改的评测结果仍被视为可信。

本轮要求完成代码实现、自动化测试和集成验收。

严格控制范围，不修改 Agent、Planner、Engine、HITL、历史 Golden Set 或 TC Runner。

## 一、实现 MustForbidEvaluator

新增独立 Evaluator，例如：

`insightflow.golden.must_forbid`

要求：

- 遵循现有 Evaluator Protocol。
- 支持通用的结构化禁止规则，不根据 `case_id` 写死业务逻辑。
- 对有禁止规则的用例注册为必选 Evaluator。
- 对没有禁止规则的用例不强制执行。
- 不修改现有 Golden Set 文件。
- 对 RF-04 使用经过明确验证的规则适配。
- 保留规则来源和原始约束引用。

至少支持：

- 禁止使用指定字段。
- 检查实际执行计划中使用的字段。
- 检查 Engine 实际执行的字段。
- 检查最终结果列名。

字段匹配必须基于明确的字段引用、规范化字段名或经过验证的别名，不能仅凭普通自然语言中出现「薪资」两个字就认定违规。

### 判定规则

**PASS**

所有必需证据完整，且没有发现禁止字段使用。

**FAIL**

在可信执行证据中发现禁止字段被使用。

即使字段不在 Dataset Profile 中，只要计划或实际执行记录明确引用该禁止字段，也应判 FAIL。

**NOT_EVALUATED**

缺少完成判定所必需的 Plan、Engine 或结果证据，无法证明没有违规。

**EVALUATOR_ERROR**

Evaluator 自身发生异常。

Evaluator 的异常不能被记录为 Agent 的业务失败。

### 规则适配

现有 Golden Set 的 `must_forbid` 可能是自然语言。

不得默认将所有自然语言规则解析为可执行规则。

MVP 允许在代码中维护显式、版本化的规则适配配置，但必须：

- 与原始约束建立引用关系。
- 记录适配规则版本与配置哈希。
- 不修改 Golden Set。
- 不静默忽略无法适配的必选规则。

如果无法适配，应返回 NOT_EVALUATED，而不是 PASS。

## 二、修正 Golden Evaluator 注册

调整默认 Evaluator 注册逻辑：

- Oracle：必选。
- MustForbid：对适用用例必选。
- Node Fidelity：可选。

从 Oracle 中移除 RF-04 专属的禁止薪资检查，避免重复评分。

保持原有城市计数 Oracle 逻辑不变。

必须保证新运行不会因为缺少禁止规则证据而得到错误的 E2E PASS。

## 三、Manifest 完整性校验

扩展 `read_run()`：

- 校验 Config Snapshot Hash。
- 校验 Summary Hash。
- 校验每个 Case Result Hash。
- 校验每个 Trace Hash。
- 校验 Manifest 中声明的其他必需产物。

设计独立的完整性状态：

- VERIFIED
- INVALID
- INCOMPLETE
- UNVERIFIED

不要把证据完整性与 Agent 执行状态混为一谈。

要求：

1. 任一必需文件缺失或哈希不一致，不能返回 VERIFIED。
2. Manifest 中引用的路径必须限制在对应 Run 目录内，防止路径穿越。
3. 历史没有 Manifest 的运行标记 UNVERIFIED，而不是伪造 VERIFIED。
4. 不覆盖历史文件。
5. 不自动修复哈希不一致。
6. 文件损坏不得静默改变原始评分结论。

如果证据完整性为 INVALID，相关结果不能直接参与可信质量统计，应显式标记或排除，并说明原因。

## 四、测试要求

### MustForbidEvaluator

至少覆盖：

1. Oracle PASS，禁止规则 PASS → E2E PASS。
2. Oracle PASS，禁止规则 FAIL → E2E FAIL。
3. Oracle PASS，禁止规则 NOT_EVALUATED → E2E NOT_EVALUATED。
4. Oracle PASS，禁止规则 EVALUATOR_ERROR → E2E EVALUATOR_ERROR。
5. 计划引用禁止字段，但 Dataset Profile 不包含该字段 → FAIL。
6. Engine 实际使用禁止字段 → FAIL。
7. 最终结果包含禁止字段 → FAIL。
8. 缺少必要 Plan / Engine 证据 → NOT_EVALUATED。
9. 无禁止规则的用例不被错误阻断。
10. 未适配的自然语言必选规则不能默认为 PASS。

### Manifest

至少覆盖：

1. 完整文件 → VERIFIED。
2. Result 文件被修改 → INVALID。
3. Trace 文件被修改 → INVALID。
4. Summary 文件被修改 → INVALID。
5. 必需文件缺失 → INVALID 或 INCOMPLETE，依据明确定义。
6. 历史无 Manifest → UNVERIFIED。
7. Manifest 引用目录外路径 → INVALID。
8. 运行中断、尚未写入 Final Manifest → INCOMPLETE。
9. 不影响现有历史只读投影。

## 五、集成验收

重新执行 Phase 1-C 验收流程。

注意：原验收脚本的旧预期可能与修复后的正确行为冲突。

允许在新的验证脚本中更新预期，但不得修改或删除旧验收记录，也不得为了通过测试而放宽正确性要求。

所有验证产物写入新的独立目录。

禁止调用真实 LLM。

验证：

- RF-04 计数正确但缺少禁止规则证据时，不再 E2E PASS。
- RF-04 计数正确且证据完整、没有违规时，可以 E2E PASS。
- RF-04 发生禁止字段使用时，E2E FAIL。
- Manifest 文件被篡改后，不再 VERIFIED。
- 历史文件哈希保持不变。
- 原有 Golden / TC 兼容读取能力不退化。

## 六、严格禁止

- 不修改 Agent 业务逻辑。
- 不修改 Planner、Engine、HITL。
- 不修改 Golden Set 原始文件和 Oracle 预期。
- 不覆盖历史运行。
- 不修改 TC Runner。
- 不新增数据库迁移。
- 不开发 Admin 页面。
- 不开发 Bad Case 自动回流。
- 不引入 LLM-as-Judge。
- 不修复无关的历史红测试。

## 七、交付报告

请输出：

1. 实际修改文件清单。
2. MustForbidEvaluator 的规则结构、证据来源和判定逻辑。
3. Evaluator 注册与 Hard Gates 的实际行为。
4. Manifest 完整性校验实现。
5. 新增测试及实际结果。
6. Phase 1-C 关键验收项复测结果。
7. 历史数据哈希检查。
8. 是否仍存在阻塞 Phase 2 的问题。

完成后停止，不自动进入 Phase 2。
