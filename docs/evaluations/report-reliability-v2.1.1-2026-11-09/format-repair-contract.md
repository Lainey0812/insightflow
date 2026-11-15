# Final exact-reference format patch

V2.1.1 fixed-upstream R05 generated the exact list [E0027, E0024, E0027]. Retain that raw failure. The final patch normalizes exact duplicate identifiers without modifying the raw Draft. It does not add references, change primary/type/recommendations, combine fields, change numeric values, or accept unknown references. Full source/type/option/limitation checks still run; only after all pass is the repair marked validated and recorded in candidate_repairs/Trace. This is not a model retry or numeric repair.

Run the four exact historical inputs once again under fixed-upstream-release/, with new isolated Registry files. Keep prior fixed-upstream/ and the fresh ten-case candidate-v211-01 results intact. The most recent full-chain case S03 contains pre-validated F0 tasks skipped by Engine; its partial_success and partial report remain an unresolved upstream finding. Do not overwrite it with another fresh plan to claim a perfect full-chain score.
