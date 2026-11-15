# Report reliability V2.1.1 delivery

Date: 2026-11-09 (Asia/Shanghai). Requirement **REQ-0104**. Final Prompt `report-insights-v2.1.1`; generation `evidence-selection-v2.1.1`; final composition `composition-v0.12-report-reference-format-v1`. Model remains **qwen3.8-flash**, using the same OpenAI-compatible provider and configured model parameters. Public AnalysisReport schema, Engine, Planner, Validator and HITL business rules remain unchanged.

## Changes

1. The dynamic request Schema now binds finding_type, primary evidence IDs, same-task/result/metric/scope reference sets and recommendation IDs together in per-group branches. Allowed type lists are also supplied in the input. Prompt requires every included real metric group, including auxiliary/supplementary directions; existing batching budget of eight groups per call remains. Runtime validation independently checks all bindings; a model/schema claim is never enough.
2. All candidates are fully validated before deduplication. A candidate is harmless redundancy only if all its verified semantic facts are already covered. Invalid recommendations, limits, sources, values, type or references still cause rejection even when the primary ID repeats. Reusing a primary while adding genuinely new verified evidence is permitted. Redundant candidates remain in metadata and Trace with an explicit disposition; they are not silently discarded or falsely presented as a failed fact check.
3. Successful directions lacking valid Insights are explicitly listed in uncompleted_tasks, limitations and interpretation_status. Their charts and complete results remain. The report becomes partial; original Engine success remains intact. Core metric coverage is unchanged. No rule template fabricates missing interpretations.
4. Exact repeated Evidence IDs are normalized as an auditable formatting repair. The raw Draft is unchanged; original and normalized refs plus rule_id are recorded in candidate_repairs. No primary ID is added, no field/type/value/recommendation is changed, and full validation must pass first. Unknown or missing references, cross-metric composition and invalid options remain rejected. This is an explicit narrow change to the old duplicate-reference formatting rule, not a relaxation of factual verification.
5. Historical V2.0/V2.1 presentations explicitly retain the saved-Insight rendering path when the current generation version changes. Old reports and Prompt snapshots are not rewritten. The output-boundary allowlist includes the new version because it retains the same controlled renderer; unsupported free-text/causal/profit claims remain blocked.

## Actual files

Eleven files are listed in changed-files.json; source snapshots are in before.zip, before-extra.zip, before-boundaries.zip, before-v2.1.1.zip, before-reference-format.zip, before-module-test.zip and after.zip. Prompt diff is prompt.diff. No new database migration or API. The existing versioned Prompt Registry records changed templates under new composition IDs. No independent Attempt entity or third Trace layer.

## Automated verification

- Final backend: **1633 passed**, 88.79 seconds (backend-regression-completed.log). Existing Starlette/httpx deprecation warning remains.
- Frontend: **93 passed**, TypeScript/Vite build passed. Frontend source was not changed.
- Admin: **88 passed**, TypeScript/Vite build passed. Admin source was not changed.
- New regression tests replay exact saved real candidates for T01/P03/R05/T05, verify continued invalid-type rejection and missing-direction disclosure, validate Schema group binding, test bad duplicates versus harmless redundancy, audit exact repeated reference repair, and preserve historical presentation. Existing unknown-ID, unsupported facts, causal inference, cross-metric, source tampering, timeout, Engine/Workflow and approval tests remain in the full suite.

## Real model evaluation: do not merge different experiments

All evaluations use the unchanged ten synthetic CSV cases and business rubric frozen in REQ-0103. Original baseline records are untouched. No outer retry or new LLM node; changed implementations run in fresh directories. A full-chain run regenerates Intent and plans, so fixed-upstream report-only comparisons are separately recorded.

| Experiment | Full/complete reports | Partial reports | Expected safety stop | Note |
|---|---:|---:|---:|---|
| Original REQ-0103 full chain | 6 | 3 | 1 | Baseline retained |
| V2.1 full chain | 9 | 0 | 1 | Intermediate; not proof all old report inputs were fixed |
| V2.1 fixed original upstream (4 cases) | 2 | 2 | 0 | Exposed recommendation binding and cross-metric selection; retained |
| V2.1.1 full chain | 8 | 1 | 1 | S03 has two F0 directions skipped by Engine; report correctly partial |
| V2.1.1 fixed original upstream (4 cases) | 3 | 1 | 0 | Exact duplicate refs rejected in R05; retained |
| Final reference-format patch: fixed original upstream (4 cases) | **4** | **0** | 0 | Same historical Intent, Approval, plan, profile and ExecutionResult |

The final fixed-upstream comparison uses five real HTTP calls. All four reports have valid interpretations for all their executed directions, with no rejected candidates or missing-direction records in this particular round. Their raw inputs/outputs, saved report JSON, Presentation and call IDs are under `docs/evaluations/report-reliability-v2.1.1-2026-11-09/fixed-upstream-release/`. Numeric source tables were unchanged. This is a targeted known-case test, not an independent holdout or long-term reliability estimate.

The most recent full-chain run precedes only the final exact-reference formatting patch (composition v0.11 versus final v0.12). It has 31 HTTP calls. Eight executions succeed and one is partial_success; one missing-profit case safely stops. Every successful task matches independent Pandas values. S03 has two skipped F0 tasks, so the inherited runner reports CALCULATION; it is not an observed wrong numeric result in a successful task. It remains an unresolved upstream planning-quality case, not a passed case. It was not rerun with a more favorable new plan. All Root/Span/call links and recorded collection status were verified.

Across both implementation revisions and all real substudy calls, **77 HTTP requests** were retained, including intermediate partial results. These are separate, justified implementation experiments; no failed result was overwritten or excluded to advertise a single perfect score.

## Remaining risks

- S03 can still produce F0 task chains (access to an original field after a previous aggregate removed it). Validator identifies them and Engine skips them; report preserves partial state. Planner/Engine were intentionally not changed. Full MVP acceptance remains **not passed**.
- Long numeric decimals, generic recommendations, tie-rank wording and descriptive questions using significance/performance language remain quality issues from the baseline. They were not the target of this generation-reliability patch.
- Model selection can still be invalid despite strict Schema; runtime validation and explicit partial/failure states remain essential. No professional-analyst-level quality or universal success guarantee is claimed.
- The final formatting patch was verified by the full automated suite and fixed original upstream real-model reports, not another fresh ten-case run. Ordinary-user usability testing and broader unseen inputs remain pending.
- Evaluation storage is isolated from the active user/Admin databases. Full-chain Trace snapshots are in the evaluation artifacts; report-only calls have no fabricated Run/Span association. Historical live reports are unchanged, so refreshing an old report does not regenerate it.
- The local backend was restarted to load the final version. Use a new analysis to test it. No existing report was replaced.

## Preserved test/harness failures

Initial new Schema test expected a returned-concentration Evidence in a two-group fixture; it was corrected to test a real proportion Evidence. One old duplicate-reference negative test was updated to include an unknown ID (still rejected), and an explicit positive/audit test for exact valid repetition was added. These changes match the documented formatting contract and do not remove the unknown-ID or source-binding safety boundary. All initial failing logs remain.
The first fixed-upstream runner queried CallRecords without a required scope after T01 had already generated. T01 was recovered by its exact persisted Call IDs, without a new model call. Subsequent calls use captured operation IDs. The runner error, original script and recovered metadata are retained in the V2.1 evaluation directory.

## Artifact links

- [Final case/Trace summary](../../evaluations/report-reliability-v2.1.1-2026-11-09/final-summary.json)
- [Remaining upstream case](../../evaluations/report-reliability-v2.1.1-2026-11-09/remaining-bad-cases.json)
- [Recruitment fixed-input report HTML](../../evaluations/report-reliability-v2.1.1-2026-11-09/R05-report-preview.html)
- [Project fixed-input report HTML](../../evaluations/report-reliability-v2.1.1-2026-11-09/P03-report-preview.html)
- [Original frozen acceptance](../../evaluations/direction-first-acceptance-v1-2026-11-09/README.md)
