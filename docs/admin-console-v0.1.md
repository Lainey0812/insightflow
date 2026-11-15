# Admin Console V0.1 工程交付

需求：REQ-0042。范围只包含独立前端工程框架，不实现监控业务。日期：2026-10-28。

## 开发前检查

项目根目录已有 `frontend/`、`backend/`、`docs/`、`examples/`、`var/` 和 `.venv/`。原前端使用 npm 独立安装，没有根 package.json、pnpm workspace 或 Ant Design；本轮继续采用独立 npm 应用，未迁移目录或引入构建编排工具。

| 项目 | 实际版本 / 方式 |
| --- | --- |
| React / React DOM | 19.3.1 |
| TypeScript | 5.9.3 |
| Vite / React 插件 | 7.3.7 / 5.2.0 |
| Vitest | 4.1.12 |
| Admin 新增 React Router DOM | 7.18.5（精确锁定） |
| Node / npm | 25.5.0 / 11.8.0 |
| FastAPI / Uvicorn / Pydantic | 0.162.0 / 0.54.0 / 2.14.1 |

Admin 沿用 React、TypeScript、Vite、Lucide 和原前端测试工具。原前端没有 Ant Design，因此使用本地 CSS 实现基础 Layout，不额外安装组件框架。两个应用各有锁文件，主前端锁文件没有变化。

现有后端从 `backend/` 启动：`../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`。现有 API 以 `/api/v1` 为前缀，包含 health、sessions、datasets、intents、plans、executions、reports 等，交互式文档为 `/docs`。当前没有 Admin API，本轮没有新增后端路由。

检查时项目不属于 Git 仓库，因此无法提供 Git diff 或已提交状态。本轮没有初始化 Git、提交或重置文件；用 `before-manifest.json` 记录原有 backend/frontend 文件哈希，交付时核对。初次检查 5174 和 4174 均空闲。

## 文件变更

新增 `admin/` 全部工程文件，完整文件列表与哈希见验收目录的 `admin-source-manifest.json`。核心位置：

| 文件 | 内容 |
| --- | --- |
| `admin/package.json`、`package-lock.json` | 独立依赖与 dev/typecheck/test/build/preview 命令 |
| `admin/vite.config.ts`、`tsconfig.json`、`index.html` | 端口、代理、类型与构建配置 |
| `admin/.env.example`、`.gitignore`、`README.md` | 独立环境变量、忽略规则与运行说明 |
| `admin/src/app/*`、`layouts/AdminLayout.tsx` | 路由、导航及统一布局 |
| `admin/src/pages/*` | 四个页面与 404 |
| `admin/src/components/*` | 空状态与渲染失败处理 |
| `admin/src/api/client.ts`、`config/env.ts` | API Client 与配置检查 |
| `admin/src/auth/AccessBoundary.tsx` | 权限挂载结构，无虚构身份认证 |
| `admin/src/tests/*` | 路由和 API Client 自动化测试 |
| `admin/src/main.tsx`、`vite-env.d.ts`、`styles.css`、`public/favicon.svg` | 页面入口、样式及本地图标 |

根 README 仅追加 Admin 启动入口；另新增本文、验收证据和需求版本档案。未修改原前后端源代码、测试、依赖契约或业务数据库。

## 页面与基础行为

| 路由 | 当前真实行为 |
| --- | --- |
| `/dashboard` | 运行数据未接入的空状态，无虚构指标 |
| `/traces` | Trace 未接入的空状态，无模拟记录 |
| `/versions` | 版本 API 未接入的空状态，不读取或改变旧档案 |
| `/settings` | 只读展示真实公开配置，注明认证尚未接入 |
| `/` | 跳转 `/dashboard` |
| 其他路径 | 页面级 404，可返回概览 |

路由使用 BrowserRouter；所有页面共享侧栏、面包屑、内容容器和工程预览提示。侧栏可收起/展开，小屏保留带可访问名称的导航图标。没有无法工作的保存、登录或自然语言修改按钮。

## 验收结果

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| Admin TypeScript | 通过 | `admin-typecheck-01.txt` |
| Admin 单元测试 | 14/14 通过（2 文件） | `admin-tests-01.txt` |
| Admin 构建 | 通过 | `admin-build-01.txt` |
| 原 frontend 测试 | 52/52 通过（8 文件） | `frontend-tests.txt` |
| 原 frontend 构建 | 通过 | `frontend-build.txt` |
| backend 完整测试 | 670/670 通过 | `backend-tests.txt` |
| 开发服务 | 5174 独立启动，后端未启动也可浏览 | 浏览器检查记录 |
| 四个路由直接访问与刷新 | 开发服务与构建预览均通过 | 浏览器检查记录、`preview-route-snapshots.json` |
| 根跳转、404、侧栏交互 | 通过 | 浏览器检查记录 |
| 端口冲突 | 第二次启动明确拒绝 5174，退出码 1 | `port-conflict.txt` |
| 原有源文件保留 | 见 `preservation-check.json`，所有预存条目一致 | 哈希逐项核对 |

后端测试仍有一个现有 Starlette/httpx 兼容弃用警告。本轮未修改相关依赖。自动化测试没有调用真实 LLM，也未把测试替身用作页面业务数据。

浏览器使用 Codex In-app Browser：开发服务验证页面导航、直接访问、刷新、根跳转、404 和侧栏；构建预览在 4174 验证全部页面直接访问和刷新。浏览器捕获的 warn/error 日志为空。截图与详细步骤见 [验收证据](evaluations/admin-console-v0.1/README.md)。

## 后续 API 接入建议（未在本轮实施）

先定义只读查询契约及服务端授权，再接入已有持久化记录。明确“没有记录”和“接口失败”的不同状态；统一 session、plan/version、execution/report、prompt/schema/model 版本引用与分页规则。界面通过 `api/` 服务层读取，不直接访问 SQLite、本地文件或包含密钥的日志。

当前默认 `/api/v1/admin` 只是未来命名空间，不代表服务已实现。保留独立 Base URL 后，可选择同源代理或独立后台服务。未来静态部署需要 SPA 路由回退配置；认证能力上线前保持本地用途。

工程参考：[React Router 官方路由说明](https://reactrouter.com/start/declarative/installation)、[Vite 环境变量说明](https://vite.dev/guide/env-and-mode)。
