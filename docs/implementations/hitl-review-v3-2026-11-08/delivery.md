# HITL Review V3 — delivery and verification

Requirement: REQ-0101. Date: 2026-11-08. This delivery changes the end-user InsightFlow review, not Admin. The original request, before/after source archives, intermediate failures, and final verification records are retained. No historical report, approval or plan payload was replaced.

## User-facing structure

1. Core goal and coverage; revised plans show their change summary.
2. Actual dataset overview: file/sheet, uploaded rows, columns, missing cells, suspected duplicate rows. Missing-field and quality notes expand on demand.
3. Original conditions and actual proposed grouping/metric/sort definitions with their existing verification status.
4. Business analysis directions, priority labels, readiness and gaps; inline editing and deletion confirmation.
5. Unresolved issues and acknowledged limitations; original blockers remain in force.
6. Server-authorized approval and execution; technical plan/version/proof records remain collapsible.

No missing-cell count is converted into an invalid-row count. Effective task samples are computed during execution; pre-execution counts are not invented. The profiler does not automatically clean data. The review states that no automatic fill/delete/dedup has occurred, and shows planned filtering separately. No cleaning service, new model node, natural-language revision, or new analysis method was added.

## Editing and version rules

Existing task steps can be edited through their supported parameter schemas: existing filter fields/operators/values, grouping slots, metric fields/functions, sort fields/directions, Top N and supported year/month extraction. New steps/tasks, changed goals, new statistical assumptions and unresolved semantics require a new explicit request. Task identity, priority, requirements, original Intent constraints and dataset references cannot be replaced by the new edit request.

Save runs the existing deterministic PlanValidator, persists a new immutable PlanVersion and basis sidecar atomically, clears the active approval, and requires another review. A type-incompatible but schema-valid task remains visible as F0 with unmet requirements; it is not deleted. Constraints incompatible with the original request remain approval blockers. Saving is not execution. Stale revisions fail without adding a version. Unsupported parameters return an explicit error and roll back.

Deletion requires an explicit confirmation, warns for core directions, produces a new version and revalidates coverage. Editing, deletion confirmation and pending save disable approval. Completed plans have no new edit/delete controls in the UI. The existing legacy API deletion-after-completion path remains compatible, including its lifecycle association behavior; this feature does not broaden Root state transitions.

## API and compatibility

Reuse `POST /api/v1/sessions/{session_id}/plan-revisions` with existing session authentication:

```json
{
  "expected_revision": 4,
  "plan_id": "saved-plan-id",
  "plan_version": 1,
  "task_edits": [{
    "task_id": "A03",
    "step_params": {"S01": {"metrics": [{"function": "avg", "field": "field_0003", "alias": "total"}]}}
  }]
}
```

This is illustrative only; fields and aliases must come from the actual saved plan. Original removal payloads still work. No new database table or migration. Public `PlanVersion.change_type` now permits `tasks_edited`; strict older readers need this compatible enum addition before rollback. ReviewPresentation adds optional `data_overview`, containing only metadata/counts and quality notes, not raw sample rows. Historical missing metadata is explicitly unavailable.

Prompt text/model/parameters are unchanged. Because Report registry snapshots track the review presentation source, the composition source version is bumped to `composition-v0.9-hitl-review-v3`, preventing changed source from being registered under an immutable older template version. Older snapshots remain intact.

## Files

Full list: `changed-files.json` (13 files). Before archives: `before.zip`, `before-extra.zip`. New component: DirectionEditor. New tests: test_review_v3. Existing HITL deletion UI test now confirms the explicit deletion dialog before expecting the existing removal callback.

## Actual verification

- Backend full suite: **1619 passed**, 88.64 seconds (`req101-backend-final-v2.log`). Existing Starlette/httpx deprecation warning remains.
- Frontend: **86 passed**, TypeScript/Vite build passed (`req101-frontend-final-v3.log`, `req101-frontend-build-final-v3.log`).
- Admin unchanged: **88 passed**, TypeScript/Vite build passed (`req101-admin-test.log`, `req101-admin-build.log`).
- Four domains use actual uploaded synthetic CSVs: sales, recruitment, service tickets and project tasks. Each verifies 4 rows, 1 missing cell, 1 duplicate row, and a real changed aggregation/new version. These are deterministic API integration tests, not four real-LLM quality evaluations.
- Live local API: session `268a49e8de164f7db660903f96f8cd6d`. Real example CSV, human-constructed plan, no model calls. v1 approval persisted; A03 aggregation changed to avg producing v2 and clearing approval. Old execution request rejected HTTP 409. A03 removed producing v3. All three immutable versions readable; v1 payload equals the original. Full non-secret records: `live-api.json`.
- Browser: actual current sales review shows 60 uploaded rows, 12 columns, 0 missing cells and 0 suspected duplicate rows. Inline grouping/metric controls load. Approval disables while an editor or deletion decision is open. Cancel restores review without altering the user's plan. No error-level browser console records. Final screenshots: `review-data-overview-final.png`, `review-edit-direction-final.png`. Browser inspection did not save or approve changes to the user's existing plan.

## Preserved failures and corrections

1. Initial new constraint test changed count() to avg() without supplying a field. Registry correctly rejected it. Fixture corrected to select a real numeric field; validation was not weakened. `req101-targeted.log` retained; corrected targeted run: 17 passed.
2. First full regression identified the existing completed-plan deletion API compatibility path. The new guard was narrowed to new structured edits; the legacy lifecycle test remains unchanged. The complete original lifecycle scenario passes.
3. Second full run hit the existing millisecond Planner deadline test (one rather than two requests before its shared deadline). No Planner code/test/timeout was changed. Isolated recheck passed, and the final full suite passed. All failing logs retained; success is not substituted for those earlier runs.

## Remaining boundaries

- No full natural-language plan rewrite, new goal in place, new operations, new filter step insertion, unit/currency/formula editor, automatic cleaning, or arbitrary task creation.
- Original constraint mapping gaps and report candidate rejection from REQ-0100 are not solved by a presentation change.
- Schema/field/type validation does not prove that an edited calculation fully captures every business intent. Original question remains the target; actual revised calculation is explicit. Core requirement IDs are retained and constraint auditing continues to block detected conflicts.
- New sidecars and versions remain Session-scoped as in the existing single-workflow path; no Workflow Switch/multi-workflow release.
- The dedicated live API verification uses manual plan submission and does not claim a new end-to-end real-LLM run. Engine/Reporting and Admin business logic remain unchanged.
