# evaluation-constraint-coverage-v1（Phase 1-E Stage B）

- 需求：REQ-0144（任务书），REQ-0145（Stage A 决策确认 D1–D4）。
- Stage A 审核：`docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/REVIEW.md`。
- Stage B 验收证据：`docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/stage-b/`。
- 修改前副本：`before/`（must_forbid.py、forbid_rules.py、golden_run.py、两份测试文件）。

## 新增文件

- `backend/app/evaluation/constraint_coverage.py`：版本化 Constraint Coverage Mapping（`golden-constraint-coverage-v1`），以及守卫 `unique-oracle-labels`、`mapping_sha256()`、`resolve()`。
- `backend/app/evaluation/row_set.py`：用 `CapabilityRegistry` 注册的同一批内核，在固定的 Golden 行上重放已完成任务，得出进入首个聚合步骤的行编号；重放行数与 Engine 步骤日志不一致时报告缺口。
- `backend/tests/test_evaluation_constraint_coverage.py`：15 个测试（12 项必测、重复标签守卫、错误筛选反例、Runner 配置哈希与端到端）。
- 验收脚本 `stage-b/expected_behaviour.py` 及其输出。

## 修改文件

- `must_forbid.py`：`must-forbid-v1` 升级为 `must-forbid-v2`。逐句经映射解析，支持四种方式：forbid_field、row_set、ORACLE_COVERED、NON_ASSERTION；另加重复标签守卫。判定顺序：FAIL → NOT_EVALUATED（未映射、映射失效、缺证据、Oracle 未通过）→ PASS。
- `forbid_rules.py`：RF-04 的 adaptation 条目迁入映射；本文件只保留规则定义，`RULES_VERSION=golden-forbid-rules-v1`。
- `golden_run.py`：evidence 的 artifacts 增加 `dataset_rows`（Golden 原始行）。
- `test_evaluation_quality_gates.py`、`test_evaluation_contracts.py`：断言随预期行为调整：reason 文本变化；RF-04 增加 row_set 检查；RF-02 已有映射，不能再当“未适配”样例；脚本化运行中 RF-02、RF-05 的 E2E 由 NOT_EVALUATED 变为 PASS。

## 映射失效规则

一条映射只有同时满足以下条件才可用，否则该句为 `coverage_stale:<ref>:<原因>`，结论 NOT_EVALUATED：

- `constraint_text_hash` 等于当前原文的 SHA-256；
- `mapping_version` 等于当前版本；
- `evaluator_version` 等于 `covered_by` 指向的 Evaluator 的当前版本（Oracle 为 `golden-oracle-v2`，独立检查为 `must-forbid-v2`）；
- `coverage_basis.capability_version` 等于 `CapabilityRegistry.version`；
- `coverage_basis.rows_sha256` 等于 evidence 中 Golden 行的规范化 JSON 哈希。

映射全文、守卫、规则及版本都写入 `MustForbidEvaluator.config()`，从而进入 run-config 中该 Evaluator 的 `config_sha256`。

## 不做的事

- 不回填历史运行；历史结果按记录读取。
- 不修改 Golden Set、Oracle 逻辑与预期、Agent、Planner、Engine、HITL、TC Runner。
- RF-03 的 must_execute[0]「只保留岗位类型为实习的行」不单独映射：它恰好等于 must_forbid[0]（逐行读法：两城实习不得丢）与 must_forbid[1]（正式不得计入）两条行集合检查的合取，单独映射会造成重复评测。
- 其余 must_execute 条目（城市范围、分组方式、一行一岗）不在本阶段映射范围内。
