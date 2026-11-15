# Phase 2-C1 evidence (REQ-0153)

Admin evaluation pages: Dataset list and detail, Evaluation Runs, Run Detail, and a Case Detail placeholder. All pages are read-only and call the real B1/B2 API through `admin/src/api/evaluations.ts`.

## Files in this directory

| File | Content |
|---|---|
| `vitest-before.txt` | Admin vitest before the change: 10 failed / 109 passed (the 10 REQ-0126 failures in `traces.test.tsx` and `comparison.test.tsx`) |
| `vitest-after.txt` | Admin vitest after the change: the same 10 failures / 138 passed |
| `vitest-c1-verbose.txt` | Verbose run of the C1 tests plus regression, navigation, routes and workflows suites |
| `typecheck.txt`, `build.txt` | `tsc --noEmit` exit 0; `vite build` exit 0 (output written to /tmp, the existing `admin/dist` was not touched) |
| `live_contract.test.ts`, `live-contract-result.json` | Live check through the Admin dev proxy (127.0.0.1:5174 → 8000) using the pages' `evaluationApi`; field sets compared with `admin/src/types/evaluations.ts` |
| `screenshots/` | Pages rendered against the running backend |
| `history_snapshot.py`, `history-before.json`, `history-after.json`, `history-check.txt` | Path, size, mtime and SHA-256 of 58 historical files before and after the live check: unchanged |
| `source-diff.txt` | Diff of the edited existing files against `docs/implementations/evaluation-admin-c1-2026-11-13/before/`; no `/traces` route line changed |

## Decisions recorded here

1. The run list API has no E2E metric field. The list shows "列表接口不提供，进入详情查看" instead of deriving a value.
2. `CaseSummary` in the run detail API has no per-case evaluator verdicts. The Case table does not show them; evaluator verdicts appear per evaluator in the run-level distribution (`metrics.evaluators[].counts`). RF-04's Oracle NOT_EVALUATED is therefore visible as part of the Oracle's `NOT_EVALUATED 3` count, not on the RF-04 row. Per-case verdicts belong to Case Detail (Phase 2-C2).
3. `ApiError` gained optional `serverCode` and `details`, read from the `{"error": {...}}` body, so 409 conflicts can be told apart. The server message is not displayed.
4. The bundled `golden-set.json` content is shown inside the golden dataset detail only when the API reports the same SHA-256 (`fe52a92c…`).
5. The running 8000 process uses its own data directory; its TC root does not exist (`root_unavailable` warning), so the live check saw only the two golden runs and `typical-suite-v1` with 0 related runs. The TC run detail page is covered by tests using the real B2 response body for `rg_20261112-133157_f04289`.
