Phase 1-E Stage A（只读审核）完成，未进入 Stage B。

- 未修改任何生产代码、测试、Golden Set、Oracle 或历史运行数据。
- 新增审核证据目录 docs/evaluations/constraint-coverage-review-phase1e-2026-11-13/：REVIEW.md（18 条 must_forbid 覆盖矩阵与五个问题）、probe_counterexamples.py（用真实 Engine 内核与真实 GoldenOracleEvaluator 实测反例）、probe-output.log。
- 结论：RF-01 #0–#3、RF-02 全部、RF-05 全部为 ORACLE_COVERED（数据级证明，依赖 Golden 哈希与 Engine 能力集）；RF-03 #1 为 INDEPENDENT_CHECK 且当前未覆盖；RF-04 #0–#3 已由 must-forbid-v1 独立检查；RF-04 #4 为 NON_ASSERTION；RF-03 #0 语义歧义待决策。
- 发现 Oracle 业务缺口：错误筛选（岗位名称 eq 产品经理 / eq 分析师）可使 RF-01、RF-04、RF-03 的 Oracle PASS；find_mapping 重复标签“最后一行覆盖”可使 RF-01、RF-03、RF-04 的 Oracle PASS。
- 按 REQ-0144「Stage A 如果发现约束语义存在歧义，或者需要产品决策才能确定验收标准，应停止并提交决策问题」停止，提交决策 D1–D4，等待用户确认。
