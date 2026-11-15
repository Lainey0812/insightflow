REQ-0050 / prompt-loading-audit-v0.1，2026-10-29。

完成三个 LLM 节点的入口、System 导入绑定、User 动态构造、Schema 构造、重试及 Provider 出站请求审计。保留 108 个当前业务源码的 ZIP/SHA；不含环境文件、密钥、数据库或真实上传数据。

新增交付仅在 docs/audits/prompt-loading-paths-2026-10-29/。没有修改 backend/app、Prompt 内容、前端或数据库；没有新增 Snapshot Runtime/表或更改业务规则。

本地合成数据经实际服务与 CompatibleLLMProvider 的 HTTP MockTransport 截取：13 个场景、12 个请求体、30 项断言全部通过，外部调用 0，SQLite 连接 0。是请求组装验证，不是真实模型质量评测或浏览器端到端验收；未运行完整 pytest。Report 批准分支仅使用内存夹具。

前两次审计脚本错误保留：首次场景数量计数不一致，第二次无证据夹具违反 count 结果契约；均未修改业务逻辑，最终修正审计夹具另存新 captures-v3/。原脚本、原请求和说明完整保留。

关键结论：System 来自 Python 字符串模块，User 及 retry 指令位于服务/辅助组合器；Planner 能力规则影响 User；Report Evidence ID 影响实际输出 Schema；现有 Trace System 哈希不能覆盖全请求；存在导入时绑定与队列/完成时记录时间点不同的追溯风险。当前实际模块与截取消息一致，未证明历史曾错绑；无 Git，因此实际 source_commit 不可提供。

详细依据：audit.md、request-index.json、captures-v3/summary.json 和逐次请求。后续快照方案应从实际请求边界绑定，但本轮未实施，旧审计与历史记录均保留。
