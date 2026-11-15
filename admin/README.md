# InsightFlow Admin Console V0.3

独立的本地测试管理界面。Trace 列表、详情、Node Inspector 和两次运行对比已接入真实后端记录；Dashboard、设置仍为占位。支持本机免登录测试和管理员只读访问，没有多用户账户、版本评测或 Prompt 编辑。

## 当前 Prompt 模板登记

后端启动时会登记三个已配置真实模型节点实际加载的当前 Prompt 模板。登记复用原不可变快照存储，不调用模型、不生成调用或 Trace 记录。重复启动不会新增相同版本，也不会改写旧快照。未配置模型时不伪造模板运行状态；旧版未留存内容仍显示 unavailable。

## 本机免登录测试

后端启动前显式导出 `INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE=true`，即可不设置或输入管理员凭证。可以保存在私密的 `backend/.env`，但原始 uvicorn 命令不会自动加载该文件，需要先将配置导入进程环境。Admin 与后端均保持监听 `127.0.0.1`。

该模式包括完整请求快照读取，仅用于本人电脑上的功能测试；检查实际连接、Host、Origin 和跨站请求，不信任转发头。不要通过公网隧道或其他代理暴露此模式。设置为 `false` 并重启后恢复原有凭证校验；未配置凭证时接口默认关闭。旧凭证与历史数据仍保留。

## 安装与启动

使用 Node.js 22.12+（本轮验证版本 25.5.0）和 npm。与 `frontend/` 各自安装依赖，不使用 workspace。

```sh
cd /Users/lainey/Desktop/vibe-coding/insightflow/admin
npm ci
npm run dev
```

访问 http://127.0.0.1:5174/dashboard。也可直接访问 `/traces`、`/traces/compare`、`/versions`、`/settings`；根路径跳转到 `/dashboard`。未知路径显示 404。

默认仅绑定 127.0.0.1，端口被占用时明确失败，不会自动选择其他端口。退出之前启动的服务后重试，或通过独立配置修改端口。

## 配置

默认值已内置，无需创建 `.env` 即可启动。需要覆盖时，将本目录 `.env.example` 复制为 `.env.local`，修改后重启开发服务；生产构建需重新构建。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `VITE_ADMIN_API_BASE_URL` | `/api/v1/admin` | 客户端 API 命名空间，Trace 与只读访问已实现 |
| `ADMIN_DEV_PORT` | `5174` | 开发端口 |
| `ADMIN_PREVIEW_PORT` | `4174` | 构建产物预览端口 |
| `ADMIN_API_PROXY_TARGET` | `http://127.0.0.1:8000` | 本地开发和预览的 `/api` 代理目标 |

`VITE_` 变量会进入浏览器产物，只放公开配置，禁止放 API Key。Admin 不读取 backend 或 frontend 的 `.env`。Trace 页面按需请求真实接口，未将后台数据或凭证打包进前端。浏览器通过服务端只读凭证换取短期 HttpOnly Cookie，不把凭证写入 URL 或本地存储。后端未配置时明确报错。

## 检查与构建

```sh
npm run typecheck
npm test
npm run build
npm run preview
```

构建输出为 `admin/dist/`。预览地址为 http://127.0.0.1:4174/dashboard。Vite 的开发与预览服务支持 SPA 路由回退；未来使用其他静态服务时，须将非资源、非 API 的页面路径回退到 `index.html`，否则直接刷新深层路由可能出现服务器 404。`vite preview` 用于本地验收。

## 目录与接入点

```text
admin/
├── .env.example / .gitignore
├── package.json / package-lock.json
├── index.html / tsconfig.json / vite.config.ts
├── public/favicon.svg
└── src/
    ├── app/             # App、路由和导航元信息
    ├── layouts/         # 侧边栏、顶部导航、内容容器
    ├── pages/           # Trace 列表、详情、对比与其他占位页面、404
    ├── features/traces/ # 访问表单、层级、Inspector、诊断展示
    ├── types/           # 复用 V0.1 的 Trace 数据契约
    ├── components/      # 空状态和渲染错误边界
    ├── api/client.ts    # JSON 请求、错误、取消和超时
    ├── config/env.ts    # 公开配置解析
    ├── auth/            # 未来服务端权限结果的路由挂载点
    ├── tests/           # API 和路由基础测试
    ├── main.tsx
    └── styles.css
```

后续服务模块通过 `createAdminClient()` 发起请求，并在页面明确区分加载、真实空结果和请求失败。当前 `AccessBoundary` 仅控制页面壳。Trace 数据由服务端凭证或其派生的 Cookie 授权；未授权接口拒绝。前端路由不能替代后端权限校验。

当前统一 API Client 处理 HTTP 错误、网络错误、无效 JSON、超时与取消，不自动重试写入，也不硬编码密钥。Trace 服务层增加了基础响应结构与归属检查，未用空数据掩盖无效响应。

当前运行示例、权限配置及验收记录见 [Trace V0.2](../docs/admin-trace-v0.2.md)。工程框架历史见 [V0.1 工程说明](../docs/admin-console-v0.1.md)。

访问 `/traces/:runId` 可直接刷新；筛选和分页保存在 URL，`span` 参数恢复选中节点。Cookie 方案要求同源代理；生产静态部署需配置 SPA 回退。管理员只读凭证配置在后端进程环境的 `INSIGHTFLOW_ADMIN_READ_TOKEN`，不要使用模型 API Key。


## Trace V0.3 版本追溯与对比

在 `/traces` 勾选两条历史 Run，进入 `/traces/compare?left=...&right=...`；URL 可刷新恢复。Manifest 保存当时采集的版本与输入指纹，缺失为 unknown；旧记录不补当前配置。对比页按节点身份和节点内重试序号对齐，展示状态、耗时、错误、规则和受控 Evidence/LLM/报告投影。

管理员凭证仍仅由 backend 的 `INSIGHTFLOW_ADMIN_READ_TOKEN` 配置。浏览器按需输入现有凭证，不能写入 VITE_ 变量。新增只读接口 `/api/v1/admin/comparison` 与 `/api/v1/admin/runs/{id}/snapshots` 沿用相同权限；没有编辑或执行权限。

原始数据和完整模型文字不保留在 Trace；数值与引用可读，类别/自由文本只比较哈希，历史未采集内容不可用。Git 不存在时显示 unknown。完整来源、可比性定义、真实示例和限制见 [Trace V0.3](../docs/admin-trace-v0.3.md)。

## 分层导航

后台目录已调整为：运行总览、工作流管理、Prompt 管理、版本与发布、运行追踪、评测中心、Bad Case、系统管理。已有 Trace 与运行对比保留，未开发模块只有明确的占位页。当前分组自动展开；窄屏使用顶部按钮打开导航。

完整路由和接入状态见 [Admin 分层目录](../docs/admin-navigation-v1.md)。新增需求 REQ-0047，旧版本继续保留。

## Prompt Registry V1.0（只读）

已接入同一 V0.1 Registry 数据库，无新快照存储：

- `/prompts`：三节点筛选、最新登记与运行时绑定状态。
- `/prompts/:promptId`：真实模板历史，按登记时间分页。
- `/prompts/:promptId/versions/:snapshotId`：固定正文、组合/重试/Schema 定义、来源与关联调用。
- `/prompts/versions?node=...&left=...&right=...`：两个同节点已存快照的文本 Diff；选择与分页均可刷新恢复。
- `/prompts/calls/:callId`：调用元信息与默认脱敏摘要；完整请求仍需独立快照凭证。

`promptId` 使用 `intent_parser`、`analysis_planner` 或 `insight_generator`；详情以不可变 snapshot ID 定位，不以当前版本号反推历史。版本列表没有记录时显示空状态，只有一个版本时不生成虚假 Diff。最新登记不等于已发布，只有实际运行时绑定且已保存的快照才标注“运行时已绑定且登记”。

访问沿用服务端 Admin 只读凭证与 HttpOnly Cookie。原文还需 `INSIGHTFLOW_ADMIN_SNAPSHOT_TOKEN`，仅按需输入，不存 URL/localStorage/sessionStorage；页面刷新后不自动重现原文。不要将任何凭证写入 VITE_ 变量。

Report 的 RunManifest/LLM Inspector 可跳到实际保存的模板引用；Intent/Planner 无持久 Run 时只显示调用关联，不伪造 Trace。详情不可恢复时标 unavailable。

本轮不提供编辑、Playground、发布或自动评测。具体 API、截图、测试及限制见 [Prompt Registry V1.0 交付](../docs/implementations/prompt-registry-v1.0-2026-10-29/delivery.md)。
