# InsightFlow Phase 03-B1：Workflow Lifecycle Policy Validator

## 目标

依据已冻结的 `Lifecycle Contract V1.1`（REQ-0079/VER-0001），实现 Workflow 级生命周期命令校验器。

本阶段只建立 Policy Validator 和测试，不切换业务状态权威，不改动现有 Session 执行路径。

## 实施要求

1. 以冻结契约中的 32 条命令矩阵为唯一目标行为依据，逐条建立 Command → Preconditions → Allowed Transition → Required Evidence 的映射。
2. 实现纯领域层 Policy Validator，不依赖前端状态、LLM 自报状态或 Trace 成功结论。
3. 区分 Control Status、Business Lifecycle、Activity 和 Execution Outcome，禁止混用。
4. 对每项命令验证 Workflow ID、当前阶段、精确对象引用、revision、必要的 active key 及幂等语义。
5. Validator 只输出 allow/deny、稳定 reason code 和必要的预期转换，不直接写数据库。
6. 不支持的 Resume、unavailable Retry、Root.complete 重开必须明确拒绝。
7. Legacy 兼容行为必须单独标记，不得静默改变现有 Session 状态机。
8. 不修改冻结的 V1.1 契约。如发现设计冲突，输出差异报告并停止相关实现。

## 测试

- 覆盖全部 32 条允许命令。
- 覆盖非法状态转换和缺少必要证据。
- 覆盖跨 Workflow 归属错误。
- 覆盖过期 revision 和 active key。
- 覆盖重复命令、同幂等键不同载荷。
- 覆盖 Engine partial、Report failed、Report unavailable。
- 覆盖 Legacy 兼容。
- 保证原有后端、前端、Admin 回归测试不退化。

## 边界

禁止：

- 开始 Backfill 或 Switch。
- 修改 SessionState 业务权威。
- 将 Validator 直接接入生产写入路径。
- 修改 Engine / Reporting 的业务执行逻辑。
- 开放新的 Workflow Root 状态转换。
- 开始 Admin UI 改造。

## 交付

输出实现文件清单、32 条命令覆盖报告、非法操作测试结果、完整回归结果、尚未解决的设计差异及是否允许进入 Phase 03-B2 的判断。

完成后停止，不自动进入下一阶段。
