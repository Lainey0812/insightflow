# InsightFlow Evaluation Platform — Phase 1-E：Golden Set 约束覆盖审核与最小适配

## 一、任务目标

你是一名资深 AI Agent Evaluation Engineer 和测试架构师。

当前 Phase 1-D 已实现：

- 统一评测数据契约。
- Golden Oracle Evaluator。
- MustForbidEvaluator。
- E2E Hard Gates。
- Manifest 完整性校验。
- 历史运行只读兼容。

但目前 RF-01、RF-02、RF-03、RF-05 的 `must_forbid` 尚未适配，导致新运行即使 Oracle PASS，E2E 仍为 NOT_EVALUATED。

本轮目标是建立**可审计的约束覆盖机制**，解决重复评测与遗漏评测问题。

本任务分为两个阶段：

**Stage A：只读审查。**

先检查全部 Golden 约束和 Oracle 实现，输出逐条覆盖矩阵。此阶段禁止修改代码。

**Stage B：最小实现。**

仅当 Stage A 能提供充分证据时，实施明确可验证的覆盖关系或独立规则。

无法证明覆盖的约束不得强行标记 PASS。

## 二、Stage A：逐条约束审核

读取真实 Golden Set 文件和以下模块：

- `backend/app/evaluation/forbid_rules.py`
- `backend/app/evaluation/must_forbid.py`
- `backend/app/evaluation/evaluators.py`
- `backend/app/evaluation/aggregate.py`
- 相关 Oracle 和 Golden Runner 实现。

对 RF-01～RF-05 的每一条 `must_forbid` 逐项分析：

1. 原始约束文本。
2. 约束的真实业务语义。
3. 属于结果约束、执行过程约束，还是说明性条款。
4. 现有 Oracle 是否真正覆盖。
5. 若 Oracle PASS，该约束是否必然成立。
6. 是否存在 Oracle PASS 但约束违反的反例。
7. 是否需要独立 Evaluator。
8. 实际可用的执行证据。
9. 建议验证方式。

分类：

- `ORACLE_COVERED`：已有 Oracle PASS 可以严格证明该约束满足。
- `INDEPENDENT_CHECK`：需要独立验证。
- `UNSUPPORTED`：目前缺少可执行规则或必要证据。
- `NON_ASSERTION`：说明性文字，不构成独立验收条件。

注意：

不能仅因为两个约束都涉及城市、岗位数量或实习筛选，就认定 Oracle 覆盖。

如果存在 Oracle PASS 但约束违反的可行反例，不能标记 ORACLE_COVERED。

## 三、Stage A 输出

输出完整覆盖矩阵：

| Case | Constraint | 原文 | 分类 | 覆盖 Evaluator | 证据 | 反例 | 结论 |
|---|---|---|---|---|---|---|---|

并明确回答：

1. RF-02、RF-05 的全部必选约束是否能被现有 Oracle 严格覆盖？
2. 哪些约束需要新增独立检查？
3. 哪些约束当前缺乏执行证据？
4. 哪些自然语言描述实际上只是说明，不应成为 Hard Gate？
5. 是否存在 Oracle 逻辑本身未覆盖的业务要求？

## 四、Stage B：最小适配

仅对 Stage A 已经证明的覆盖关系实施适配。

建立版本化 Constraint Coverage Mapping。

至少包含：

- dataset_id
- case_id
- constraint_index
- constraint_text_hash
- verification_mode
- covered_by
- evaluator_version
- coverage_basis
- mapping_version

要求：

- 不修改原始 Golden Set。
- 不使用模糊语义匹配自动认定覆盖。
- 原文哈希变化时映射失效。
- Evaluator 版本变化时必须重新验证覆盖关系。
- Oracle 未 PASS 时不能借覆盖关系产生 PASS。
- 未覆盖的必选约束必须保留 NOT_EVALUATED，或进入独立 Evaluator。
- 映射表及版本写入运行配置哈希。
- 历史运行不回填新的覆盖结果。

对于 `INDEPENDENT_CHECK`，仅实现 MVP 所需的确定性检查。

不要引入 LLM-as-Judge、通用规则 DSL 或复杂规则引擎。

## 五、测试要求

至少覆盖：

1. Oracle PASS 且严格覆盖关系有效 → 对应约束 PASS。
2. Oracle FAIL → 不得通过覆盖映射得到 PASS。
3. Oracle NOT_EVALUATED → 对应约束 NOT_EVALUATED。
4. 覆盖关系原文哈希变化 → 失效。
5. Evaluator 版本不匹配 → 失效。
6. 未适配的必选约束 → NOT_EVALUATED。
7. 说明性条款不构成独立 Hard Gate。
8. 独立检查发现违规 → FAIL。
9. 缺少必需执行证据 → NOT_EVALUATED。
10. RF-04 现有薪资禁止规则不退化。
11. RF-01～RF-05 的 Oracle 预期不改变。
12. 历史文件哈希不变。

特别设计至少一个反例：

**Oracle 数值结果正确，但 Agent 使用了错误筛选条件。**

验证此类执行过程约束不能被错误标记为 ORACLE_COVERED。

## 六、实施边界

允许：

- 新增约束覆盖映射。
- 扩展现有 MustForbidEvaluator。
- 新增必要的确定性约束检查。
- 新增测试。
- 对 Golden Runner 做最小适配。

禁止：

- 修改 Agent、Planner、Engine、HITL。
- 修改 Golden Set 原始文件。
- 修改 Oracle 预期。
- 改写历史评测记录。
- 修改 TC Runner。
- 新增数据库。
- 开发 Admin 页面。
- 开发 Bad Case 回流。
- 引入 LLM-as-Judge。

## 七、交付报告

完成后输出：

1. 全部 `must_forbid` 逐条覆盖矩阵。
2. Oracle 覆盖关系的证明与反例。
3. 新增和修改文件。
4. 覆盖映射的版本与哈希策略。
5. 新增独立检查及其证据来源。
6. RF-01～RF-05 的预期评测行为。
7. 自动化测试结果。
8. 历史数据完整性检查。
9. 尚未覆盖的必选约束及原因。
10. 是否可以进入 Phase 2。

**重要：Stage A 如果发现约束语义存在歧义，或者需要产品决策才能确定验收标准，应停止并提交决策问题，不得自行修改业务验收口径。**

完成后停止，不自动进入 Phase 2。
