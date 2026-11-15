# HITL V1：代码审查与实施方案

## 复用结论

| 模块 | 原有行为 / 本次复用方式 |
|---|---|
| `services/plan_review.py`、`api/routes.py` | 原审核服务及 revision / approval 路由保留，按会话真实计划类型分流。旧 Mock 审批不能转为真实执行权限。 |
| `components/PlanReviewCard.tsx`、`MessageList.tsx`、`App.tsx` | 扩展现有审核卡片和聊天交互；新上传会话使用真实计划导入、审核与执行。历史 Mock 会话明确标识。 |
| `planning/validator.py`、`domain/analysis_plan.py` | 直接调用既有确定性 Validator，不改变 F0/F1/F2、六类能力或覆盖算法。客户端不能提交 executable 等资格标记。 |
| `services/analysis_engine.py`、`storage/execution_repository.py` | 沿用四标识执行请求、服务端批准快照、真实文件摘要验证、内核及幂等执行；补充审批审计一致性与结果 approval_id。 |
| `storage/session_repository.py`、SQLite sessions JSON | 原接口不变。会话 JSON 增加默认可空 review_plan / review_status；所有旧数据保持可读。 |
| `api/datasets.py`、Profiler、DatasetRef | 复用真实画像，数据版本仍是解析契约与文件摘要产生的字符串，不改为递增数字。 |

## 公共 Schema 兼容风险与调整

1. 旧 `Plan.version / tasks[].id` 与 V1 `AnalysisPlan.plan_version / tasks[].task_id` 不兼容，不能相互强制转换。新增 `SessionState.review_plan` 保存 V1 版本，旧 `plans` 字段保留。已有卡片按真实类型展示，真实模式不渲染旧 Mock 卡片。
2. `ValidatedAnalysisPlan` 只表明可执行资格，不代表审批。新增只追加的 `PlanVersion`、`ReviewApproval`；真实审批生成既有 `ApprovedExecutionSnapshot`。
3. 批准快照新增可选 `session_id`、`acknowledged_warnings`，结果新增可选 `approval_id`。既有测试夹具、历史 imported 报告仍兼容；真实 HITL 始终填写这些字段。
4. 版本历史沿用 `/sessions/{id}/plans`。真实会话返回 PlanVersion，旧会话返回原 Plan；调用方根据 review_plan / review_status 分流。新增 `/plan` 和 `/plans/{version}` 专供真实审核读取。
5. 原有审批请求仅含 revision 和 plan_version。V1 另外强制核对 plan_id、dataset_id、dataset_version、validation_version、approval_request_id、acknowledged_warnings；旧调用不获得真实权限。拒绝额外 `approved=true`。
6. 原始约束均为 `unverified`，没有结构化解决证据。本次明确阻断这些约束及 clarify/defer，不通过布尔确认、隐藏字段或模型猜测宣称问题已解决。
7. 项目无账户身份系统。新增真实会话使用一次发放的随机访问凭证，服务端只保存 SHA-256；保护会话、画像引用、审核与执行查询，并过滤无权访问的会话标题。这是本地会话能力凭证，不是完整多租户隔离；独立数据集 API 和历史 Mock 接口仍沿用本地单用户假设。

## 数据迁移需求

启动时增量创建三张表：

- `plan_versions`：session_id + plan_version 唯一；保存完整验证快照与变更元数据。
- `plan_approvals`：approval_id 主键、session_id + request_id 唯一；保存请求与不可变审批记录。
- `session_access`：新真实会话的凭证摘要。

对前两张表安装拒绝 UPDATE / DELETE 的触发器。不重写旧数据、不改变旧表列、不转换历史 Mock 批准。计划版本、当前会话、审批指针均在 `BEGIN IMMEDIATE` 事务中更新；版本检查和重新校验失败全部回滚。执行记录继续保存原有不可变批准快照。

## 实施文件范围与顺序

1. 扩展 `domain/models.py`、`domain/execution.py`，新增 `domain/plan_review.py`。
2. 新增 `storage/plan_review_repository.py`，扩展 `storage/database.py`，复用 session 存储。
3. 扩展现有 `services/plan_review.py` 与 `api/routes.py`；新增会话凭证守卫，接入画像和执行路由。
4. 扩展 `workflow/orchestrator.py` 的人工计划入口，跳过 LLM / Mock Planner；真实计划始终走现有 Engine API。
5. 扩展审核卡片、API client、会话类型及聊天展示；新增计划导入和真实执行结果预览。
6. 新增边界、并发、真实文件测试与可复现验证脚本；保留并运行全部原有测试。最后进行真实浏览器上传、审核、删除、确认与结果恢复验收。
