Phase 1-B evaluation contracts v1 for REQ-0141.
Added backend/app/evaluation/{contracts,protocol,aggregate,metrics,evaluators,projection,manifest,golden_run,runs}.py and backend/tests/test_evaluation_contracts.py.
Modified backend/scripts/run_golden_fidelity.py to write run-config.json before and run-manifest.json after a run; before-copy under docs/implementations/evaluation-contracts-v1-2026-11-13/before/.
Tests: new 10 passed; full backend 1702 passed, 1 pre-existing unrelated failure (test_failure_diagnosis user goal leak); Admin traces/comparison failures pre-existing from REQ-0126 /traces redirect.
History: 13 historical files sha256-checked before and after, all identical.
Real Golden runner not executed. Details in NOTES.md.
