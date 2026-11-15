# Prompt Registry V1.0 只读页面审计与实施计划

REQ-0052，2026-10-29。

现有 PromptRegistryRepository 在单一 registry.sqlite3 内保存不可变 prompt_templates、llm_request_snapshots、llm_calls 与受控 payload。V0.1 API 已提供单个模板读取、单个调用元信息、额外 snapshot token 的完整请求，以及 Run/Span 的调用关联；缺少节点目录、模板历史分页、版本关联调用和文本 Diff。

复用 Admin 现有 HttpOnly Cookie/只读 token 和 API client。完整请求继续由独立 snapshot token 授权；默认页面只显示元信息/哈希，不自动加载原文、不把凭证放 URL/本地存储。前端 React 19.3.1 / Router 7.18.5 / Vite 7.3.7，现有组件和 CSS，无 Ant Design，不新增 UI 框架或 Diff 依赖。

重要兼容点：V0.1 模板来源包包含服务与部分辅助模块的源码指纹。为避免无关只读查询开发改变已登记模板内容，本轮不改原 PromptRegistryRepository、LLM Provider、TemplateSource、三个节点、TraceRecorder 或既有模型；新增独立只读 query service，在原 Admin Router 挂查询。运行时模板引用从现有 service.prompt_source.snapshot 读取，不重演 Prompt 构造、不登记新快照。

当前版本语义：最新登记 snapshot 从真实数据库时间/稳定顺序得到；运行时绑定 ID 来自当前进程实际固定模板。分别显示，未知不填。固定组合定义是 JSON，不伪装成不存在的 User 字符串模板；variables_schema 未保存则标 unavailable，仅显示已登记字段列表。缺失历史返回 unavailable/404，不通过 Git 或今天配置补齐。

新增读取：节点目录、按节点历史分页、单版本详情、同节点两个真实快照的分段/按行 Diff、版本调用分页、调用默认脱敏摘要。复用 V0.1 原文权限接口。不会生成新业务 Run，不新增数据库或迁移，不在线编辑/发布 Prompt。

页面：/prompts、/prompts/:promptId、/prompts/:promptId/versions/:snapshotId、/prompts/versions（URL 保存节点、左右选择与分页）、/prompts/calls/:callId。Report Run 和 LLM Inspector 链接只使用已保存模板 ID，旧 Run 无引用显示 unavailable，不使用当前配置替代。

文件计划：新增 backend/app/services/prompt_registry_query.py、backend/tests/test_prompt_registry_read.py；调整 api/admin.py 和 main.py 的只读接入；新增 admin types/api/prompts、Prompt 四类页面与复用展示组件、专项测试；调整路由/导航、Trace 链接和局部 CSS。保留本次前后源码、测试与浏览器/操作记录。
