# Phase 03-B1 — Workflow Lifecycle Policy Validator 交付

日期：2026-10-31（Asia/Shanghai）；REQ-0080；依据冻结REQ-0079/VER-0001。  
交付状态：**部分完成，C19因契约时序冲突暂停。不宣称32条允许路径全部验收。**

## 1. 结果与进入下一阶段的判断

- 32/32命令完成不可变映射，逐条保存Command、Preconditions、Allowed Transition、Required Evidence。
- 31/32目标允许路径实现；C19始终明确deny/POLICY_CONTRACT_CONFLICT。
- 专项测试446通过；完整后端1325通过；Frontend67、Admin78通过；两个前端类型检查/构建通过。
- 现有281个源码及冻结设计文件未改变；没有在main、Workflow、API、Repository或任何生产写路径导入新模块。
- 不开启Backfill、Switch、第二个Workflow入口、新Root转换或Admin UI。

**是否允许进入Phase 03-B2：当前不建议。** 需先评审D01并追加契约决议，随后补齐C19合法允许路径与提交时序测试。未来任务需单独下发，本轮停止。

## 2. 实际新增文件

| 文件 | 原因 |
|---|---|
| `backend/app/domain/workflow_policy/models.py` | 冻结的纯领域快照、引用、业务证据、命令、幂等记录与Decision；字段严格区分Control/Execution/Generation；不接收业务投影或UI状态 |
| `backend/app/domain/workflow_policy/catalogue.py` | 32条冻结映射，保存原文guard/evidence与契约表SHA；不在运行时读取docs，不新增业务转换 |
| `backend/app/domain/workflow_policy/validator.py` | 纯校验入口、阶段资格、精确绑定、revision/key、幂等、证据和不支持命令拒绝；C19冲突隔离 |
| `backend/app/domain/workflow_policy/__init__.py` | 独立领域导出；无生产接入 |
| `backend/tests/workflow_policy_fixtures.py` | 合成可信领域事实，不使用真实用户数据/LLM/数据库 |
| `backend/tests/test_workflow_policy.py` | 32条映射、31条正向、非法状态/引用/证据、幂等、报告/执行、恢复、Legacy等测试 |

源码与冻结稿基线：[source-before.json](source-before.json)、[source-before.zip](source-before.zip)。交付快照：[source-after.json](source-after.json)、[source-after.zip](source-after.zip)。没有修改现有源码、测试、Prompt、模型参数或SQL。

## 3. 核心接口

```python
from app.domain.workflow_policy import WorkflowPolicyValidator

# snapshot与command由未来可信业务适配层构造。本轮没有API或Repository适配。
decision = WorkflowPolicyValidator().validate(snapshot, command)
```

输入：

- PolicySnapshot：native_v1.1/legacy_session_v1适用域，Workflow/Session/预留Root、control_status、revision、active key、当前精确引用、可信业务事实和幂等记录。
- PolicyCommand：冻结C编号、Workflow/Session、request_id、expected_revision、当前及下一活动key、输入绑定、待提交证据和命令选项。
- BusinessFact：来源只允许business/deterministic；包含所属Session/Workflow、摘要、精确绑定和本阶段所需数据。Intent/Candidate的artifact_origin可为llm，但“接纳状态”只能来自已验证的业务投影，不能使用原始LLM自报结果。

输出：

- decision：allow/deny。
- reason_code：固定的POLICY_*代码，完整清单在isolation-verification.json。
- action：execute/replay/none；**只有execute才有预期转换**。
- expected_transition：control/generation/creation owner、source、target。
- required_evidence：对应冻结事务效果，未来Writer必须同事务兑现，Policy本身不写。
- policy_scope、replay_ref、detail_fields：必要关联与诊断；不返回原始用户内容。

C13的实际合成调用输出示例：

```json
{
  "decision": "allow",
  "reason_code": "POLICY_ALLOWED",
  "action": "execute",
  "policy_scope": "native_v1.1",
  "command_id": "C13",
  "expected_transition": {
    "owner": "control",
    "source": "RUNNING",
    "target": "COMPLETED"
  },
  "required_evidence": ["ExecutionResult.partial_success+控制检查点"],
  "replay_ref": null,
  "detail_fields": []
}
```

这是Engine部分成功结束的控制检查点，不是报告成功、Root.complete或Business Lifecycle.succeeded。Policy不实现Lifecycle Read Model V2，也不派生Activity。

## 4. 32条命令覆盖

逐例结果：[command-coverage.md](command-coverage.md)。原文映射、输入和真实PolicyDecision：[command-coverage.json](command-coverage.json)。

- C01–C18、C20–C24及C15/C16/C21各展开项：合计31条允许路径。
- C19：映射保留，只有安全拒绝；没有用伪造accepted布尔值补齐通过率。
- C15/C21 normal失败与Recover分开：Recover要求证明旧Worker已隔离并提供新隔离key；不运行剩余任务。
- C16只按已有可信检查点选重试目标；不要求未来Plan/Approval/Execution ID非空。
- C17/C18/C20/C21/C22覆盖success/partial_success/failed的真实执行组合，不篡改Execution Outcome。

## 5. Fencing、证据与幂等语义

1. 每个命令验证Session/Workflow与所有输入事实归属；相同Dataset/Plan ID不能替代Workflow owner。
2. 新动作同时核对当前阶段、精确Bindings、revision、必要的当前活动key；开始/Retry要求不同的新key。
3. 不让Trace完成替代业务事实。物理Trace缺失不会阻断；已观察Root.complete只作终态拒绝信号，不能授权成功。
4. Profile绑定文件hash/表头等解析选项；Intent绑定目标/答案集；Planner绑定Intent和能力版本；保存计划保留P0/F0及未满足核心需求。
5. 审批检查确定性验证事实、覆盖、可执行任务、约束审计、阻断不确定性、告警确认和精确批准引用；不重新调用Plan Validator或LLM。
6. Engine outcome由任务事实计数核对；成功任务必须有真实结果引用，空表可以有结果引用；失败/跳过必须有错误。阻断任务不可成功执行，已保存任务不可篡改。
7. Report绑定当前Execution和attempt；generation.failed才可Retry，completed/unavailable不允许；旧执行、旧attempt、未提交核心事实都不能借COMPLETED放行。
8. 指纹从实际PolicyCommand规范化JSON计算，不信任调用者传来的payload_hash。同键不同载荷拒绝；同键进行中拒绝；同键已完成只返回replay_ref，**无转换且不得再次执行**。
9. 副本修改也重新验证，不能用model_copy绕过枚举/引用类型；模型冻结且容器使用tuple。

重要安全边界：纯Policy无法证明输入真实性、不能读取数据库确认事实、不能预约幂等键或持有CAS锁。未来适配层必须从可信数据库事务快照构造这些内部投影，禁止把HTTP/LLM原始字典直接当business事实。本轮输入schema不是公开API。

## 6. Legacy兼容与生产隔离

`legacy_session_v1`返回deny/POLICY_LEGACY_DELEGATED，明确“此原生Policy不适用，请走原Session规则”，不是声称旧业务请求被线上拒绝。现有Session、Engine、Reporting、HITL不导入Policy，legacy COMPLETED后修订与所有原有行为保持不变。

隔离检查：[isolation-verification.json](isolation-verification.json)：旧源码引用新Policy为0；Policy没有storage、services、API、Workflow、LLM、TraceRecorder、SQLite、HTTP或文件系统依赖。唯一既有业务枚举依赖是SessionStatus作为Control值集合，未更改原枚举或ALLOWED。

没有数据库Schema/迁移/API修改；仅在测试中构造新Workflow投影，不创建生产Workflow、Span或Root。

## 7. 测试与完整回归

| 验证 | 实际结果 | 记录 |
|---|---|---|
| Policy专项 | 446通过 | policy-tests-final.txt |
| 全部后端 | 1325通过，含旧879和新446 | backend-full-final.txt |
| Frontend | 67通过，9文件 | frontend-tests.txt |
| Admin | 78通过，10文件 | admin-tests.txt |
| Frontend类型检查与Vite构建 | 通过 | frontend-build.txt |
| Admin类型检查与Vite构建 | 通过 | admin-build.txt |
| 冻结V1.1完整性 | 原冻结文件SHA全部匹配 | isolation-verification.json |
| 旧代码/测试与生产导入 | 未变；无接入 | isolation-verification.json |

后端有1条既有Starlette/httpx弃用警告，不是本次新增失败。测试使用合成事实和原项目测试桩；未调用外部真实模型，不将Policy单测当作完整新Workflow运行验收。

运行命令（项目根目录）：

```sh
.venv/bin/python -m pytest -q backend/tests/test_workflow_policy.py
.venv/bin/python -m pytest -q backend/tests
```

Frontend/Admin分别在对应目录执行`npm test -- --reporter=dot`与`npm run build`。

失败记录全部保留：policy-tests-first.txt包含8个用例构造错误（Retry失败事实在snapshot中而非proposal）；r2包含2个同时损坏validation/任务集合导致的首个拒绝码预期错误。修正用例以隔离目标规则，没有关闭校验或放宽边界。r3保留440通过的中间结果；最终补充边界后446通过。第一次完整后端1319通过记录同样保留，最终1325使用新文件，不覆盖旧结果。

## 8. 未解决差异、风险与下一步门槛

详见[design-differences.md](design-differences.md)：

- **D01阻断**：C19的accepted=True时序与纯前置命令接纳冲突；必须追加契约决议，当前暂停允许路径。
- 幂等记录、active key、revision、事实与归属同事务提交都没有接入Writer，Policy allow不代表这些原子性已经具备。
- 合成内部事实模型需要后续受审计的适配层；本轮不能认证客户端自称business的证据。
- 多Worker恢复、历史分支提交策略、实际route/权威Switch仍未实施。
- 目前不开放新Root转换，旧Root/Report Run与Prompt快照仍按旧规则读写。

**结论：31条允许行为及32条映射可评审，Phase 03-B1完整验收尚未满足。暂不进入03-B2；先处理C19契约差异，再单独决定后续实施。**

代表性非法操作实际结果：[negative-cases.md](negative-cases.md) / [negative-cases.json](negative-cases.json)。20个合成非法请求均按预期deny，涵盖跨Workflow、过期revision/key、Root.complete、Resume、未验证约束、部分成功伪装、旧Execution、旧Report attempt、unavailable Retry、恢复隔离、幂等载荷冲突、Legacy与C19冲突。
