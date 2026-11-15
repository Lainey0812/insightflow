# Phase 1-C integration acceptance (REQ-0142)

Date: 2026-11-13. Verification only. No production code, test assertion, Golden Set, Oracle expectation or historical run was changed. No model was called.

Overall verdict: CONDITIONAL_PASS. The Golden runner to metrics loop works and historical data is intact. RF-04 `must_forbid` is not a registered required check and can let a wrong E2E PASS through, so Phase 2 should wait for the minimal fix described below.

## Evidence

- `verify_phase1c.py`: the acceptance script. Scripted `run_one`, temporary run directories copied to `outputs/runs/`.
- `verify-output.log` and `outputs/checks.json`: 35 checks, 28 PASS, 6 FAIL, 1 INFO, each with its evidence.
- `regression/`: pytest and vitest logs for the current tree and for a reconstructed pre-Phase-1-B tree.

Command: `.venv/bin/python docs/evaluations/evaluation-contracts-phase1c-2026-11-13/verify_phase1c.py` from `insightflow/`. The script refuses to run if `outputs/` already exists.

## 1. Integration loop

All of these passed:

1. The runner calls the new evaluators. Spy wrappers recorded `evaluate` for all five cases, and `golden_fidelity.score_case` was replaced by a tripwire that was never hit.
2. Each case has its own execution locator, two evaluator results that point to that locator, and its own E2E verdict.
3. `run-config.json` existed before every `run_one` call, and the manifest did not.
4. `run-manifest.json` was written at the end with status FINISHED and five cases.
5. All 12 hashes in the manifest (config, summary, five results, five traces) match the files, and there are no unlisted files.
6. `read_run` returns the recorded run as FINISHED, with executions, evaluator results and E2E summaries identical to the stored JSON. Config integrity is verified.
7. `metrics.compute` on the `read_run` output equals the metrics in the runner's summary.
8. Interruption inside RF-03 gives INCOMPLETE with RF-03 to RF-05 missing. An interruption after all five results but before the summary also gives INCOMPLETE, never FINISHED.

The default registration is oracle (required) and node fidelity (optional).

## 2. Hard gates

Six aggregation scenarios behave as specified. They were tested with a stub required forbid evaluator, because no such evaluator exists in the runner:

- oracle PASS with forbid PASS gives PASS;
- forbid FAIL gives FAIL;
- forbid NOT_EVALUATED gives NOT_EVALUATED;
- forbid EVALUATOR_ERROR gives EVALUATOR_ERROR;
- agent FAILED with oracle NOT_EVALUATED gives FAIL;
- an optional EVALUATOR_ERROR leaves PASS.

## 3. RF-04 must_forbid

- No production file reads `must_forbid`. The rule is hard-coded as `case_id == 'RF-04' and salary_executed(...)` at the top of `GoldenOracleEvaluator.evaluate`. When it fires, the oracle returns FAIL `F-METRIC-SUBSTITUTED`.
- There is no separate required forbid evaluator, so forbid NOT_EVALUATED and EVALUATOR_ERROR cannot be represented. Missing evidence is treated as clean.
- What the current check catches: a result column containing 薪资, and a plan step on a profiled field whose display name contains 薪资. Both give FAIL.
- What it misses:
  - With no plan and no profile captured, RF-04 with the right counts is oracle PASS and E2E PASS, also through the runner.
  - A step on a field id 薪资 that is not in the profile is PASS, although `must_forbid` says not to invent salary fields.
- The Golden data has no salary column (编号, 城市, 岗位名称, 岗位类型), so the profiled-field branch cannot fire on this data set. In practice only the result-column check is live.
- Exposure in real runs is limited: the runner records the plan and profile whenever there is a reviewed plan, and the plan validator should reject unknown fields. But the gate is unsound, because it treats absence of evidence as a pass.

Minimal fix, not applied:

- Add a required `insightflow.golden.must_forbid` evaluator that applies only to cases with `must_forbid`.
- It returns NOT_EVALUATED when the plan or profile is missing, and FAIL when any step identifier or result column names salary, whether or not the field is profiled.
- Move the RF-04 branch out of the oracle and register the new evaluator as required in `default_evaluators`.
- Add tests for the four verdicts.

## 4. Regression attribution

The pre-Phase-1-B tree was rebuilt under `/tmp/if-pre1b`. Phase 1-B changed exactly 11 files (10 new, 1 modified), with no Admin files among them. In the rebuild the 10 new files were removed and `run_golden_fidelity.py` was restored from the before-copy (sha256 `4989cc04…`, same as the archived copy). Both trees give identical results.

- Backend `test_failure_diagnosis.py::test_success_has_no_failure_and_records_inputs_without_user_text`. Verdict: PRE_EXISTING.
  - It fails on `assert session['user_goal'] not in json.dumps(detail)`. The text appears at `$.trace.nodes[1].intent_result.user_query`.
  - Source: `backend/app/services/workflow_trace.py` lines 100-105 attach the saved IntentArtifact to the intent node.
  - This was added by REQ-0133 (intent-node-detail-v1). Its 12:53 before-copy has no `intent_result`; the later planner-node-detail before-copy does.
  - REQ-0133 recorded running only the observability detail tests.
  - Same failure in the pre-Phase-1-B tree: 1 failed, 4 passed.
- Admin `traces.test.tsx` (9) and `comparison.test.tsx` (1). Verdict: PRE_EXISTING.
  - All ten open `/traces...`, which `admin/src/app/routes.tsx` line 37 redirects to `/traces/workflows`. The Run Explorer elements the tests expect never render, and the Workflow list's multiple 查看详情 links break the single-link queries.
  - The redirect was added by REQ-0126; the archived before-copy of `routes.tsx` has no such route. REQ-0126 notes record the redirect.
  - Same 10 failed, 13 passed in the pre-Phase-1-B tree, with identical per-test outcomes.

## 5. Data integrity

- Historical files: 13/13 sha256 equal to the Phase 1-B baseline, both before and after reading (Golden summary, five results, five traces, `golden-set.json`, TC `run.json`).
- History projection matches expectations:
  - RF-01 and RF-03: BLOCKED / oracle NOT_EVALUATED / E2E FAIL.
  - RF-04: FAILED / NOT_EVALUATED / FAIL.
  - RF-02 and RF-05: COMPLETED / PASS / PASS.
  - The legacy `F-GOAL-SUBSTITUTED` label stays only in `legacy`.
- Manifest: all recorded hashes match. However, `read_run` checks only `config_sha256`. A `result.json` edited after the manifest still reads as FINISHED with config verified, and the edited verdict is returned.

## 6. Open issues

Blocking Phase 2:

- RF-04 `must_forbid` is not a required evaluator and can produce a false E2E PASS (section 3).

Deferrable:

- `read_run` does not verify case or summary hashes from the manifest.
- REQ-0133 exposes user query text in the observability detail, against the existing privacy test. This is a product privacy issue, so it should be decided soon even though it does not block the evaluation contracts.
- REQ-0126 left Run Explorer tests red. The tests and the route need a decision.
- Phase 1-B limitations still apply: no TC config or manifest, `agent_version` is null, TIMEOUT is inferred only from an unsettled status.
