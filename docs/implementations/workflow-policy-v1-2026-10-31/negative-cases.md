# 非法操作实际校验结果

纯领域合成输入，20个代表性非法操作均按预期拒绝。完整测试还有每条命令参数化的状态/证据/归属/幂等覆盖；不是20次线上请求。

| 操作 | 实际reason_code | 结果 |
|---|---|---|
| 跨Workflow命令 | POLICY_WORKFLOW_MISMATCH | deny |
| 过期revision | POLICY_STALE_REVISION | deny |
| 过期活动key | POLICY_STALE_ACTIVE_KEY | deny |
| Root.complete不可重开 | POLICY_ROOT_CLOSED | deny |
| 开始活动没有新key | POLICY_NEW_ACTIVE_KEY_REQUIRED | deny |
| Engine Resume不支持 | POLICY_UNSUPPORTED_OPERATION | deny |
| Report Resume不支持 | POLICY_UNSUPPORTED_OPERATION | deny |
| 缺证据 | POLICY_MISSING_EVIDENCE | deny |
| 业务生命周期不可代替控制状态 | POLICY_INVALID_INPUT | deny |
| 同幂等键换载荷 | POLICY_IDEMPOTENCY_CONFLICT | deny |
| 旧Planner回调 | POLICY_STALE_ACTIVE_KEY | deny |
| 未验证约束 | POLICY_APPROVAL_BLOCKED | deny |
| 部分成功谎称success | POLICY_EXECUTION_INVALID | deny |
| 旧Execution引用 | POLICY_REFERENCE_MISMATCH | deny |
| 旧Report attempt | POLICY_REFERENCE_MISMATCH | deny |
| 无效unavailable掩盖有效核心 | POLICY_REPORT_UNAVAILABLE_INVALID | deny |
| unavailable禁止Retry | POLICY_REPORT_RETRY_UNSUPPORTED | deny |
| Recover缺少旧Worker隔离 | POLICY_MISSING_EVIDENCE | deny |
| Legacy显式委托 | POLICY_LEGACY_DELEGATED | deny |
| C19契约时序冲突 | POLICY_CONTRACT_CONFLICT | deny |
