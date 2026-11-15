# Admin Console V0.1 验收证据

本目录是 REQ-0042 的工程验收记录，没有生成运行成功率、虚假 Trace 或模型评测数据。

## 自动化结果

- `admin-typecheck-01.txt`：TypeScript 检查通过。
- `admin-tests-01.txt`：14 个测试全部通过。
- `admin-build-01.txt`：Admin 构建通过。
- `frontend-tests.txt`：原前端 52 个测试通过。
- `frontend-build.txt`：原前端构建通过。
- `backend-tests.txt`：后端 670 个测试通过，1 个现有弃用警告。
- `port-conflict.txt`：保持第一实例运行，第二次尝试 5174 被拒绝；这是预期成功的冲突检测。

## 浏览器检查记录

使用 Codex In-app Browser，2026-10-28。本轮没有上传真实业务数据或调用未实现的 Admin API。

| 场景 | 操作与观察 | 结果 |
| --- | --- | --- |
| 开发概览 | 打开 `127.0.0.1:5174/dashboard`，看到“暂无运行数据” | 通过 |
| Trace | 侧栏导航进入 `/traces`，刷新后保留“暂无可查看的 Trace” | 通过 |
| 版本 | 直接进入 `/versions`，刷新后保留“尚未接入版本数据” | 通过 |
| 设置 | 直接进入 `/settings`，刷新后保留公开 Base URL 与未认证提示 | 通过 |
| 根路径 | 进入 `/` 后跳转到 `/dashboard`，刷新后页面正常 | 通过 |
| 404 | 进入 `/not-a-page` 并刷新，均显示“页面不存在” | 通过 |
| 侧栏 | 点击收起后隐藏侧栏，再展开后四个导航恢复 | 通过 |
| 构建产物 | `127.0.0.1:4174` 的四个路由逐个直接访问并刷新 | 通过 |
| 浏览器日志 | 开发与构建预览捕获 warn/error 均为空 | 通过 |

开发截图使用实际窄屏面板，没有手工调整尺寸；构建预览在后台浏览器的默认桌面尺寸捕获。`preview-route-snapshots.json` 保存 Trace、版本、设置的直接访问和刷新 DOM。概览构建截图证明布局、页面及空状态正常。

![Admin 构建概览](dashboard-build.jpg)

## 文件保留

`before-manifest.json` 保存改动前原有前后端文件 SHA-256；`preservation-check.json` 是最终逐项比较。`admin-source-manifest.json` 列出全部新增 Admin 源文件。`admin-console-v0.1-source.zip` 是源码快照，排除 node_modules、dist、缓存与真实 .env，保留不含密钥的 `.env.example`。

本轮需求原文已保存至 `docs/versions/records/REQ-0042/request.md`。旧版本、数据库与上传文件均未清理。
