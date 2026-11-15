# 模型原始返回受控快照 V1

日期：2026-11-09。需求：REQ-0112（暂不迁移 LangGraph，继续 Admin），关联 REQ-0111、REQ-0107（P0：LLM 返回只存 hash）。

## 改动

后端
- 新增迁移 `storage/migrations/prompt_registry_002.sql`：`llm_response_payloads(call_id, kind, content, content_sha256, truncated, expires_at)`，禁止 UPDATE；迁移版本允许 {1,2}。
- `storage/prompt_registry.py`：`finish(call, response)` 与调用终态同一事务写入返回；content 类型校验与 call.response_hash 一致；`response()` 读取时校验哈希，篡改返回 LLM_RESPONSE_INTEGRITY_ERROR(503)；`response_availability()`；`prune_expired` 同时清理到期返回。保留期限复用请求的 expires_at。
- `llm/capture.py`：成功保存 response.text（kind=content）；失败且错误携带 raw_response 时保存原始响应体（kind=raw_body，上限 64KB，记录 truncated）。写入失败沿用 LLM_CAPTURE_FINALIZE_FAILED。
- `llm/compatible_provider.py`：解析拆为 `_parse`；HTTP 错误、超大、拒答、未完整结束、结构异常时把 response.text 附在 AppError.raw_response 上，仅供快照，不进入业务错误、日志或 API 业务响应。
- `services/prompt_registry_query.py`：summary 增加 response_availability、response_kind（不含正文）。
- `api/admin.py`：新增 `GET /admin/llm-calls/{id}/response`，与请求共用快照凭证校验（抽出 require_snapshot_token）；无保留返回 410 LLM_RESPONSE_UNAVAILABLE。快照拒绝提示文案改为“完整模型请求与返回…”。

Admin
- `types/prompts.ts`、`api/prompts.ts`：CallResponseContent 与 rawResponse。
- `pages/PromptCallPage.tsx`：新增“受控模型返回”区块：授权后读取、JSON 自动格式化、标注 raw_body/截断、隐藏按钮、凭证即时清空；unavailable/expired 说明不提供读取表单。

测试
- 新增 backend/tests/test_llm_response_snapshot.py 9 例：成功内容与授权、模型输出非 JSON 但调用成功、HTTP 500/截断/拒答保留原始体且不进入业务错误、64KB 截断、超时 410、不可更新与篡改检测、v1 库原地迁移。
- 修改 backend/tests/test_prompt_registry.py 迁移断言 [1] → [1,2]（新增迁移的预期变化，原文件副本已保存）。
- 新增 admin/src/tests/prompt-response.test.tsx 4 例。

修改前副本：docs/implementations/llm-response-snapshot-v1-2026-11-09/before/。

## 验证

- 后端全量 1652 passed，1 failed 为既有沙箱 git 测试（无法写 .git/hooks），与本次无关。
- Admin 96 passed，typecheck、build 通过。
- 真实 Registry 副本迁移：版本 [1,2]，16 条调用、30 个模板不变，旧调用 response_availability=unavailable、不回填。副本已删除，原库未写。

## 限制

- 未发起真实模型调用验证（需要用户模型配置与授权）；Provider 行为由 MockTransport 覆盖。
- 运行中的 8000 后端重启后才加载新代码并对真实 Registry 执行迁移 002；迁移后旧版本代码无法打开该库（版本检查）。
- 历史调用、超时等无响应调用没有返回内容。
- 返回可能包含业务结果，保护仅依靠快照凭证、本地文件权限与可选保留期；未加密存储。
