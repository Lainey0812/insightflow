我们先不进行进一步的优化，因为现在我很多时候没办法判断哪里有问题。我们先去做一个后台管理，给测试用，可以全程监控和追溯，方便不同版本对比。以下是框架，InsightFlow Admin Console V0.1 — 工程框架搭建

## 目标

在现有 InsightFlow 仓库中新增一个独立的 Admin Console，用于未来的工作流监控、问题追溯、版本对比和评测管理。

本阶段仅搭建工程框架，不实现真实监控业务。

## 第一步：检查现有项目

请先检查：

- 根目录结构与包管理方式。
- frontend 使用的 React、TypeScript、Vite、Ant Design 等实际版本。
- backend 的 FastAPI 启动方式及 API 结构。
- 当前 Git 状态、已有测试与启动命令。

先输出拟修改文件清单，避免覆盖现有未提交的开发工作。

## 第二步：搭建 Admin 应用

在项目根目录新增 `admin/`。

优先沿用 frontend 已有的稳定技术栈，不引入不必要的新框架。

要求：

- React + TypeScript。
- Vite 构建。
- React Router 路由。
- Ant Design 布局与基础组件（如现有项目已采用）。
- 独立开发端口，例如 5174，需检测冲突。
- 独立环境变量与 API Base URL。
- TypeScript 类型检查与构建脚本。
- 清晰的模块化目录。

## 第三步：创建基础页面

创建四个路由：

1. `/dashboard`：运行概览。
2. `/traces`：Workflow Trace 列表。
3. `/versions`：版本对比。
4. `/settings`：系统设置占位。

页面使用统一 Layout，包括侧边栏、顶部导航、内容区域。

目前没有真实 API 的功能，只展示明确的空状态，不生成虚假的成功率、Trace 或运行数据。

## 第四步：基础工程能力

- 建立统一 API Client。
- 配置环境变量。
- 设置基础错误处理。
- 设置 404 页面。
- 预留权限路由结构，但不要伪造已经完成的身份认证。
- 避免在客户端硬编码密钥。
- 不修改现有 Workflow、Planner、HITL、Engine、Report 的业务逻辑。

## 第五步：Monorepo 处理

保持现有 `frontend/` 和 `backend/` 目录。

如当前使用 pnpm 且适合配置 workspace，可添加最小 workspace 配置；否则先保持两个前端应用独立安装依赖。

不引入 Turborepo/Nx。

不迁移到 apps/，不做无关目录重构。

## 第六步：验收

需要验证：

- Admin 可以独立启动。
- 四个路由可以正常访问。
- 页面刷新后路由正常。
- TypeScript 检查通过。
- Admin 构建通过。
- 原 frontend 构建不受影响。
- 原 backend 核心测试不受影响。
- 无真实数据时展示空状态。

完成后提供修改文件、启动命令、验证结果和后续接入 API 的建议。

**本轮只完成 V0.1 框架，不提前开发 Dashboard 指标、Trace 埋点、评测中心或版本管理后端。**
