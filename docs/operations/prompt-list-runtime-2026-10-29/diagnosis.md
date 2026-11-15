# Prompt 列表加载失败排查（REQ-0053）

2026-10-29，针对当前本地实例进行诊断。

## 原因与处理

- 排查前 8000 和 5174 均无监听进程，API 无法连接。
- backend/.env 原有模型配置保留，但没有 INSIGHTFLOW_ADMIN_READ_TOKEN；当前进程环境也没有该配置。Admin 默认关闭并非数据库丢失。
- 已在原 backend/.env 追加随机独立管理员只读凭证，将该配置文件权限设为 0600；不记录凭证值，不复用模型 API Key。
- 后端从 backend 工作目录加载现有私密配置启动，保留 INSIGHTFLOW_DATA_DIR=../var 指向原项目 var；Admin 保留 /api 到 8000 的代理。
- 未修改应用源码、Prompt 内容或业务审批逻辑，未登记虚假历史或调用真实 LLM 填充页面。

## 实际验证

- GET http://127.0.0.1:8000/api/v1/health：200。
- 经 Admin 5174 代理 GET /api/v1/admin/prompts：未授权 403，使用已有服务器配置的只读凭证 200。
- 真实列表包含 intent_parser、analysis_planner、insight_generator，三个节点 version_count 均为 0，runtime_registration=not_registered。
- 浏览器现有 /prompts 页面可访问并显示“需要管理员只读访问”，无伪造数据。
- 用户可从私密 backend/.env 复制 INSIGHTFLOW_ADMIN_READ_TOKEN 的值，在页面启用只读访问。完整请求快照的额外权限未开启。

## 限制

没有已登记历史快照与服务连接失败是两个不同状态。当前真实数据库没有模板历史；机制启用后的实际模型调用将登记对应模板与调用记录，不能从当前模板伪造旧版本。

本轮仅运行服务、代理与权限验证，未更改源码，因此未重复运行全量构建与单元测试。服务是本地开发进程；机器或进程停止后仍需重新启动。现有 uvicorn 启动命令不自动读取 .env，本次启动显式安全加载了其中的 INSIGHTFLOW_ 配置。
