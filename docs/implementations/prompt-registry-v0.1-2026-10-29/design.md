# Prompt Registry V0.1 实施契约

REQ-0051，2026-10-29。复用三个服务、Compatible Provider、Report Trace/权限；不新增业务 Run，不改 Prompt 文本和统计/审核规则。

- PromptTemplateSnapshot：template_snapshot_id、node_id、version、content_hash、system_template、user_composition（固定结构、重试规则和能力说明）、output_schema_definition、实际加载的组合代码及来源哈希、Git 来源、创建时间。不可变；node_id/version 同内容幂等、不同内容报冲突。组合实现升级必须显式更新组合版本。
- LLMRequestSnapshot：request_snapshot_id、template_snapshot_id、消息/Schema/完整请求哈希、模型及实际发送参数、受控 payload 引用、创建/到期时间。实际发送 HTTP JSON 是唯一输入来源，不重演组合器。Header/密钥不保存。
- LLMCallRecord：call_id、node_id、operation_id（一个服务调用的相关 ID，非 Workflow Run）、call_sequence、retry_index、request_snapshot_id、template_snapshot_id、已有 run_id/span_id（允许 null）、生命周期、耗时、错误代码、响应文本哈希。每个 API 尝试一条，首次及 retry 分开；模型供应商实际版本未知时不补填。
- 独立本地 SQLite `var/prompt_registry/registry.sqlite3` 保存上述三类对象，不复制业务 Run/Execution。使用版本化增量迁移、外键和唯一约束；内容快照写入后不可变。原始 payload 单独表，便于保留策略管理。目录 0700/数据库0600，无客户端密钥。
- 调用前快照失败：fail closed、不发 HTTP；调用后状态写入失败：明确失败、不输出成功假象。Trace 关联写入仍 fail open，可出现有调用记录但无 Trace 的明确缺口。
- Report 现有 RunManifest 增加可选模板引用；调用事实从 CallRecord 关联，不修改已保存 Manifest。Intent/Planner 暂无持久 Trace Run，不伪造运行；operation_id 关联重试，Run/Span 为 unavailable。
- 模板来自实际绑定 System、运行中代码对象及经核验源码，不仅取磁盘当前文件。调用时再次核对绑定，发现单独热重载/源码不一致拒绝错误标记；schema动态内容保存在当次 RequestSnapshot。
- 默认保留模板与调用元信息、请求内容直到显式策略变更，避免擅自删除用户历史；可配置原始请求保留天数，到期 API 不再读取，按策略清理 payload（模板与哈希不删）。磁盘备份另行管理。
- 普通 Admin 只读授权查看调用元信息；完整请求另外要求专用 snapshot token；无授权不返回消息正文。历史 Run 没有关联调用时返回 unavailable，不用当前模板补齐。

预定修改：新增 domain/prompt_registry.py、storage/prompt_registry.py 与 SQL migration、llm/templates.py、llm/capture.py；调整 llm/base.py、compatible_provider.py、main/config、三个 service、observability/recorder 与 api/admin；新增专项测试。不修改 Planner/Validator/HITL/Engine 的业务决策或 Report Insight 校验规则，不开发 Registry 页面。
