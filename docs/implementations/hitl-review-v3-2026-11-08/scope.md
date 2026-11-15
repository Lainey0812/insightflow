# HITL Review V3 implementation scope

User approved the preceding review layout and edit/delete reapproval rules. Original request: REQ-0101.

The review remains in the conversation. Order: goal, actual profile overview, range and metrics, directions, unresolved issues, approval. Actual profile counts use explicit units (rows/fields/cells). Missing cells are never presented as invalid rows. No automatic cleaning is added; planned filters and missing-value aggregation policies are shown, with affected sample counts deferred to real execution.

Edits are bounded structured changes to existing steps (grouping, aggregation, filter, order/top N and supported date extraction), with unchanged task identity, priority and core requirement bindings. The original Intent constraints are retained and checked against the revised steps; conflicting changes remain blocked. Different goals require a new request. Every edit/delete creates an immutable version, invalidates approval, reruns Validator, and requires a fresh review. No natural-language AI revision, new LLM node, or execution change.

UI uses existing green (#187b61), white (#ffffff), ink (#20352e), light neutral (#f4f7f5), amber (#9a6700). Existing font stack. Full-width goal followed by compact data cards and business questions; editable controls open inline, with concise blocking information and collapsed technical details. Preserve the existing chat layout rather than rebuilding application chrome.
