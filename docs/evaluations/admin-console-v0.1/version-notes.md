# REQ-0042 / Admin Console V0.1 实施记录

本次按用户最新要求暂停进一步 Insight Generator 优化，新增独立 `admin/` 工程框架。

- 沿用 React 19.3.1、TypeScript 5.9.3、Vite 7.3.7，新增精确锁定的 react-router-dom 7.18.5；独立 npm 锁文件。
- 四个页面、统一布局、404、错误边界、环境配置、API Client 和权限挂载结构均已实现。页面没有真实监控 API、指标、Trace 或假认证。
- 原 frontend/backend 的 216 个预存文件哈希逐项一致，未修改既有业务实现、测试和依赖。未初始化 Git，未清理数据库、上传文件或历史档案。
- Admin 14 项测试、类型检查和构建通过；原前端 52 项测试及构建通过；后端 670 项测试通过（1 条原有弃用警告）。
- 浏览器验证开发服务 5174 和构建预览 4174 的四个页面直接访问与刷新；根跳转、404、侧栏展开/收起通过。重复启动 5174 明确失败，未静默换端口。
- 默认 API Base URL 是尚未实现的 `/api/v1/admin`；没有调用真实 LLM，没有提前实现后台管理业务。
- 运行说明：`admin/README.md`；工程交付：`docs/admin-console-v0.1.md`；测试、浏览器记录、源码快照及哈希：`docs/evaluations/admin-console-v0.1/`。
- 本轮源码快照 `admin-console-v0.1-source.zip` 共 29 个文件，仅包含 Admin 源码与配置样例，不含真实 .env、密钥、依赖或构建产物。

后续建议先定义有服务端授权的只读查询契约，再逐项接入真实记录；本记录不宣称监控、追溯或版本比较业务已完成。
