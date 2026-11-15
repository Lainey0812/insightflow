# Phase 1-E Stage A：Golden Set must_forbid 约束覆盖审核

- 需求：REQ-0144（Golden Set 约束覆盖审核与最小适配）
- 性质：只读审核。未修改任何生产代码、测试、Golden Set、Oracle 或历史运行数据。
- 结论：Stage A 发现需要产品决策的语义歧义与 Oracle 业务缺口，按 REQ-0144 要求在 Stage B 之前停止，提交决策问题。
- 证据：`probe_counterexamples.py`（使用真实 Engine 内核 `app.planning.operations` 在 Golden 9 行上执行计划，再交给真实 `GoldenOracleEvaluator` 判定），输出见 `probe-output.log`。
- Golden Set：`docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json`，sha256 `fe52a92cc77bb16fa5425f5618c7d7a9dd633f0790eaf341a3c434554a052142`。

## 1. 覆盖论证所依赖的前提

ORACLE_COVERED 结论不是通用逻辑推论，而是绑定在下列前提上的数据级证明。任一前提变化，映射必须失效。

| 编号 | 前提 | 依据 |
|---|---|---|
| A1 | 分析数据就是 Golden Set 的 9 行（J01–J09），四列均为文本。 | golden-set.json sha256 如上；runner 用 `rows` 生成数据文件。 |
| A2 | Engine 无 join/union/行复制/改写城市值的算子。 | `CapabilityRegistry` v1.0：filter、group_aggregate、aggregate、sort、top_n、derive（仅 extract_year/extract_month）。 |
| A3 | 数据无数值/日期列，因此唯一可得的数值指标是 count / distinct_count，其值不超过所在分组的行数。 | sum/avg/median/min/max 只接受数值字段；derive 只接受日期字段。 |
| A4 | Oracle 要求每个非空结果表都存在某个（标签列, 数值列）组合，其映射的键集合与 Oracle 完全相等、数值相等。 | `_exact_oracle` + `find_mapping(exact=True)`。 |
| A5 | `find_mapping` 对同一标签的重复行按“最后一行覆盖”处理。 | `scoring.py` 中 `mapping[_key(row[label])] = …` 逐行赋值。 |

各城市行数：上海 4（正式 3、实习 1）；深圳 3（正式 1、实习 2）；北京 1（正式）；杭州 1（实习）。上海不同岗位名称 2 个（产品经理、分析师）。

## 2. 真实内核反例（probe-output.log）

| Case | 计划 | Oracle | 说明 |
|---|---|---|---|
| RF-01 | 城市 in 上海/深圳，岗位名称 eq 产品经理，按城市计数 | PASS | 上海 3 = J01、J02、J04，其中 J04 是实习。错误筛选条件得到正确数值。 |
| RF-01 | 不筛岗位类型，按城市+岗位类型计数，按岗位类型升序 | PASS | 表里有 4 行，城市标签重复；最后覆盖后得到上海 3、深圳 1。实习未被排除。 |
| RF-04 | 同 RF-01 的产品经理筛选 | PASS | 同上。 |
| RF-03 | 城市 in 上海/深圳，岗位名称 eq 分析师，按城市计数 | PASS | 上海 1 = J03（正式），深圳 2 = J06、J07。正式岗位被计入，实习 J04 被丢弃。 |
| RF-03 | 不筛岗位类型，按城市+岗位类型计数（默认首现顺序） | PASS | 结果表包含正式行；最后覆盖后得到上海 1、深圳 2。 |
| RF-02 | 岗位类型 ne 实习 / eq 实习 | FAIL（F-EXTRA-CONSTRAINT / F-POLARITY-REVERSED） | 违规可被 Oracle 抓住。 |
| RF-05 | 城市 in 深圳/北京/杭州（白名单） | PASS | 与“城市 ne 上海”在本数据上等价，不违反任何 must_forbid。 |
| RF-05 | 再加岗位类型 ne 实习 / 按城市+岗位类型 | FAIL（F-EXTRA-CONSTRAINT / F-ORACLE-MISS） | 深圳子组最大为 2，覆盖后不可能得到 3。 |

## 3. 覆盖矩阵（18 条）

| Case | Constraint | 原文 | 分类 | 覆盖 Evaluator | 证据 | 反例 | 结论 |
|---|---|---|---|---|---|---|---|
| RF-01 | #0 | 不得把排除实习做成只保留实习。 | ORACLE_COVERED | golden-oracle-v2 | A1–A4：只保留实习时上海分组最多 1 行，不可能出现上海 3。 | 无可构造反例；只保留实习得 1/2，命中 F-POLARITY-REVERSED。 | 覆盖（数据级） |
| RF-01 | #1 | 不得计入北京或杭州。 | ORACLE_COVERED | golden-oracle-v2 | A2 + A4：键集合必须恰为 {上海, 深圳}；无改名算子，北京行不能并入上海分组。 | 不筛城市得 {上海3, 深圳1, 北京1} → F-INCLUDE-DROPPED。 | 覆盖 |
| RF-01 | #2 | 不得按岗位名称去重。 | ORACLE_COVERED | golden-oracle-v2 | A3：上海不同岗位名称只有 2 个，任何按名称去重的上海值 ≤ 2。 | 去重得 2/1 → F-METRIC-SUBSTITUTED。 | 覆盖（数据级） |
| RF-01 | #3 | 不得只输出一个总数。 | ORACLE_COVERED | golden-oracle-v2 | A4：每个非空表都必须是按城市的映射；单值总数表无法匹配。 | {岗位数量: 4} → F-GOAL-SUBSTITUTED。 | 覆盖 |
| RF-02 | #0 | 不得排除实习。 | ORACLE_COVERED | golden-oracle-v2 | A3 + A5：上海 4 / 深圳 3 等于两城全部行数，必须包含 J04、J06、J07；任何真子组都达不到 4/3，重复标签覆盖也无效。 | 岗位类型 ne 实习 → F-EXTRA-CONSTRAINT（已实测）。 | 覆盖（数据级） |
| RF-02 | #1 | 不得把「不排除」写成只看实习。 | ORACLE_COVERED | golden-oracle-v2 | 只看实习时上海 ≤ 1。 | 岗位类型 eq 实习 → F-POLARITY-REVERSED（已实测）。 | 覆盖（数据级） |
| RF-02 | #2 | 不得漏掉任一城市。 | ORACLE_COVERED | golden-oracle-v2 | A4 键集合相等；“任一城市”按 must_execute「上海和深圳都要出现」理解。 | 缺一城 → 键集合不等 → FAIL。 | 覆盖 |
| RF-03 | #0 | 不得排除实习。 | 待决策（极性读法：ORACLE_COVERED；逐行读法：INDEPENDENT_CHECK） | — | 极性读法：排除全部实习时深圳 ≤ 1，不可能得到深圳 2。 | 逐行读法：岗位名称 eq 分析师丢弃实习 J04，Oracle 仍 PASS（已实测）。 | 语义歧义，见决策 D3 |
| RF-03 | #1 | 不得把正式岗位算进结果。 | INDEPENDENT_CHECK | 无（当前未覆盖） | 需要已执行计划的筛选条件 + profile 字段映射 + engine 步骤对应关系，才能确认进入聚合的行没有正式岗位。 | 岗位名称 eq 分析师 → 上海 1 = J03（正式），Oracle PASS；按城市+岗位类型分组，重复标签覆盖后同样 PASS（均已实测）。 | 未被 Oracle 覆盖 |
| RF-04 | #0 | 不得读取、解析、聚合、筛选或分组薪资、薪资区间。 | INDEPENDENT_CHECK | must-forbid-v1 / forbid-salary-field | plan + profile + engine + result_columns（Phase 1-D 已实现）。 | 计划中有薪资分组而结果仍是上海 3、深圳 1 → 必须 FAIL。 | 已有独立检查 |
| RF-04 | #1 | 不得发明薪资字段。 | INDEPENDENT_CHECK | must-forbid-v1 / forbid-salary-field | 同上（别名与聚合别名匹配）。 | 别名 salary_avg。 | 已有独立检查 |
| RF-04 | #2 | 不得输出薪资数值或薪资区间。 | INDEPENDENT_CHECK | must-forbid-v1 / forbid-salary-field | result_columns 范围。 | 结果列含 薪资区间。 | 已有独立检查 |
| RF-04 | #3 | 不得用薪资任务代替岗位数量。即使同时给出上海 3、深圳 1，只要执行了薪资计算，也失败。 | INDEPENDENT_CHECK | must-forbid-v1 / forbid-salary-field | 原文明确 Oracle PASS 不足以通过。 | 正确计数 + 另一个薪资任务。 | 已有独立检查 |
| RF-04 | #4 | 计划正文里保留「不要分析薪资」这句话，不算执行了薪资分析。 | NON_ASSERTION | must-forbid-v1（clarification） | 对 #0–#3 的判定说明：只匹配结构化标识符，不扫描计划正文。 | — | 解释性条目 |
| RF-05 | #0 | 不得保留上海。 | ORACLE_COVERED | golden-oracle-v2 | A4：键集合恰为 {深圳, 北京, 杭州}。 | 不排除上海 → F-EXCLUDE-DROPPED。 | 覆盖 |
| RF-05 | #1 | 不得漏掉深圳、北京、杭州中的任何一个。 | ORACLE_COVERED | golden-oracle-v2 | A4 键集合相等。 | 缺杭州 → F-ORACLE-MISS 控制项。 | 覆盖 |
| RF-05 | #2 | 不得只输出深圳。 | ORACLE_COVERED | golden-oracle-v2 | A4 键集合相等。 | 只输出深圳 → 键集合不等。 | 覆盖 |
| RF-05 | #3 | 不得再排除实习。 | ORACLE_COVERED | golden-oracle-v2 | A3 + A5：深圳 3 必须包含 J06、J07；杭州 1 只能是 J09（实习）；深圳子组最大 2，覆盖无效。 | 再加 ne 实习 → F-EXTRA-CONSTRAINT；城市+岗位类型 → F-ORACLE-MISS（均已实测）。 | 覆盖（数据级） |

## 4. 五个问题

1. RF-02、RF-05 的 must_forbid 是否完全被 Oracle 覆盖：是，7 条全部 ORACLE_COVERED，但只是基于 A1–A5 的数据级证明，并非对任意数据成立。映射的 coverage_basis 必须绑定 Golden Set 哈希、Oracle 版本与 Engine 能力版本。
2. 需要独立检查的：RF-03 #1（当前无任何检查）；RF-04 #0–#3（Phase 1-D 已实现）；RF-03 #0 取决于决策 D3。
3. 缺乏证据的：新运行都有 plan、profile、engine、result_tables，足以支撑上述检查。历史运行（如 `gf_20261112-143406_cde1fd`）没有 plan 和 profile，独立检查只能给出 NOT_EVALUATED，不补算。`execution_steps` 本身不带字段引用，需要通过 (task_id, step_id) 回连 plan。
4. 仅解释性的：RF-04 #4。
5. Oracle 本身未覆盖的业务要求：
   - RF-01 / RF-04 的核心要求「聚合前排除实习」只写在 must_execute，不在 must_forbid。岗位名称 eq 产品经理会得到正确数值而 Oracle PASS。
   - RF-03 的核心要求「只保留实习行」：岗位名称 eq 分析师会得到正确数值而 Oracle PASS。
   - `find_mapping` 重复标签按“最后一行覆盖”（A5）：按城市+岗位类型分组的表可以让 RF-01、RF-03、RF-04 的 Oracle PASS，而结果表实际包含不应计入的行。RF-02、RF-05 不受影响。

## 5. 特殊反例的适用情况

“Oracle 数值结果正确，但 Agent 使用了错误筛选条件”在本数据上真实存在（RF-01/RF-04 产品经理筛选、RF-03 分析师筛选）。若在 Stage B 把 RF-01 #0–#3 全部映射为 ORACLE_COVERED，RF-01 的 must_forbid 会全部通过；而筛选错误违反的是 must_execute，并不在 must_forbid 中，所以 E2E 结论会变成 PASS。这是否可接受属于验收口径问题，不能由实现者自行决定。

## 6. 提交的决策问题

- D1：RF-01 / RF-04 的「聚合前排除实习」（must_execute）以及 RF-03 的「只保留实习行」，是否要作为 E2E 必需的独立检查纳入本阶段？
- D2：`find_mapping` 的重复标签覆盖问题如何处理？可选：修改 Oracle 逻辑（属于修改 Oracle，此前被禁止）；作为独立检查（结果表城市标签必须唯一）；或暂不处理，只登记为已知缺口。
- D3：RF-03 #0「不得排除实习」采用哪种读法？极性读法（不得施加“排除实习”的筛选，已被 Oracle 覆盖），还是逐行读法（上海、深圳的任何实习行都不得被丢弃，需要独立检查）？
- D4：在 D1/D2 定案前，Stage B 是否先只为 RF-02、RF-05（以及 RF-04 #4）启用覆盖映射，RF-01、RF-03 暂不映射、保持 NOT_EVALUATED？
