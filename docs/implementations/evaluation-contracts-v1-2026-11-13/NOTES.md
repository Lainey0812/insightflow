# Evaluation contracts v1 (REQ-0141, Phase 1-B)

Date: 2026-11-13. Scope: unified evaluation data contracts, Evaluator protocol, read-only adapters for historical Golden and TC runs, write-once Run Config Snapshot and Final Manifest for new Golden runs, aggregation and metric functions. Agent, Planner, Engine, HITL rules, Golden Set, Oracle expectations, TC runner behaviour, database schema and Admin pages were not changed.

## Files

New, under `backend/app/evaluation/`:

- `contracts.py`: `EvaluationRun`, `CaseExecution`, `EvaluatorResult`, `E2ESummary`, `Derivation`, `EvaluatorRef`, and the status literals. All models are frozen Pydantic models with `extra='forbid'`.
- `protocol.py`: the `Evaluator` protocol, `EvaluationEvidence`, `Outcome`, `config_hash`, and `run_evaluator`, which turns exceptions into `EVALUATOR_ERROR`.
- `aggregate.py`: `task_condition` and `summarize` (the E2E hard gates).
- `metrics.py`: `ratio` and `compute`. A zero denominator yields `None`.
- `evaluators.py`: `GoldenOracleEvaluator` (required) and `RequirementFidelityNodeEvaluator` (optional).
- `projection.py`: derives the execution status, blocking stage and failure origin from recorded facts, with the sources listed.
- `manifest.py`: `write_once` (temp file, fsync, `os.link`, which fails if the target exists).
- `golden_run.py`: `run_golden`, the Golden runner integration that writes the config, per-case v2 results, a v2 summary and the manifest.
- `runs.py`: `read_run`, `read_golden_run`, `read_regression_run`, returning `RunView`.

Modified: `backend/scripts/run_golden_fidelity.py` now delegates to `run_golden`. The before-copy is in `before/backend/scripts/run_golden_fidelity.py`. The case execution path (`run_case`) is unchanged.

Tests: `backend/tests/test_evaluation_contracts.py` (10 tests, fixtures and temp dirs only, no model calls).

## Status model

`CaseExecution.execution_status` is one of PENDING, RUNNING, WAITING_APPROVAL, COMPLETED, BLOCKED, FAILED, TIMEOUT, CANCELLED, or `None` when it cannot be derived. Terminal statuses are COMPLETED, BLOCKED, FAILED, TIMEOUT, CANCELLED. WAITING_APPROVAL is a live pause and is never produced from files; a finished run that stopped at a gate is BLOCKED with `blocking_stage` set (`hitl_approval` or `clarification`).

`failure_origin` separates `agent` failures from `infrastructure` failures (runner errors and LLM-unavailable error codes).

## Mapping of historical runs

Historical runs are only read. Nothing is written back.

Golden `gf_*` without `run-config.json` is a legacy projection:

- `provenance='legacy_projection'`; `agent_version`, `evaluator_manifest` and evaluator versions stay `None`.
- `dataset_id` is filled only if the current `golden-set.json` hash equals the summary's `golden_sha256`.
- Fields the old files never recorded (execution id, attempt, start and finish times, output ref) are listed in `unverified`.
- The execution status is derived by `projection.classify` from `result.json` and `trace.json#business_lifecycle.status`. Each derived value carries a `Derivation` with its sources. A missing or unreadable trace leaves the status `None`; it is never guessed as BLOCKED.
- The old verdict maps to evaluator `insightflow.golden.score_case`: `passed` is PASS; reason `no_execution_result` is NOT_EVALUATED (`no_engine_result`, no failure code); other failures are FAIL with the original code. The raw verdict, including the old `F-GOAL-SUBSTITUTED` label, is kept under `legacy` and never copied into `failure_code`.

Golden runs with `run-config.json` are read as `recorded`. A manifest means FINISHED; otherwise INCOMPLETE with `missing_case_ids`.

TC `rg_*`: `run.json` means FINISHED; `run-start.json` alone means INCOMPLETE. `not_run` cases go to `not_started_case_ids` and get no execution. A `stopped` check marks `expect_blocked`. The legacy evaluator is `insightflow.tc.checks`: passed is PASS, failed is FAIL with `check:<key>`, needs_review and blocked are NOT_EVALUATED. Runner errors become infrastructure failures and E2E INFRA_ERROR.

Results against the real history: RF-01 and RF-03 are BLOCKED at `hitl_approval` with oracle NOT_EVALUATED and E2E FAIL; RF-04 is FAILED at `analysis_planner` (`PLANNER_BUSINESS_INVALID`), oracle NOT_EVALUATED, E2E FAIL; RF-02 and RF-05 are COMPLETED, PASS, PASS. TC02 of `rg_20261112-133157_f04289` is COMPLETED and PASS; the other 14 cases are not started.

## E2E hard gates

Applied in order by `summarize`:

1. Infrastructure failure: INFRA_ERROR.
2. Task condition not met: FAIL. The condition is COMPLETED, or BLOCKED when the case expects a block. A non-terminal or unknown status is not a failure; it falls through to NOT_EVALUATED.
3. Any required evaluator FAIL: FAIL.
4. Any required evaluator EVALUATOR_ERROR: EVALUATOR_ERROR.
5. Unknown or non-terminal status, any required evaluator NOT_EVALUATED, or no required evaluator: NOT_EVALUATED.
6. Otherwise PASS.

Optional evaluators are reported in `optional_verdicts` and never change the verdict.

Differences from the Phase 1-A design: E2E gained INFRA_ERROR; a confirmed FAIL is ranked above EVALUATOR_ERROR; the Golden oracle keeps the original rule that the engine status must be exactly `success`.

## Golden oracle adapter

`GoldenOracleEvaluator` reuses `_exact_oracle`, `_matches` and `salary_executed` from `golden_fidelity`. RF-04 with a salary field in the plan is FAIL `F-METRIC-SUBSTITUTED` (unchanged rule). Without a successful engine result it returns NOT_EVALUATED with reason `no_engine_result` and no failure code. With a result: an exact oracle match is PASS, a matching error control is FAIL with that control's code, anything else is FAIL `F-ORACLE-MISS`. `run_evaluator` drops any failure code returned with a non-FAIL verdict.

## Manifest behaviour

`run_golden` writes `run-config.json` (schema `evaluation-run-config-v1`) before the first case: dataset id, version, ref and sha256, case ids, evaluators with config hashes, agent `{id: insightflow, version: null}`, model settings (endpoint stored as a hash), environment and policy. After each case it writes `trace.json` and `result.json` (schema `golden-fidelity-case-v2`). After the last case it writes `summary.json` (schema `golden-fidelity-run-v2`) and then `run-manifest.json` (schema `evaluation-final-manifest-v1`): status FINISHED, config and summary sha256, per-case result and trace refs with sha256, and observed prompt snapshot ids.

Every file is write-once. An interrupted run keeps the config and the cases already written, has no manifest, and reads back as INCOMPLETE with the missing case ids. There is no resume: a rerun starts a new run directory.

## Verification

- `cd backend && ../.venv/bin/python -m pytest tests/test_evaluation_contracts.py -q`: 10 passed.
- Full backend `../.venv/bin/python -m pytest -q -p no:cacheprovider -k 'not test_git_unknown'`: 1702 passed, 1 failed, 1 deselected. The failure (`test_failure_diagnosis.py::test_success_has_no_failure_and_records_inputs_without_user_text`, user goal text found in the intent parser input record) is in code this change does not import or touch.
- Admin `npx vitest run` on workflows, golden-set, traces and comparison: workflows and golden-set pass. traces (9) and comparison (1) fail because the exact `/traces` route was redirected to the Workflow list in REQ-0126, which was accepted then. Not caused by this change.
- History: sha256 of the historical Golden summary, five results, five traces, `golden-set.json` and the TC `run.json` were recorded before the change and checked with `shasum -a 256 -c` afterwards: 13/13 OK, and no file in either run directory is newer than the baseline.

## Limitations

- The real Golden runner was not executed (it calls the real model). The integration is covered by a scripted `run_one` in tests.
- `agent_version` is null for new runs because the agent has no version identifier yet.
- TC runs gain no config snapshot or manifest, because the TC runner may not be changed in this phase.
- TIMEOUT is inferred only from an unsettled final status; WAITING_APPROVAL, PENDING, RUNNING and CANCELLED are defined but not produced from files.
- Nothing is exposed through the API or Admin yet.
