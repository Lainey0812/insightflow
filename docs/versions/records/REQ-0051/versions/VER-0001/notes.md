REQ-0051 / prompt-registry-v0.1-foundation，2026-10-29。

实现默认 FastAPI 应用三个 Compatible HTTP LLM 节点的不可变模板、调用记录、最终请求快照；新增独立 SQLite 迁移、服务实际来源绑定、Provider 统一捕获、Report Trace/Manifest 引用与受限只读接口。没有开发 Registry 页面或改变 Prompt/业务分析规则。

三个 prompt.py 字节未变；服务内三段 retry 指令提取为同值常量，已与 REQ-0050 冻结记录逐字比对。三个节点的完整 HTTP 请求亦与冻结实施前样例比较一致。

最终后端全量 756 passed（原 726 + 新 30），1 项原有弃用 warning。最终测试、早期失败及修复记录均保留，没有改低覆盖要求或覆盖旧历史。真实模型/网络调用 0；请求组装示例通过真实服务和 HTTP Provider、以本地脚本响应得到，不能声称模型质量评测。示例含 3 节点、5 调用、retry、动态 Schema 和 2 条 Report Run/Span 关联。

before/after 源码 ZIP/SHA、契约 JSON、测试日志、完整示例及 delivery.md 在本 artifact 目录；没有复制真实 .env、密钥、用户上传、业务数据库或旧报告。

限制：Intent/Planner 暂无完整 Trace Run，只以 operation_id 追溯；历史请求不可补造；旧评测脚本/自定义 Provider 未自动纳入；同步 SQLite/单进程恢复；未做加密、RBAC、真实模型质量或新 UI。Code/source 哈希为保守来源指纹，不等同于 System 文本变更或已验证历史 Git 部署。后端完整重启后自动初始化新侧库。
