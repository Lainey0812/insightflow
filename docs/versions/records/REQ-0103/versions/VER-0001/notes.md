# Direction-first MVP acceptance — frozen baseline 01

Date: 2026-11-09 (Asia/Shanghai). Requirement: REQ-0103. **Not accepted as complete MVP.** No business implementation was changed.

## Outcome

Ten frozen cases were run once against the configured real qwen3.8-flash provider. All 32 HTTP calls returned successfully. Nine cases reached server-approved execution; every actual computation matched an independent Pandas reference. The missing-profit case safely stopped before approval/execution. This small single round does not measure long-term reliability.

Persisted report statuses: **6 complete, 3 partial, 0 failed, 0 unavailable**, plus **1 expected safe stop**. These are service statuses, not a blanket business acceptance score. All normal cases in this selected set reached approval; earlier constraint-mapping failures from other inputs remain unresolved and are not disproved by this round.

All ten Workflow Trace snapshots were retrieved through the actual authenticated Admin API over real persisted isolated stores. Correlation checks confirm one Workflow Root, direct Node Spans, real completion times, associated call/snapshot IDs and no recorded collection gap. This does not prove that every possible observability failure mode is covered.

## Case results

| Case | Domain / mode | Stored report outcome | Elapsed | Agent review |
|---|---|---|---:|---|
| S01 | sales / numeric | complete | 17.9s | 核心筛选、销售额、城市、降序和Top3均匹配独立基准。比较证据充分，建议仍偏向通用核对。排名固定附带并列说明，容易误读。 |
| S03 | sales / exploratory | complete | 32.9s | 4个方向与销售探索相关，实际计算均通过。报告有10条洞察，长小数和重复边界文案降低可读性；本轮未证明普通用户能独立理解。 |
| S04 | sales / blocked | expected_stop | 9.1s | 缺少利润数据，保留P0不可执行计划，coverage=blocked且无执行记录。属于预期安全停止，不是报告成功。 |
| R01 | recruitment / numeric | complete | 11.9s | 城市计数与排序正确，数值可追溯。当前数据无岗位唯一标识，报告使用记录计数；不能泛化为已完成岗位实体去重。 |
| R03 | recruitment / clarify | complete | 16.5s | 模糊请求实际暂停澄清；补充后在同一Workflow继续，生成正确城市计数和报告。 |
| T01 | support / numeric | partial | 12.8s | 均值计算正确，7个非空响应值参与。重复极值候选被正确拒绝，报告保留2条洞察但标partial。排名按数值高低而非响应越快越好，易造成业务误读。 |
| P02 | projects / numeric | complete | 14.1s | 只保留已完成且非丙项目，甲16、乙36、合计52与独立基准一致。建议与解释偏模板化。 |
| P03 | projects / exploratory | partial | 37.5s | 3个方向有业务相关性，10个指标实际计算通过。差值证据被选为集中度主证据，校验正确拒绝；报告partial/coverage partial，任务数指标对应候选未进入报告。使用显著差异措辞但操作只有描述统计，不应理解为统计显著性已验证。 |
| R05 | recruitment / exploratory | complete | 21.3s | 4个方向可计算且相关，但最终仅城市和学历有文字发现；薪资和岗位名称有图表无解读，也未作为未完成方向披露。系统complete不等于方向解读完整。 |
| T05 | support / exploratory | partial | 33.1s | 4个方向可计算。工单数量差值证据被当作集中度主证据，校验正确拒绝。优先级/状态、月度方向无文字解读，未完成任务列表为空。业务问题含显著差异、处理进度优于，现有链路未验证显著性或绩效优劣。 |

## Independent business results

- S01: Jinan 21,250; Nanjing 20,250; Shanghai 5,760. Returned Top 3 total 47,260. Exact year/region/completed-order scope, ranking and Top N were checked independently. This frozen sales CSV has 10 rows; it is not the separate 60-row file in the user’s active conversation.
- R01/R03: Beijing 3, Shanghai 2, Hangzhou 2, Nanjing 1 records. The recruitment fixture has 8 records and no unique job ID, so do not claim verified entity deduplication.
- T01: Team 1 average 18.3333333333 minutes; Team 2 40; Team 3 5. Seven non-null response values out of eight uploaded rows participate. No invented effective sample count.
- P02: completed tasks excluding project C; project A 16 hours and B 36, total 52.

## Confirmed gaps and priorities

1. **Finding type selection causes valid safety rejection (P03, T05).** Both model candidates use `finding_type=concentration` with a primary `difference` evidence item. `materialize_selection` in `backend/app/reporting/materialize_v2.py:38` correctly rejects this. The exact raw candidates, source Evidence and fact-validator Span IDs are in bad-cases.json. This is not a reason to remove validation. Next proposal: constrain or guide primary-evidence/type selection using the actual compatibility contract, retaining all core metrics.
2. **Successful directions can lack written explanation (R05, T05).** R05 produces charts for salary and job-name directions but only two Insights for city/education; it still reports complete with no uncompleted tasks. T05 lacks explanations for priority/status and monthly directions. The current report coverage check in `backend/app/services/analysis_report.py:162` is P0-metric focused; it does not guarantee explanations for every displayed direction. Next proposal: track executed-direction interpretation coverage and disclose missing explanations without deleting results or manufacturing prose.
3. **Duplicate candidate rejection and incomplete delivery are conflated (T01).** The rejected highlight merely repeats facts already covered by ranking/comparison. Deduplication at `backend/app/reporting/materialize_v2.py:46` is justified; batch status at `backend/app/reporting/batches.py:137` becomes partial on rejection. Next proposal: separately represent harmless deduplication and real missing coverage; preserve the rejected candidate and existing safety checks. Any status-policy change needs explicit design/review rather than relabelling this run.
4. **Business language remains weak.** `backend/app/reporting/claims.py:181` adds the same tie-rank parenthesis to every rank. Long decimal outputs and generic caution/review-source recommendations reduce readability. Some generated planning questions mention significant differences or superior progress even though only descriptive operations are available; neither statistical significance nor performance superiority was verified. These are recorded quality issues, not new model-proven conclusions.

## Trace and model timing

32 real HTTP calls: Intent 11 (including clarification continuation), Planner 10, report Insight 11 (including report batches). No retry_index greater than zero in this round. Median call durations: Intent 2.532s, Planner 7.104s, Insight 4.442s. Planner range 4.268–20.701s. These are observed wall times for this selected run, not an SLA. Full workflow times range 9.1–37.5s including the safe-stop case.

## Scope and limits

- Inputs are synthetic CSV business scenarios, inherited from the existing frozen suite. R05 and T05 are new exploratory requests, not a blinded holdout. No private uploaded business document was transmitted.
- This is an end-to-end backend API acceptance run using TestClient plus actual external HTTP model calls and persisted SQLite/files. It is not ten browser-operated trials, and no ordinary-user usability pass is claimed.
- All model requests/responses, plan, review, execution, independent oracle, report, presentation and Trace snapshots are retained under runs/frozen-baseline-01. Rejected candidates and partial outputs are not replaced by outer retries.
- Each case uses an isolated business/trace/registry storage directory recorded in configuration.json. These test records were not inserted into the running user/Admin databases. Raw Admin response snapshots are available here; their Workflow IDs do not automatically resolve in the currently running production Admin instance.
- No Source/Prompt/model/algorithm change. The hashes of 244 existing source files remain unchanged. Frozen input hashes pass. Existing automated tests are not claimed as rerun in this evaluation-only delivery; the real oracle, approval guard and idempotency checks are in each case record.
- Versioned edit/delete behavior remains covered by the preceding HITL automated suite, not newly exercised against every generated plan in these ten runs. A real ordinary-user trial and browser edit/delete reapproval trial are still required before usability sign-off.

## Files

frozen/: inputs and pre-run rubric; source-freeze.json: source hashes; run-plan.json: selected cases and no outer retries; batch-results.json: original harness verdicts (pending_review retained); case-review.json: separate agent interpretation; summary.json: numerical facts; bad-cases.json: exact rejected candidates and missing direction explanations; trace-correlation.json: full node references; runs/: actual artifacts.

## Recommended next action

First fix report selection compatibility and direction-explanation coverage, then rerun this same frozen set as a new run directory. Do not redesign HITL again, remove core indicators, relax safety checks, or introduce another LLM node to conceal the issue. Ordinary-user review remains pending. No fixes were started in this task.
