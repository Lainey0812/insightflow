# 32 条命令覆盖报告

REQ-0080。映射32/32，目标允许实现31/32，C19因D01安全拒绝；不宣称全部32条允许验收通过。所有样例为纯领域合成输入，不是真实Workflow运行。

| 命令 | 业务命令 | 转换owner | 前态 | 后态 | 验证结果 |
|---|---|---|---|---|---|
| C01 | 开始准备 | control | CREATED | PROFILING | allow / POLICY_ALLOWED |
| C02 | 画像完成 | control | PROFILING | PARSING_INTENT | allow / POLICY_ALLOWED |
| C03 | 意图可规划 | control | PARSING_INTENT | PLANNING | allow / POLICY_ALLOWED |
| C04 | 意图需澄清 | control | PARSING_INTENT | WAITING_FOR_CLARIFICATION | allow / POLICY_ALLOWED |
| C05 | 补充澄清 | control | WAITING_FOR_CLARIFICATION | PARSING_INTENT | allow / POLICY_ALLOWED |
| C06 | Planner回调 | control | PLANNING | VALIDATING | allow / POLICY_ALLOWED |
| C07 | 保存验证计划 | control | VALIDATING | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C08 | 待审批删除任务 | control | AWAITING_APPROVAL | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C09 | 已批准但未执行修订 | control | APPROVED | AWAITING_APPROVAL | allow / POLICY_ALLOWED |
| C10 | 批准当前计划 | control | AWAITING_APPROVAL | APPROVED | allow / POLICY_ALLOWED |
| C11 | 执行claim | control | APPROVED | RUNNING | allow / POLICY_ALLOWED |
| C12 | Engine成功结束 | control | RUNNING | COMPLETED | allow / POLICY_ALLOWED |
| C13 | Engine部分成功结束 | control | RUNNING | COMPLETED | allow / POLICY_ALLOWED |
| C14 | Engine全部失败结束 | control | RUNNING | FAILED | allow / POLICY_ALLOWED |
| C15-CREATED | 准备失败/中断收敛 | control | CREATED | FAILED | allow / POLICY_ALLOWED |
| C15-PROFILING | 准备失败/中断收敛 | control | PROFILING | FAILED | allow / POLICY_ALLOWED |
| C15-PARSING_INTENT | 准备失败/中断收敛 | control | PARSING_INTENT | FAILED | allow / POLICY_ALLOWED |
| C15-PLANNING | 准备失败/中断收敛 | control | PLANNING | FAILED | allow / POLICY_ALLOWED |
| C15-VALIDATING | 准备失败/中断收敛 | control | VALIDATING | FAILED | allow / POLICY_ALLOWED |
| C16-PROFILING | 准备显式Retry | control | FAILED | PROFILING | allow / POLICY_ALLOWED |
| C16-PARSING_INTENT | 准备显式Retry | control | FAILED | PARSING_INTENT | allow / POLICY_ALLOWED |
| C16-PLANNING | 准备显式Retry | control | FAILED | PLANNING | allow / POLICY_ALLOWED |
| C16-VALIDATING | 准备显式Retry | control | FAILED | VALIDATING | allow / POLICY_ALLOWED |
| C17 | 首次报告排队 | generation | 不存在 | queued | allow / POLICY_ALLOWED |
| C18 | 报告启动 | generation | queued | generating | allow / POLICY_ALLOWED |
| C19 | 提交可交付报告 | generation | generating | completed | deny / POLICY_CONTRACT_CONFLICT |
| C20 | 提交不可生成记录 | generation | generating | unavailable | allow / POLICY_ALLOWED |
| C21-queued | 报告失败/Recover | generation | queued | failed | allow / POLICY_ALLOWED |
| C21-generating | 报告失败/Recover | generation | generating | failed | allow / POLICY_ALLOWED |
| C22 | 报告显式Retry | generation | failed | queued | allow / POLICY_ALLOWED |
| C23 | 提交任务进度 | control | RUNNING | RUNNING | allow / POLICY_ALLOWED |
| C24 | 创建独立新目标 | creation | 不存在 | CREATED | allow / POLICY_ALLOWED |

每行前置条件、证据需求、可重放输入与实际PolicyDecision详见 [command-coverage.json](command-coverage.json)。允许路径均额外覆盖命令/证据跨Session/Workflow、过期revision/key、绑定错误、缺失证据、状态非法、Root关闭、无Trace与幂等重放/冲突。C19只覆盖明确拒绝，不伪造成功提交receipt。
