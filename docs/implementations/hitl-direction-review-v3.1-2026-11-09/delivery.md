# HITL V3.1 — Direction-first review

Date: 2026-11-09 (Asia/Shanghai). Requirement: REQ-0102, related REQ-0101. The user confirmed simplifying review around whether the proposed analysis directions are correct.

## Delivered behavior

The default review now asks “这些分析方向符合你的需求吗？” and contains: core objective, uploaded data, business directions, actual confirmation issues, and confirmation controls.

The independent “分析范围与统计口径” list and repeated global metric definitions are removed from the default view. Each business direction has a collapsed “查看计算说明” containing its original step descriptions and only its own saved metric definitions. No definitions are deleted from the plan or approval snapshot. Original user-specified time, filter, metric and output constraints remain visible under the data overview with their existing verification status. Only plan-derived repetitions and the explicit empty-request placeholder are omitted there.

Actual filter conditions remain visible per direction. A small pure presentation helper reads the saved controlled steps and original field labels; it tracks intermediate aliases only for naming filters. It distinguishes input-data filters from filters applied after aggregation/Top N. Unsupported steps, missing steps or unknown references produce explicit uncertainty instead of an invented all-records scope. “No additional filter configured” is not an effective-row count or a claim of clean/valid data.

Uploaded-data cards and real quality checks remain. Optional grain declaration is accessible through one collapsed control, without imposing a new artificial approval prerequisite. Server issues, task gaps, partial-coverage acknowledgements and unexecutable directions remain visible. Supported report batching estimates move into technical details; an unsupported-capacity message stays visible and remains blocked by existing server eligibility.

Existing direction editing, deletion confirmation, immutable plan versions, stale-version guards and server-authorized approval are unchanged. Editing or a pending deletion still disables confirmation. The frontend does not resolve uncertainties, alter metrics, reinterpret user constraints, or run new analysis.

## Files and scope

Five files changed; see changed-files.json. Before source: before.zip. After source: after.zip. No backend, API, database schema, Prompt, model parameter, Admin page, Engine or Reporting file changed. The source helper is presentation-only and never modifies a task or substitutes for Validator. No new model call was made. Historical plans/reports/archives were not overwritten.

## Validation

- Frontend full suite: **93 passed**, 10 test files, 3.23 seconds (req102-frontend-v2.log).
- Frontend TypeScript and Vite build: passed (req102-build-v2.log).
- Backend related HITL/basis tests: **51 passed**, 4.71 seconds (req102-backend-review.log). Existing Starlette/httpx deprecation warning remains. The full backend/Admin suites from REQ-0101 are not represented as rerun in this UI-only change.
- New tests cover hidden computation text, visible blocking gaps, retained explicit time/exclusion/Top N conditions, task-specific filter display, input versus result filtering, unknown operations and missing field references.
- Existing tests continue covering server denial, warnings, old-version responses, edit/save callbacks, deletion confirmation and grain declaration. The supported capacity assertion now verifies that its text is hidden until technical details expand; unsupported capacity remains visible.

## Browser verification

Used the user's existing localhost session in read-only/cancel-only mode. The same actual four directions are displayed. Four “查看计算说明” disclosures start collapsed. The removed global block has zero matches. Data cards retain 60 uploaded rows, 12 fields, 0 missing cells and 0 suspected duplicates. Expanding the first direction shows its existing calculations; collapsing hides them again. Opening the existing edit form disables approval; cancel restores the unchanged review. No save, approval, execution or new model request was performed. Browser error-level log list was empty.

Screenshots: directions-default.png, calculation-expanded.png and direction-controls.png. The last shows a direction together with its preserved edit/delete controls.

## Intermediate failures retained

An initial build command used the repository root instead of frontend; its ENOENT output is retained as req102-build-initial.log. A subsequent file-edit batch also used frontend as its working directory while referring to frontend-prefixed paths, so no edits in that batch occurred. The test run consequently used the old assertions and reported 4 selector/visibility failures (req102-frontend-v1.log). The working directory and expected presentation contract were corrected, and new visibility/safety tests added; final tests and build passed. No approval or business rule was relaxed to resolve these failures.

## Limits

This improves review presentation; it does not introduce new business ambiguity detection, semantic metric validation, automatic cleaning or natural-language plan rewriting. Previously identified issues such as month-only grouping across years are not silently changed. Existing actual blockers continue to govern whether analysis can start. No new Workflow lifecycle/state authority or trace hierarchy was introduced.
