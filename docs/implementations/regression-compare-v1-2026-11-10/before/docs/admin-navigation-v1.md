# InsightFlow Admin — 分层目录导航

对应需求 REQ-0047。本轮按用户提供的信息架构调整后台导航，不提前实现新模块业务。

## 目录与路由

| 一级入口 | 二级入口 | 路由 | 当前状态 |
| --- | --- | --- | --- |
| 运行总览 | — | /dashboard | 沿用总览空状态 |
| 工作流管理 | 工作流概览 | /workflows/overview | 管理入口占位 |
| 工作流管理 | Understanding | /workflows/understanding | 管理入口占位 |
| 工作流管理 | Planning | /workflows/planning | 管理入口占位 |
| 工作流管理 | Execution | /workflows/execution | 管理入口占位 |
| 工作流管理 | Reporting | /workflows/reporting | 管理入口占位 |
| Prompt 管理 | Prompt 列表 | /prompts | 占位 |
| Prompt 管理 | 版本详情与 Diff | /prompts/versions | 占位 |
| Prompt 管理 | Playground（后期） | /prompts/playground | 后期功能 |
| 版本与发布 | 节点版本 | /versions/nodes | 占位 |
| 版本与发布 | Workflow Releases | /versions/releases | 占位 |
| 版本与发布 | 版本对比 | /versions | 沿用真实 Run 对比入口 |
| 运行追踪 | Run Explorer | /traces | 沿用真实接口与权限 |
| 运行追踪 | Trace Detail | /traces/detail | 未选择 Run 时引导到列表 |
| 评测中心 | 测试数据集 | /evaluations/datasets | 占位 |
| 评测中心 | Evaluation Runs | /evaluations/runs | 占位 |
| 评测中心 | 回归对比 | /evaluations/regressions | 占位 |
| Bad Case | 问题列表 | /bad-cases | 已接入（REQ-0114）：人工标注的问题列表，按状态、类型、Workflow 筛选 |
| Bad Case | 问题详情 | /bad-cases/detail、/bad-cases/{case_id} | 已接入（REQ-0114）；未选择问题时引导到列表 |
| 系统管理 | 权限与角色 | /settings/roles | 占位，不冒充完成账户/角色管理 |
| 系统管理 | 环境配置 | /settings | 沿用公开本地配置，只读 |
| 系统管理 | 操作审计 | /settings/audit | 占位，不将 Trace 当作操作审计 |

已有深层地址保持：`/traces/:runId` 为真实运行详情，归属“运行追踪 / Trace Detail”；`/traces/compare?left=...&right=...` 为真实运行对比，归属“版本与发布 / 版本对比”。静态 `/traces/detail` 不会作为假的 run_id 请求接口。

各阶段“管理入口占位”指后台界面未接入，不表示对应业务模块未开发。原 Workflow、Planner、HITL、Engine、Report 与 Admin API 均未修改。

## 交互

- 8 个一级入口，7 个可折叠分组，21 个二级入口；按用户提供的顺序排列。
- 当前分组自动展开，子页高亮，面包屑显示分组与子页。
- 长菜单单独滚动，窄屏默认收起，通过顶部按钮打开抽屉；选择页面后关闭抽屉。
- 未接入页明确显示范围与状态，不请求虚构 API、不产生模拟数据、不添加无效业务操作。
- 新路由继续通过原权限扩展点；没有新增身份认证或绕过 Trace 服务端鉴权。

## 修改与验证

核心改动：app/navigation.ts、app/routes.tsx、layouts/AdminLayout.tsx、styles.css；新增 ModulePlaceholderPage.tsx；调整 Dashboard/环境配置/404 标签及 EmptyState 的状态提示；扩展既有权限类型占位与导航测试。

Admin 自动化 **43 passed**，包括原有 Trace/对比测试与新增 5 项导航测试；TypeScript 与 Vite 构建通过。验收日志、修改前/后源码和截图见 [本轮档案](audits/admin-navigation-v1/)。早期测试断言与测试类型错误的日志保留。

浏览器实测：现有旧 URL 进入后新的面包屑正确；分组展开后能进入工作流概览；页面刷新恢复；窄屏抽屉包含所有一级入口和当前工作流子项；截图 navigation.jpg。原 Trace 页在本轮浏览器检查时因后端未启动显示连接失败，本轮没有启动/改配后端或创建新 Run；功能代码与原 API 保留，相关前端自动化通过。

本轮只运行 Admin 测试与构建，未将历史后端测试成绩冒充本轮结果。没有调用真实 LLM，没有更改数据库或既有版本档案。
