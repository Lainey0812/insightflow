# Prompt Registry V1.0 只读 Admin 交付

2026-10-29 · REQ-0052。

已完成三节点模板目录、真实历史、不可变详情、固定文本 Diff、调用分页与受控请求读取入口。复用 V0.1 的 registry.sqlite3、模型与捕获机制，没有新的快照存储、迁移或模型调用节点，没有 Prompt 编辑、Playground、发布或自动评测。

## 审计与兼容性

V0.1 已保存固定模板、最终请求和 Call，具备单条模板/调用读取及 raw 请求独立授权；缺少列表、分页历史、模板调用检索和 Diff。本轮新增 `PromptRegistryQuery` 只读投影，所有查询连接既有 Repository，不注册新模板、不渲染 Prompt。

V0.1 来源包包含组合器及一些辅助模块的源码指纹。因此特意没有改原 storage/prompt_registry.py、llm/templates.py、capture.py、compatible_provider.py、domain/prompt_registry.py、TraceRecorder 或三个节点。新查询服务不进入它们的 Prompt 内容包，避免为 UI 查询更新制造模板冲突。启动接入只调整 main.py 与现有 Admin Router。

“最新登记”依据已保存创建时间/稳定顺序；“运行时已绑定且登记”还要求匹配当前服务已有 pin 的 ID。当前进程无法确认或尚未登记时分别 unknown/not_registered，不以最新历史冒充当前启用。

当前默认路径的 registry.sqlite3 在审计时不存在，见 storage-audit.json。因此本轮没有可展示为用户生产历史的 Registry 记录。下次后端启动沿用 V0.1 自动初始化侧库；没有记录则真实空状态。历史文件/ZIP 档案与数据库登记不同，未擅自导入、重建或补造过去部署内容。

## 只读 API

沿用原 `/admin` 与 `/api/v1/admin` 两个前缀，原 Header/HttpOnly Cookie 授权及 no-store。新增：

| GET 路径 | 返回 |
| --- | --- |
| /admin/prompts?node=intent_parser | 三节点目录或单节点，实际版本数、最新记录与运行时登记状态 |
| /admin/prompts/{node}/versions?limit=20&offset=0 | 真实历史分页及总数 |
| /admin/prompts/{node}/versions/{snapshot_id} | V0.1 原模板及登记状态、变量信息可用性 |
| /admin/prompts/compare?left={id}&right={id} | 两个同节点真实快照的逐片段逐行 Diff |
| /admin/prompts/{node}/versions/{snapshot_id}/calls?limit=20&offset=0 | 调用分页，含已保存模型和真实 Trace 可用性 |
| /admin/llm-calls/{call_id}/summary | 调用、请求哈希、保留状态，正文默认 hidden |

复用原 `/admin/llm-calls/{call_id}/request`：必须额外提交 `X-Admin-Snapshot-Token`。新摘要接口不读取 payload 正文，只查元信息与保留状态。原始正文不写入列表响应、URL、localStorage 或 sessionStorage。

API 拒绝跨节点 Diff、同一快照对比、未知节点、错误归属及缺失版本。未知历史返回 404，前端标 unavailable；没有用当前代码兜底。Diff 只读 prompt_templates，与 llm_request_snapshots 无版本推断关系。

实际后端 API 示例在 `api-examples-browser/`：catalog.json、history.json、version.json、calls.json、call-summary.json。这些来自隔离测试库中的真实登记/查询，三个模板由未修改的 TemplateSource 从当前实际加载源码生成；调用使用合成 CSV 与本地 HTTP 脚本响应，外部模型调用 0，**不是用户生产历史或真实模型质量评测**。每份文件均有来源标记，未把测试数据写入用户库。

初次生成成功但端口绑定被沙箱拒绝的 API 示例另保存在 `api-examples/`，没有覆盖。后续隔离服务器获准启动后完成浏览器验证。

## 页面与使用方式

1. 完整重启 backend 以加载新 API，启动原 Admin 开发服务，打开 Prompt 管理 → Prompt 列表（`/prompts`）。按需输入现有服务端管理员只读凭证；它不是 LLM API Key。
2. 筛选 Intent Parser、Analysis Planner、Insight Generator。节点卡片仅展示真实版本数、最新登记、哈希、创建时间和来源 Commit；未采集 Commit 为 unknown。
3. 打开 `/prompts/{node}` 查看真实历史。只有一个版本时明确提示没有第二个快照可比；分页保存在 offset 参数。
4. 打开 `/prompts/{node}/versions/{snapshot_id}` 查看固定 System、User 组合/变量、重试、固定能力说明、Schema 生成定义和来源代码。复制操作只复制当前已存片段。
5. V0.1 的固定 User 是 JSON 组合定义，并没有独立长字符串模板；页面按登记形式呈现。独立 variables_schema 未保存，明确 unavailable，只显示已知字段/组合定义，不杜撰变量类型。
6. `/prompts/versions` 先选节点，再将实际存在的两个快照选为左侧/右侧。分页选择可跨页，node、left、right、offset 均保存在 URL；直接刷新仍恢复。相同 ID 不请求 Diff。
7. Diff 可切换 System、User 组合、重试、固定上下文、Schema 定义及逐个来源文件。并排保留原始行号/换行，左红右绿表示差异。某侧未登记文件内容时标 unavailable，不猜测增删原因。
8. 从版本查看关联调用的时间、节点、模型、状态和重试序号。调用协议正常不等于业务校验成功；Intent/Planner 没有持久 Run 时只展示操作/调用关联。
9. 调用详情 `/prompts/calls/{call_id}` 默认展示脱敏摘要与哈希。需要原文时输入单独快照读取凭证，按需授权读取；字段随提交清空，原文可隐藏，刷新不自动重现。已过期/未保留时不重建。
10. Report RunManifest 与 Insight Generator Inspector 只使用保存的模板引用或 Call Event ID 跳转，不用当前配置填历史。Call 指向的 Run/Span 不存在时不提供伪造跳转。

本轮不额外登记模板来让页面好看。若没有已登记记录，应先使用真实业务入口产生可追溯调用，或另行设计经过审核的历史导入；打开只读页面本身不会创建版本。

## 验证与截图

- Backend：**770 passed，1 项原有 Starlette/httpx 弃用 warning**；新增只读查询测试 14 项。
- Admin：**59 passed**（原 43 + 新 16）；TypeScript 检查与 Vite 构建通过。
- 原业务 frontend：**52 passed**；TypeScript/Vite 构建通过。
- 三个 prompt.py、V0.1 契约、来源绑定、捕获与原 Repository 文件哈希保持不变。

日志分别为 backend-final.txt、admin-tests-final2.txt、admin-build-final.txt、frontend-tests.txt、frontend-build.txt。早期日志继续保留：全局提示新增 Prompt 后，原 3 条路由测试仍断言旧文案而失败；更新为准确的新提示，保留原有“无模拟数据/无额外 API”断言，没有降低验证要求。

后端覆盖：三个真实当前模板；单/双版本与稳定分页；最新/实际绑定不同；Diff 原文重建一致与跨节点拒绝；动态请求不增加模板；权限/原文隔离；Trace 关联真实性；缺失历史 unavailable；查询不改变既有 pin 内容。两个版本的差异测试使用明确标注的第二版本夹具，仅在隔离测试库，不伪造生产历史。

浏览器通过独立 `localhost:4175` 预览和 `127.0.0.1:8011` API 验证，保留用户现有 5174 服务和标签。测试库每节点仅一个真实当前模板、两条本地脚本响应调用，没有插入虚假旧版。实测三节点正文、节点筛选、单版本历史/Diff 空态、只读授权、raw 错误凭证拒绝/额外授权成功、刷新后原文隐藏和缺失历史 unavailable。浏览器发现并修正“版本分页被节点名称覆盖”的文案问题；原截图保留，最终截图另存。隔离服务器及临时标签均已停止/关闭。

截图（来自隔离验证库，不是用户生产数据）：

- screenshots/catalog-final.jpg：三节点真实登记列表。
- screenshots/history-final.jpg：单版本历史与正确分页。
- screenshots/single-version-diff.jpg：没有第二版本时不生成虚假对比。
- screenshots/call-summary-final.jpg：默认脱敏调用摘要。
- screenshots/history-unavailable.jpg：缺失历史不可恢复。

详细记录：browser-verification.json。没有新增浏览器端双版本测试数据；双版本文本准确性由 API 行重建和组件测试验证。

## 修改文件

后端新增：

- backend/app/services/prompt_registry_query.py
- backend/tests/test_prompt_registry_read.py

后端调整：

- backend/app/api/admin.py：复用授权，挂只读查询。
- backend/app/main.py：只传递已有 runtime pin 引用。

Admin 新增：

- src/types/prompts.ts、src/api/prompts.ts
- src/features/prompts/PromptShared.tsx
- src/pages/PromptsPage.tsx、PromptHistoryPage.tsx、PromptVersionPage.tsx、PromptComparePage.tsx、PromptCallPage.tsx
- src/tests/prompts.test.tsx、prompt-api.test.ts

Admin 调整：

- src/app/routes.tsx、navigation.ts；src/layouts/AdminLayout.tsx
- src/types/traces.ts；src/features/traces/AccessPanel.tsx、NodeInspector.tsx、TraceShared.tsx
- src/styles.css；src/tests/routes.test.tsx
- admin/README.md、根 README.md

依赖/锁文件没有变化。未修改三个 LLM 节点、Prompt、Validator、HITL、Engine、Report 业务实现。

## 已知限制

1. 仅显示 V0.1 库中真实登记内容，旧文件档案和只有版本号的 Trace 不自动导入。历史缺失不能恢复。
2. 没有 Prompt 发布系统；最新登记不代表发布，运行时绑定未知就显示 unknown。
3. V0.1 模板没有单独变量类型 Schema，页面明确 unavailable；完整动态 Schema 属于受控调用快照。
4. 权限仍为既有管理员只读凭证 + 额外 raw 凭证，不宣称细粒度多用户 RBAC。固定 Prompt 源码对 Admin 可读，真实请求默认隐藏。
5. 调用及历史查询分页，但 V0.1 表中未新增查询索引；大量历史记录时仍需专门性能验证。Diff 每次读取两个完整固定包，前端只渲染所选片段；没有大包性能承诺。
6. 原始保留策略、单进程恢复、无加密等 V0.1 限制不变。schema_hash 是 response_format 指纹；模板 hash 包含版本/组合代码，不能单凭哈希把差异归因于 System 或某次质量变化。
7. 本轮未做外部 LLM 调用/质量评测，没有自动评测、Prompt 编辑或发布功能。默认业务后端在验收时未运行，需启动/重启后使用新增 API；5174 原开发服务仍保留。
