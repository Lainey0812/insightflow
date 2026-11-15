# Evaluation quality gates v1 (REQ-0143, Phase 1-D)

Date: 2026-11-13. Fixes the two gaps found in Phase 1-C (REQ-0142):

- RF-04 `must_forbid` was not an independent required check.
- `read_run()` verified only the config hash.

Agent, Planner, Engine, HITL, the Golden Set file, Oracle expectations, the TC runner, the database and Admin were not changed.

## Files

New:

- `backend/app/evaluation/forbid_rules.py`: versioned adaptation table (`golden-forbid-adapter-v1`) and `adapter_sha256()`.
- `backend/app/evaluation/must_forbid.py`: `MustForbidEvaluator` (`insightflow.golden.must_forbid`, `must-forbid-v1`).
- `backend/app/evaluation/integrity.py`: manifest verification and path containment.
- `backend/tests/test_evaluation_quality_gates.py`: 22 tests.

Modified (before-copies in `before/`):

- `contracts.py`:
  - added `Requirement`, `IntegrityStatus`, `FileCheck`, `IntegrityReport`;
  - added `EvaluationRun.integrity`;
  - added `EvaluatorRef.requirement`.
- `protocol.py`:
  - `run_evaluator` accepts `required` as a bool or one of `required`, `optional`, `required_when_applicable`;
  - under `required_when_applicable`, a not-applicable result is recorded with `required=False`;
  - if `applicable()` raises, the result stays required.
- `evaluators.py`:
  - the RF-04 salary branch was removed from `GoldenOracleEvaluator` and the version became `golden-oracle-v2`;
  - the city-count rules are unchanged.
- `golden_run.py`:
  - the default evaluators are oracle (required), must_forbid (required when applicable) and node fidelity (optional);
  - the config records `requirement` per evaluator;
  - `execution_steps` is now kept in the observed record and passed as evidence, together with `dataset_id` and evidence refs.
- `runs.py`:
  - recorded runs carry an `IntegrityReport`; legacy Golden runs and TC runs are UNVERIFIED;
  - unreadable case results are reported instead of raising;
  - added `trusted_metrics(view)`.
- `tests/test_evaluation_contracts.py`: two Phase 1-B expectations updated to the new behaviour.
  - The oracle no longer judges salary use.
  - The config lists three evaluators.
  - RF-02 and RF-05 are E2E NOT_EVALUATED in the scripted run, because their `must_forbid` items have no verified adaptation.

`metrics.py` and `manifest.py` were snapshotted but not changed.

## MustForbidEvaluator

Rules are resolved from two sources:

- **Structured rules:** `case['forbid_rules']`, used as given.
- **Natural-language items:** `case['must_forbid']`, looked up in the adaptation table by dataset id, case id, list index and the SHA-256 of the exact sentence.
  - An item is adapted either as `rule` (pointing to an entry in `RULES`) or as `clarification`.
  - A missing entry, or a changed sentence, means the item is not adapted.

No case id appears in evaluator code.

For RF-04, items 0 to 3 map to `forbid-salary-field`. Item 4 ("the sentence 不要分析薪资 in plan text is not salary analysis") is a clarification: plan text is never scanned.

The `forbid-salary-field` rule:

- **Kind:** `forbid_field`.
- **Scopes:** plan, engine, result_columns.
- **Failure code:** `F-METRIC-SUBSTITUTED`, the same code the legacy check used.
- **Matching:** identifiers are normalized (NFKC, casefold, whitespace, `_`, `-` and `.` removed), then compared with:
  - names: 薪资, 薪资区间;
  - aliases: salary, salary_range, 薪水, 工资;
  - one pattern for aggregate names such as 平均薪资, avg_salary or salary_median.

Evidence by scope:

- **plan:** structured references in `plan.tasks[].steps[].params`:
  - direct keys `field`, `fields`, `dimensions`, `alias`, `column`, `columns`, `group_by`, `by`;
  - `field` and `alias` nested inside `conditions` and `metrics`.
  - A field id is also resolved to its profile display name. A reference that is not in the profile is still matched by its own name.
- **engine:** `execution_steps` reported by the engine, joined to plan steps by `(task_id, step_id)`. The engine's step log has no field list of its own.
- **result_columns:** keys of every row in `result_tables`.

Verdict order:

1. **FAIL:** any forbidden identifier is found in any scope, even if other evidence is missing or other items are unadapted.
2. **NOT_EVALUATED:** any of the following holds.
   - An item is not adapted.
   - A rule kind is unknown.
   - Plan or profile is missing.
   - The engine ran but `execution_steps` is missing, or a step cannot be mapped to the plan.
   - The engine reported success but no result columns exist.
   - The status is unknown and there is no engine evidence.
   - Engine evidence is not required when the execution is BLOCKED, FAILED, TIMEOUT or CANCELLED and the engine never ran.
3. **PASS:** otherwise. The reason lists the scopes actually checked.

Exceptions become EVALUATOR_ERROR with no failure code.

The evaluator config contains the adapter version, the adapter hash, the rules and the adaptation table, so the config hash in `run-config.json` identifies the exact rule set.

Consequence: every Golden case declares `must_forbid`, but only RF-04's items are adapted. RF-01, RF-02, RF-03 and RF-05 describe outcome constraints such as exclusion polarity and city coverage, not forbidden fields. In new runs, must_forbid for those cases is NOT_EVALUATED, so a completed RF-02 or RF-05 with a correct oracle result is E2E NOT_EVALUATED, not PASS. Changing this requires an explicitly verified adaptation for those items.

## Manifest integrity

`verify_recorded(run_dir, config)` produces the run status:

- **INCOMPLETE:** no manifest.
- **INVALID:** the manifest is unreadable.
- Otherwise every listed file is checked:
  - config at `run-config.json`;
  - summary at `summary.json`;
  - each case's `result.json` and `trace.json` at the canonical path `<case>/<file>`;
  - any entry in an optional `artifacts` list.

Each file check yields one of:

- `outside_run`: the ref is absolute, contains `..`, or resolves outside the run directory (including through symlinks);
- `unexpected_ref`: the ref is not the canonical path for its role;
- `missing`;
- `mismatch`;
- `ok`.

The manifest's run id and schema must match, and its case ids must equal the config's case ids. Any problem makes the run INVALID. A missing file is INVALID because the manifest claims completion.

Per-case status is VERIFIED only if the config, the run-level artifacts and both of the case's files verified.

Nothing is rewritten or repaired. An edited result is still returned as read, with its case marked INVALID.

`trusted_metrics(view)`:

- VERIFIED runs: uses every case.
- INVALID runs: uses only the VERIFIED cases, and lists each excluded case with reason `evidence_integrity_invalid`.
- INCOMPLETE and UNVERIFIED runs: returns metrics labelled with that status.

## Verification

- `cd backend && ../.venv/bin/python -m pytest tests/test_evaluation_quality_gates.py tests/test_evaluation_contracts.py -q`: 32 passed.
- Full backend `-k 'not test_git_unknown'`: 1724 passed, 1 failed. The failure is `test_failure_diagnosis.py::test_success_has_no_failure...`, attributed in REQ-0142 as PRE_EXISTING from REQ-0133.
- Acceptance script `docs/evaluations/evaluation-quality-gates-phase1d-2026-11-13/verify_phase1d.py`: 37 PASS, 0 FAIL, 1 INFO.
- History: 13/13 sha256 equal to the Phase 1-B baseline. No file under the historical Golden runs, the TC runs or the Phase 1-C evidence directory changed.
