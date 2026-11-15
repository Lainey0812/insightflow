# 人工标注与存为 Bad Case V1（REQ-0114）

## 修改依据

REQ-0114：用户回复“继续”，确认执行 Admin 路线第 3 步剩余部分：在 Workflow 详情页人工标注问题，并存为可回放的 Bad Case。本版本不包含用 Bad Case 自动回放或批量回归（路线第 4 步）。

## 实现

后端：
- `app/domain/bad_case.py`：`BadCaseCreate`、`BadCaseTransition`（`extra=forbid`，长度限制）；问题类型 understanding/planning/calculation/insight/report/failure/other，严重程度 high/medium/low，状态 open/confirmed/fixed/wont_fix/invalid。
- `app/storage/migrations/bad_cases_001.sql` 与 `app/storage/bad_cases.py`：独立库 `var/bad_cases/bad_cases.sqlite3`，`bad_cases` 和 `bad_case_events` 两张表都由触发器禁止 UPDATE/DELETE；状态变更追加事件，用 `expected_sequence` 做乐观并发（不一致返回 409 `BAD_CASE_STALE`）。
- `app/services/bad_cases.py`：保存时调用 Workflow 观测投影，冻结业务生命周期、失败定位、质量信号、一致性、节点元数据（不含 `error_message`）、模型调用引用（ID、状态、重试序号、错误代码、请求/模板快照 ID、响应哈希）与回放引用（会话、数据集及版本、计划及版本、校验版本、审批、执行、报告尝试、调用 ID 列表），计算证据 SHA-256；读取时重算哈希并返回 `evidence_intact`。所选节点必须属于该 Workflow。
- `app/api/admin.py`：`GET /admin/bad-cases`、`GET /admin/bad-cases/{id}`（沿用管理员只读鉴权）；`POST /admin/bad-cases`、`POST /admin/bad-cases/{id}/events` 另需 `X-Admin-Annotation-Token`。未配置 `INSIGHTFLOW_ADMIN_ANNOTATION_TOKEN` 时返回 503，Admin 保持只读；本机测试模式免该凭证（仍受本机来源校验）。
- `app/core/config.py`、`app/main.py`：新增配置并装配服务。

Admin：
- `api/client.ts` 增加 `post`；`types/badCases.ts`、`api/badCases.ts`（返回结构校验、写入错误文案）。
- `features/badCases/BadCaseShared.tsx`：Workflow 详情页“人工标注”区（已有标注列表 + “存为 Bad Case”表单，问题节点默认选失败节点）。
- `pages/BadCasesPage.tsx`（列表与筛选）、`pages/BadCaseDetailPage.tsx`（问题描述、处理记录与追加表单、冻结证据、失败定位、质量信号、节点表与模型调用链接、证据哈希不一致告警）。
- 导航启用 Bad Case 分组；路由 `/bad-cases/:caseId`；横幅文案改为“当前开放运行追踪、Prompt 管理与 Bad Case”。

## 验证

- 后端：`tests/test_bad_cases.py` 5 项通过（冻结证据与按 Workflow 列表、凭证与引用校验、未配置凭证时只读、追加历史与并发冲突及触发器、证据篡改检测）。全量 1661 项通过，1 项失败为已知沙箱限制 `test_trace_comparison.py::test_git_unknown_without_repo_and_actual_commit_when_available`。
- Admin：`tsc -b` 通过；vitest 15 个文件、104 项通过（新增 `bad-cases.test.tsx` 5 项；`navigation.test.tsx`、`routes.test.tsx` 按新预期更新，原文件在 `before/`）；`npm run build` 通过。
- 浏览器实测：复制 `var/` 到临时目录，本机测试模式启动临时后端（8013）与 Admin（5184），在部分成功的 Workflow `wf_d5f123209ea641edaba85007c7968d0a` 上选 fact_validator 节点保存一条“【本机验证样例】”Bad Case，跳转详情页，再追加“已确认”记录，列表正确显示。截图见 `screenshots/`。临时服务已停止，临时目录已删除，原 `var/` 未写入。

## 修改前副本

`before/` 保存修改前的 14 个文件。
