Phase 1-E Stage B：按 REQ-0145 决策（D1 行集合必需检查、D2 城市标签唯一守卫、D3 逐行读法、D4 全部用例）实现版本化 Constraint Coverage Mapping。

- 新增 backend/app/evaluation/constraint_coverage.py（golden-constraint-coverage-v1）和 backend/app/evaluation/row_set.py（用注册内核重放已执行计划）。
- MustForbidEvaluator 由 must-forbid-v1 升级为 must-forbid-v2；forbid_rules.py 只保留规则；golden_run.py 的 artifacts 增加 dataset_rows。
- 映射覆盖：18 条 must_forbid 全部映射（ORACLE_COVERED 11 条，INDEPENDENT_CHECK 6 条，NON_ASSERTION 1 条），另加 must_execute 2 条（RF-01[0]、RF-04[0]，行集合检查）。
- 测试：新增 15 个；评测相关 47 个全部通过；后端全量 1739 通过，1 个失败为既有问题（REQ-0133 test_failure_diagnosis）。
- 历史：13 份历史文件哈希不变，Golden Set sha256 fe52a92c… 不变，不回填历史运行。
- 修改前副本：docs/implementations/evaluation-constraint-coverage-v1-2026-11-13/before/；说明：同目录 NOTES.md。
- 完成后停止，不进入 Phase 2。
