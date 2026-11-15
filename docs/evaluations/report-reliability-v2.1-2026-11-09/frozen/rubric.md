# Frozen acceptance rules

Frozen before real calls on 2026-11-09, REQ-0103. Four domains × goal-driven/exploratory, plus clarification and unsupported-core boundaries: 10 cases. CSVs are synthetic business fixtures inherited unchanged from the preserved earlier suite, not real enterprise datasets. Six non-boundary base cases are historical regressions; R05/T05 are new exploratory requests, not an independently blinded model-quality set.

For each case retain user input, model requests/responses, saved Intent, plan and validation, HITL review/approval, complete execution, report, presentation, Trace and model-call records. No mock model, no manual plan replacement, no changed business rules and no outer retry. Each node may use its existing configured bounded retries. Execution is withheld if independent business oracle or service eligibility fails.

Goal-driven cases must preserve all explicit filters, metrics, grouping, sorting, Top N and exclusions, with independently calculated Pandas results. The inherited runner uses exact input-row membership as well as final metric comparisons. Execution must reject before approval, compute the saved approved plan correctly, and replay idempotently.

Exploratory cases must be recognized exploratory; agent review separately assesses whether each direction is relevant to the dataset, distinct and understandable, whether its proposed calculation supports its question, whether scope is preserved, and whether there are unresolved material assumptions. Schema and Validator pass do not prove business value.

Reports: compare execution to independent computation, require valid evidence references, distinguish full versus partial report status, check coverage and rejected candidates. Facts must not invent data, causes, profit or population shares. Each executed direction must be represented or explicitly disclosed as uncompleted. A readable persisted report and its presentation must be available. Model/API failures, approval blocking and report failure remain failures or unavailable; never turn these into success by retries.

Expected stopping cases: R03 must clarify, then use the stated answer and proceed; S04 must not execute unsupported profit analysis. Expected safe stopping is reported separately from report delivery.

Statuses: complete (all automated gates and agent review satisfied), partial (valid calculation/report but missing core report coverage or partial result), failed (logic, approval or delivery mismatch), unavailable (model/transport or unavailable output), expected_stop (boundary safely blocked), runner_error (harness defect, distinct from product). A pending agent review remains pending, not complete. Ordinary-user usability requires a real user trial and is not claimed by this agent-run test.

Existing automated HITL tests cover versioned editing/deletion, approval invalidation and server blocks; this runner does not modify real generated plans or claim those actions were exercised against the model in all 10 runs. Browser verification uses actual persisted records from the running frontend separately. No production sample or API key is included.
