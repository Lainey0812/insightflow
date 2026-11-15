# InsightFlow Evaluation Platform — Phase 2-B2 实施任务

## 一、任务目标

你是一名资深 Python 后端架构师和 AI Agent Evaluation Engineer。

基于已完成的 Phase 1 评测内核与 Phase 2-B1 运行索引、数据集发现服务，实现评测详情与证据读取 API。

必须先阅读：

- `docs/designs/evaluation-admin-v1-2026-11-13/DESIGN.md`
- REQ-0146、REQ-0147、REQ-0150、REQ-0151。
- `backend/app/evaluation/` 现有契约与读取接口。
- Phase 2-B1 的 Discovery Service 和 API。
- 现有 FastAPI Admin 路由及测试。

本轮只实施 Phase 2-B2，完成后停止。

## 二、交付四个只读 API

统一前缀：`/api/v1/admin/evaluations`

### 1. GET /runs/{run_id}

返回：

- Run ID、Run Type、Agent ID/Version。
- Dataset ID/Version/Hash。
- Run Lifecycle Status。
- Integrity Status 和完整性问题。
- Evaluator Manifest。
- 运行配置及创建、完成时间。
- Case 数量和状态分布。
- 可信评测指标。
- Case 摘要列表。
- Legacy / Recorded 数据来源标识。

要求：

- 复用 B1 的 Run Index 定位运行。
- 使用 Phase 1 `read_run()` 获取事实数据。
- 不重新实现 E2E 评分。
- INVALID 的运行不得显示为可信整体指标。
- INCOMPLETE 的运行必须展示缺失 Case。
- 历史 UNVERIFIED 必须明确标记。

### 2. GET /runs/{run_id}/cases/{case_id}

返回：

- Case ID。
- Execution Status。
- E2E Verdict。
- Failure Origin。
- Oracle / MustForbid / Node Fidelity 结果。
- Evaluator ID、Version、Required、Verdict。
- Failure Code、Reason、Evidence References。
- Case Integrity。
- Execution Record 与 Final Output 的可用性。
- Legacy Projection 与原始标签。

必须区分：

- Agent 执行失败。
- 必选业务约束失败。
- Evaluator 自身异常。
- 证据缺失或完整性错误。

不得将 NOT_EVALUATED 转换为 FAIL，也不得将历史缺失字段补成虚构值。

### 3. GET /runs/{run_id}/cases/{case_id}/evidence

提供只读证据视图。

优先支持 Golden JSON 证据：

- Trace。
- Plan。
- Dataset Profile。
- Engine Execution Steps。
- Result Tables。
- Evaluator Evidence References。

TC 历史运行不得打开 SQLite。

对于不存在的证据，明确返回 NOT_RECORDED 或 UNAVAILABLE，不得伪造。

安全要求：

- 不返回本地绝对路径。
- 不返回完整 LLM Endpoint。
- 不返回 API Key、Token 或连接凭据。
- 对原始用户输入采取最小化暴露策略。
- 限制响应大小。
- 限制 Trace 节点数量及嵌套深度。
- 不允许任意文件路径查询。
- 不打开 SQLite。
- 不修改任何运行文件。

### 4. GET /datasets/{dataset_id}

返回：

- Dataset ID。
- Dataset Type。
- Dataset Version（不存在则 null）。
- Dataset Hash。
- Case Count。
- Source。
- Freeze Status（当前 UNDECLARED）。
- 关联 Run 摘要。

数据集不存在返回 404。

同一 Dataset ID 对应多个不同内容哈希时，不得静默合并成一个版本。

## 三、完整性与错误处理

明确区分：

- VERIFIED。
- UNVERIFIED。
- INCOMPLETE。
- INVALID。

建议采用以下原则：

- VERIFIED：可以提供可信指标。
- UNVERIFIED：可以展示历史记录，但明确提示无法验证完整性。
- INCOMPLETE：展示已完成部分和缺失 Case。
- INVALID：允许读取可验证的元数据，但不得把损坏结果当作可信事实。

API 错误：

- 404：Run / Case / Dataset 不存在。
- 409：Run ID 冲突或无法唯一定位。
- 422：参数非法。
- 413：证据超过响应大小限制。
- 500：真正未预期的服务器错误。

损坏或缺失的单个 Evidence 不得让整个 Run Detail 返回 500。

对于不完整数据，优先返回结构化状态和错误原因。

## 四、数据访问与安全

1. 只允许通过 B1 索引定位运行。
2. 不允许通过 URL 参数拼接文件路径。
3. 所有读取限制在配置的允许根目录。
4. 拒绝目录越界及符号链接越界。
5. 证据接口不得打开 SQLite。
6. 不得修改历史运行及 Golden Set。
7. 不得返回敏感环境变量。
8. 不得返回数据库连接字符串或模型访问凭据。
9. 所有 API 使用明确的 Pydantic Response Model。

保留现有 Admin 的权限和认证方式，不新增独立认证体系。

## 五、测试与验收

使用 Fixtures 和临时目录，不调用真实 LLM。

至少覆盖：

1. 新 Golden Run Detail。
2. 历史 Golden Run Detail。
3. 历史 TC Run Detail。
4. VERIFIED / UNVERIFIED / INCOMPLETE / INVALID。
5. RF-01～RF-05 的执行和评测状态。
6. Case Detail 的必选与可选 Evaluator。
7. EVALUATOR_ERROR。
8. NOT_EVALUATED。
9. Legacy Projection。
10. 缺失 Case。
11. 缺失 Evidence。
12. Evidence JSON 脱敏。
13. LLM Endpoint 完整移除。
14. API Key / Token 不泄露。
15. 原始用户输入最小化暴露。
16. Evidence 大小限制。
17. Evidence 嵌套深度限制。
18. 路径穿越。
19. 符号链接越界。
20. 重复 Run ID。
21. Dataset ID 对应不同 Hash。
22. 404 / 409 / 413 / 422。
23. 不打开 SQLite。
24. 不产生 WAL/SHM。
25. 历史文件哈希及修改时间不变。
26. B1 两个列表 API 不退化。
27. `/admin` 和 `/api/v1/admin` 路由兼容。

对于 INVALID 运行，额外验证：被篡改的 Case Result 不得进入可信指标，也不得以 VERIFIED 状态显示。

## 六、严格禁止

- 不修改 Agent、Planner、Engine 或 HITL。
- 不修改 Oracle 和 MustForbid 判定逻辑。
- 不修改 Golden Set。
- 不修改历史运行。
- 不开发 Admin 前端。
- 不修改 `/traces` 路由。
- 不开发 Bad Case 回流。
- 不引入数据库迁移。
- 不开发评测任务调度。
- 不进入 Phase 2-C。

## 七、交付报告

完成后输出：

1. 新增和修改文件清单。
2. 四个 API 的真实响应示例。
3. 完整性和错误处理策略。
4. Evidence 脱敏规则。
5. 可信指标计算方式。
6. 自动化测试命令和结果。
7. B1 回归测试结果。
8. 历史目录完整性检查。
9. 已知限制。
10. 是否满足进入 Phase 2-C1 的条件。

测试证据写入独立目录，不覆盖之前的验收记录。

**完成 B2 后停止，等待架构审核。**
