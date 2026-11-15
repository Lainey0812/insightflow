# Preserved V2.1 intermediate outcome

The fresh full-chain run had 9 complete reports + 1 expected stop, but fixed original upstream inputs exposed 2 partial reports: P03 recommendation binding mismatch; R05 cross-metric evidence composition with missing salary interpretation. These are real safety rejections, not false positives. The initial fixed-upstream runner also had a log-query scope defect after T01 had already generated successfully; T01 records were recovered by exact persisted Call IDs without another model call.

A second targeted implementation revision binds primary/type/evidence_refs/recommendation together per actual same-source metric group in Schema. No dynamic repair, validator relaxation, KPI deletion or retry loop. Keep V2.1 candidates and all raw outputs unchanged; new runs use new directories and versions.
