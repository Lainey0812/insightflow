# Explicit text scope confirmation V1

REQ-0105 preserves the user's choice to include AI product manager title variants. Prior question: exact title has 20 matching records; user wants parentheses, case and whitespace variants included.

Implement a generic, explicit text-field scope confirmation, not a job-specific rule or LLM semantic extraction. Preview normalization: Unicode NFKC, casefold, remove whitespace, then literal substring. Preserve original distinct source values and compile them into the existing Engine in filter. No data cleaning, no regex/dynamic code from user, no fuzzy synonyms. Read only the exact dataset version through existing DatasetLoader/FileStore integrity checks. Do not send source records to a model.

Only refine an existing positive singleton eq/in scope whose original unresolved filter text equals the keyword and whose target field is consistent in every task. Preserve all other constraints, tasks, operation order and metrics. Save creates immutable PlanVersion with a user-confirmed canonical finite JSON filter expression, typed and deterministically verified by ConstraintAuditor; retain old intent/plan, clear approval and require new user approval. Unsupported scope, extra same-field restrictions, stale revision/dataset, no matches or oversized enumeration are explicit errors. No new DB table, Workflow Switch or Engine operation.

UI offers read-only preview (counts, exact matched values and rule) and a separate save-for-review button. Saving is not approval or execution. Display business summary instead of raw JSON. The user has selected variant inclusion; applying that choice to the current session is authorized, but final execution confirmation remains for the user.
