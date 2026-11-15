# HITL V1 真实审批闭环

> 这是 V1 的历史实施与验收记录。当前主入口已接入真实 Workflow 和 [HITL V2 业务确认页](hitl-v2.md)。V2 在保持原审批/版本/执行契约的前提下增加确定性约束证明，只有证明通过才可批准；下文“所有约束统一阻断”等描述属于 V1 阶段。

真实上传 → 人工结构化计划 → Validator → 审核与任务删除 → 不可变新版本 → 用户确认 → 服务端审批 → 现有 Analysis Engine → 持久化结果。

新页面默认使用真实审核。无需配置或调用 LLM。初始人工提交不是批准；只有页面“确认并执行”或对应的明确确认请求才能生成服务端审批。自动化验收的确认操作只在独立测试数据库进行，不代表生产人工批准。

代码审查、复用依据、兼容性及迁移方案见 [实施方案](hitl-review-plan.md)。

## 使用与接口

路径均以 `/api/v1` 开始，错误沿用 `{error: {code, message, ...}}`。

| 方法 / 路径 | 行为 |
|---|---|
| POST `/sessions`，multipart `manual_review=true`、非空 `goal`、`file` | 上传、真实画像后等待人工计划。返回一次性 `review_access_token`。不调用意图模型或 Mock Planner。 |
| POST `/sessions/{sid}/plans` | `{expected_revision, plan: AnalysisPlan, intent: ParsedIntent}`。仅用于真实会话的初始 v1。服务端读取画像并运行 Validator。意图业务目标须与原始 goal 完全相同。 |
| GET `/sessions/{sid}/plan` | 当前 PlanVersion，其中 validated_plan 为真实 ValidatedAnalysisPlan。 |
| GET `/sessions/{sid}/plans` | 版本历史。真实会话返回 PlanVersion[]；历史 Mock 会话沿用 Plan[]。 |
| GET `/sessions/{sid}/plans/{version}` | 读取该会话历史版本，不改变当前版本。 |
| POST `/sessions/{sid}/plan-revisions` | `{expected_revision, plan_id, plan_version, remove_task_ids}`。锁定当前状态、删除、重新校验、生成新版本；不接受客户端校验结论。 |
| POST `/sessions/{sid}/approvals` | 见下面确认请求。服务端重新校验并创建不可变审批。返回更新后的 SessionState。 |
| GET `/sessions/{sid}/approvals` | 完整不可变审批快照及其 execution_ids。历史审批不一定仍授权执行。 |
| POST `/executions` | 沿用四标识请求，从服务端读取审批，禁止提交任意计划或 approved 标志。 |
| GET `/executions/{id}`、`/executions/{id}/results/{result_id}` | 沿用真实结果 / 分页接口；要求对应会话凭证。 |

除创建外，真实会话及执行请求均需 `X-Session-Token`。会话列表用 `X-Session-Keys`（会话 ID → 凭证的 JSON 对象）读取自己有凭证的真实会话，也支持单个 X-Session-Token。浏览器自动保存凭证、审批请求 ID 和执行请求 ID，并在重试时复用。服务端不再次返回原始凭证；清除浏览器本地存储后，需要新建真实会话。不要将凭证放入 URL 或日志。

批准请求示例（从当前版本读取准确值）：

```json
{
  "expected_revision": 7,
  "plan_id": "sales_manual_review",
  "plan_version": 2,
  "dataset_id": "真实上传ID",
  "dataset_version": "真实画像版本摘要",
  "validation_version": "1.0",
  "approval_request_id": "客户端生成的唯一确认请求ID",
  "acknowledged_warnings": []
}
```

partial coverage 必须包含 `partial_coverage`，存在 F0 必须包含 `blocked_tasks`，annotate 事项须包含 `uncertainty_{id}`。前端逐项展示并收集确认；服务端核对完整所需集合，未知警告不能代替所需确认。

删除最后一个任务允许产生空计划版本用于审计；覆盖 blocked 或没有可执行任务不能批准。删除 P0 不改变原始目标或 core_requirements；coverage、unmet_core_requirements、executable_task_ids、blocked_task_ids 全部由 Validator 重算。F0 始终展示原因并由 Engine 跳过；F1 必须是当前 Registry 支持的显式转换链。

自然语言修订接口保留在原 revision 请求的 `instruction` 字段：真实会话发送非空指令明确返回 `501 AI_REVISION_NOT_AVAILABLE`，不进行关键词 Mock 修订。

## 状态与一致性

`review_status` 与旧 SessionStatus 并存，避免破坏历史调用：

| 真实审核状态 | 含义 |
|---|---|
| awaiting_review | 画像或初始计划已保存，待审核 |
| validating | 同步修改事务内重新校验；页面请求期间禁用按钮，失败回滚 |
| awaiting_approval | 新版本已校验，待用户确认 |
| approved | 已保存当前版本的审批快照 |
| executing | 已被 Engine 事务认领 |
| completed | Engine 成功或部分成功；任务状态和错误仍逐项显示 |
| execution_failed | Engine 全部失败；原始审批记录保留 |

每次有效删除生成新计划版本，并清空当前审批指针。历史审批记录及历史执行不被修改。审批绑定 session、plan、dataset、validation 的准确版本。Engine 再次对照不可变审批表、最新计划记录和 Validator，认领时再次核对 session revision，避免数据加载期间被并发修改。

同审批 request_id、完全相同参数重试返回原审批，不新增记录或 revision；不同参数返回冲突。计划变更后重放旧审批不能重新授权。执行继续遵循原 Engine 幂等机制：同 execution_request_id 返回已保存的成功或失败结果，不静默重算；新版本需要新的审批和执行请求 ID。已完成执行的历史查询/幂等读取不意味着允许重执行旧版本。

## 主要错误码

- `TASK_NOT_FOUND`：删除目标不存在。
- `STALE_SESSION` / `PLAN_VERSION_MISMATCH`：并发修改或计划上下文不一致。
- `DATASET_VERSION_MISMATCH` / `PLAN_VALIDATION_STALE`：数据或校验版本不一致。
- `COVERAGE_BLOCKED` / `NO_EXECUTABLE_TASKS`：无法满足批准/执行前提。
- `BLOCKING_UNCERTAINTY` / `UNVERIFIED_CONSTRAINTS`：仍有未解决问题或无结构化约束证据。
- `WARNINGS_NOT_ACKNOWLEDGED`：未明确确认重要限制。
- `APPROVAL_REQUEST_CONFLICT` / `ALREADY_APPROVED` / `APPROVAL_SUPERSEDED`：重复或过期确认。
- `V1_APPROVAL_REQUIRED` / `V1_EXECUTION_ENDPOINT_REQUIRED`：未批准或试图绕过真实入口。
- `SESSION_ACCESS_DENIED`：缺少本会话凭证，返回 403。
- `AI_REVISION_NOT_AVAILABLE`：LLM 修订未接入。
- `ANALYSIS_GOAL_REQUIRED` / `ANALYSIS_GOAL_MISMATCH`：目标为空或被替换。

## 真实文件验收

从 backend 目录运行：

```bash
../.venv/bin/python -m pytest -q
../.venv/bin/python scripts/verify_hitl.py
```

前端运行 `npm test` 和 `npm run build`。

可复现脚本通过公开 API 完成：上传 `sales.csv`、保存人工计划、读取审核、拒绝未批准执行、删除 A03、生成 v2、创建审批、拒绝旧版执行、真实计算、重复审批/执行请求和重新创建应用后的持久化读取。没有直接构造批准快照。独立 Pandas 基准：华东 6 条、157000；整体 12 条、263000。

- [API 验收完整记录](hitl-verification.json)
- [真实 ExecutionResult](hitl-execution.example.json)
- [浏览器上传—删除—确认—结果恢复记录](hitl-browser-verification.json)
- [浏览器结果截图](hitl-browser-verification.jpg)
- [人工计划示例](../examples/sales-review-plan.json)：在页面编辑 JSON 时替换 dataset_id / dataset_version，并保持 goal 与示例一致。该示例不是已批准计划。

## 明确边界

- 原始 `unverified` 约束、clarify / defer 仍会阻断。本阶段没有创建结构化约束证据或解决这些事项的编辑工具；不能声称它们已被确认解决。当前可审批无这些阻断项的真实合法计划。
- 没有接入 LLM 计划生成/自然语言修订、报告自动生成或 Agent 编排。页面明确说明这些边界。
- 本地单进程部署、SQLite JSON 结果存储和原 Engine 大小/分页限制不变。会话凭证不构成完整账户系统；独立数据集 API 继续是本地单用户接口。不要直接对公网开放。
- 为保留现有测试和历史行为，旧 `/sessions` API 未传 `manual_review=true` 时仍是原有明确标记的 Mock 工作流。新前端始终传 true，真实会话不能从旧入口执行，也不接受旧 Mock 批准。
- 当前 health 的 `mode=mock` 保留为旧客户端兼容字段；新增 capabilities.hitl / analysis_engine / new_ui 标明真实路径。不能只依据该旧字段判断新页面计算来源。
