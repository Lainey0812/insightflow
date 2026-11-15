evaluation-quality-gates-v1 (Phase 1-D) for REQ-0143.
Added MustForbidEvaluator (insightflow.golden.must_forbid, must-forbid-v1) with versioned adapter golden-forbid-adapter-v1 (RF-04 items 0-3 rule, item 4 clarification, pinned by text sha256); registered required_when_applicable.
Removed RF-04 salary branch from oracle (golden-oracle-v2).
Added manifest integrity (VERIFIED/INVALID/INCOMPLETE/UNVERIFIED) with path containment and trusted_metrics.
Updated two Phase 1-B test expectations; added 22 tests.
Tests: 32 evaluation tests pass; full backend 1724 passed, 1 pre-existing failure (REQ-0133).
Acceptance: 37 PASS / 0 FAIL / 1 INFO. History 13/13 hashes unchanged.
Consequence: RF-01/02/03/05 must_forbid items are not adapted, so new runs give them E2E NOT_EVALUATED at best.
