# Admin 仅开放 Trace 与 Prompt 管理

REQ-0062，2026-10-30。保留现有目录和源码，运行总览、工作流管理、版本与发布、评测中心、Bad Case、系统管理显示灰色且不可点击。Prompt 下未实现的 Playground 同样禁用；可用子入口为 Prompt 列表、版本详情与 Diff、Run Explorer、Trace Detail。

禁用栏目采用原生 disabled 按钮，禁用子入口没有 href、没有点击回调，不只改变文字颜色。enabled 显式标记目前开放的四个静态页面。直接访问其他已登记模块地址显示“暂未开放”，不加载其原页面；保留原路由和实现，后续可以重新启用。这是前端功能开放范围控制，不是新鉴权系统；服务端权限不变。

Admin 根路径、品牌入口和 404 返回入口改为 /traces。动态 Trace Detail、/traces/compare、Prompt 历史/版本/调用详情和 Diff 保留。Trace 对比的导航归属改为运行追踪，避免指向已禁用的版本与发布。没有修改后端、Prompt、业务流程或数据记录。

修改文件：

- admin/src/app/navigation.ts
- admin/src/app/routes.tsx
- admin/src/layouts/AdminLayout.tsx
- admin/src/pages/ModulePlaceholderPage.tsx
- admin/src/pages/NotFoundPage.tsx
- admin/src/styles.css
- admin/src/tests/navigation.test.tsx
- admin/src/tests/routes.test.tsx

原测试中可进入占位页面/根路径进 Dashboard 的断言按本次要求更新；复用原 Admin 测试，没有新建重复测试框架。npm test：8 个文件、59 项通过；npm run build（含 TypeScript 检查）通过。完整日志 tests-attempt01.txt、build.txt 保留。未改后端，因此没有重复运行后端全量测试。

真实浏览器：现有 /traces 可读取真实空列表；菜单 DOM 核对六个未开放顶级栏目为 disabled、灰色 rgb(181,177,189)，无链接；Prompt 列表可正常读取三个节点的真实快照；直接访问 /workflows/planning 显示暂未开放；Admin 根路径重新加载跳至 /traces。浏览器截图 navigation.jpg 与 DOM 状态 browser-navigation.json 已保存。不生成演示 Run 或调用模型。

修改前后完整 Admin src 源码分别保存在 before-source.zip / after-source.zip，附哈希清单。历史代码、需求与评测不删除、不覆盖。当前本机开发服务已热更新，可直接检查 Admin 页面。
