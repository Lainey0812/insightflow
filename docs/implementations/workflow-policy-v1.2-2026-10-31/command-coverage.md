# V1.2 33个检查点覆盖

31条继承命令+C19-A/C19-B，均为合成领域事实，不代表已接入生产。

| 检查点 | owner | 前态 | 后态 | 实际决策 |
|---|---|---|---|---|
| C01 | control | CREATED | PROFILING | allow / POLICY_ALLOWED |
| C02 | control | PROFILING | PARSING_INTENT | allow / POLICY_ALLOWED |
| C03 | control | PARSING_INTENT | PLANNING | allow / POLICY_ALLOWED |
| C04 | control | PARSING_INTENT | WAITING_FOR_CLARIFICATION | allow / POLICY_ALLOWED |
| C05 | control | WAITING_FOR_CLARIFICATION | PARSING_INTENT | allow / POLICY_ALLOWED |
| C06 | control | PLANNING | VALIDATING | allow / POLICY_ALLOWED |
| C07 | control | VALIDATING | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C08 | control | AWAITING_APPROVAL | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C09 | control | APPROVED | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C10 | control | AWAITING_APPROVAL | APPROVED | allow / POLICY_ALLOWED |
| C11 | control | APPROVED | RUNNING | allow / POLICY_ALLOWED |
| C12 | control | RUNNING | COMPLETED | allow / POLICY_ALLOWED |
| C13 | control | RUNNING | COMPLETED | allow / POLICY_ALLOWED |
| C14 | control | RUNNING | FAILED | allow / POLICY_ALLOWED |
| C15-CREATED | control | CREATED | FAILED | allow / POLICY_ALLOWED |
| C15-PROFILING | control | PROFILING | FAILED | allow / POLICY_ALLOWED |
| C15-PARSING_INTENT | control | PARSING_INTENT | FAILED | allow / POLICY_ALLOWED |
| C15-PLANNING | control | PLANNING | FAILED | allow / POLICY_ALLOWED |
| C15-VALIDATING | control | VALIDATING | FAILED | allow / POLICY_ALLOWED |
| C16-PROFILING | control | FAILED | PROFILING | allow / POLICY_ALLOWED |
| C16-PARSING_INTENT | control | FAILED | PARSING_INTENT | allow / POLICY_ALLOWED |
| C16-PLANNING | control | FAILED | PLANNING | allow / POLICY_ALLOWED |
| C16-VALIDATING | control | FAILED | VALIDATING | allow / POLICY_ALLOWED |
| C17 | generation | 不存在 | queued | allow / POLICY_ALLOWED |
| C18 | generation | queued | generating | allow / POLICY_ALLOWED |
| C20 | generation | generating | unavailable | allow / POLICY_ALLOWED |
| C21-queued | generation | queued | failed | allow / POLICY_ALLOWED |
| C21-generating | generation | generating | failed | allow / POLICY_ALLOWED |
| C22 | generation | failed | queued | allow / POLICY_ALLOWED |
| C23 | control | RUNNING | RUNNING | allow / POLICY_ALLOWED |
| C24 | creation | 不存在 | CREATED | allow / POLICY_ALLOWED |
| C19-A | generation | generating | completed | allow / POLICY_ALLOWED |
| C19-B | span | running | complete | allow / POLICY_OBSERVATION_ALLOWED |
