# Lifecycle 验收及 Admin Trace 只读展示 V0.1

日期：2026-10-30。需求档案 REQ-0067（同意既定流程）、REQ-0068（继续），关联 REQ-0065 Lifecycle Read Model。

## 交付

按已确认顺序完成：只读验收 → 确认无活跃业务 → 重载原后端 → 核对真实查询 → 接入已有 Admin Trace 详情。

- 后端 Lifecycle 31 项专项验收通过；完整后端 **837 passed**。
- Admin 完整测试 **78 passed**（既有 59 + 新增 19）；类型检查、生产构建通过。
- 后端已从原 `backend/` 工作目录运行于 `127.0.0.1:8000`，继续使用现有 `backend/.env`，超时仍为 60 秒。
- Admin 原端口 `5174` 已通过热更新加载新页面。
- 本轮 **backend/app、backend/tests、frontend/src 均没有修改**。业务状态机、Trace 转换、Prompt、审批与分析算法保持原内容。
- 不新增 UI 路由、Root、数据库表、进度事件、模型调用或演示 Run。

## 查看入口

- 分析流程列表：http://127.0.0.1:5174/traces?kind=workflow
- 真实待审核详情：http://127.0.0.1:5174/traces/run_2db5303326b244ceab1162afbf181aba
- 真实 Planner 失败详情：http://127.0.0.1:5174/traces/run_8b798dfc8c34474f82429ccca1d4a221

默认 `/traces` 仍查询报告生成尝试；没有报告时显示真实空状态，并提供“查看分析流程记录”入口。下拉“记录范围”也可选择分析流程。API 默认值没有改变。

## 页面如何读

1. **当前分析任务**：只读取 `GET /api/v1/admin/workflows/{session_id}/lifecycle`，不根据旧 Trace 状态推测整条任务成功。
2. **计算结果、报告交付、过程采集**：分列展示，不把“计算成功”“报告生成已结束”“完整报告”和“完整目标覆盖”混为一个绿灯。
3. **当前需要了解的情况**：用固定业务文案解释服务端 reason_codes。未知或不一致明确要求核查。
4. **版本与记录依据**：可展开查看当前 dataset/plan/validation/approval/execution/report attempt；仅链接实际保存的 Root/Report Run。
5. **下方原有 Trace**：保留节点、事件、错误、历史尝试和不可变 Manifest。历史报告尝试与当前任务分支不同，会明确提示；不把新任务状态写入旧 Trace。

没有 Session 关联的旧 Trace 不请求伪造的生命周期。请求失败只影响新面板，原有节点仍可查看。手动刷新与浏览器刷新都重新查询；不轮询、不自动重跑业务。API 的枚举、会话身份、缺失字段与已知状态一致性经前端检查，非法响应显示查询错误。

## 设计与映射

沿用既有字体（系统字体/PingFang）与灰紫配色：背景 #f6f5f8、面板 #ffffff、正文 #292737、主色 #7360b3；成功 #246449、注意 #895d1c、失败/待核查 #a14941。主状态在左侧强调，计算/交付/采集用同一行定义列表分开；窄屏纵向排列。依据、ID、诊断代码折叠，避免默认展示技术明细。没有虚构阶段完成勾选或进度百分比。

| UI | 唯一数据来源 |
|---|---|
| 主状态、活动 | business_lifecycle.status、activity |
| 计算结果 | business_lifecycle.execution_status |
| 报告生成/内容/覆盖/交付 | 四个独立的 business_lifecycle 字段 |
| 采集说明 | collection、追踪相关 reason_codes；不反推业务执行 |
| 风险和待核查 | reason_codes、consistency |
| 当前版本与关联链接 | source_refs |
| 原节点列表与错误 | 原 traceApi.run / spans / events |

## 修改文件

新增：

- `admin/src/types/lifecycle.ts`
- `admin/src/api/lifecycle.ts`
- `admin/src/features/traces/LifecyclePanel.tsx`
- `admin/src/tests/lifecycle-fixtures.ts`
- `admin/src/tests/lifecycle-api.test.ts`
- `admin/src/tests/lifecycle.test.tsx`

调整：

- `admin/src/pages/TraceDetailPage.tsx`：新增独立面板、按真实 scope 标记 Root Trace。
- `admin/src/pages/TracesPage.tsx`：复用已有 kind 过滤，提供真实流程入口；请求成功空结果不再标成接口未接入。
- `admin/src/types/traces.ts`：兼容已存在的等待状态及 nullable execution_id。
- `admin/src/features/traces/presentation.ts`：等待状态和准备节点的中文标签。
- `admin/src/features/traces/TraceShared.tsx`：采集范围按保存的 scope 展示。
- `admin/src/features/traces/NodeInspector.tsx`：修正“未展示调用”被写成“未记录调用”的不准确提示，不增加模型查询或重构 Inspector。
- `admin/src/styles.css`：生命周期展示与窄屏适配。
- `admin/src/tests/traces.test.tsx`：旧 fixture 显式隔离新 API、增加 Root 列表/详情兼容测试。

## 证据

- [验收与浏览器记录](verification.md)
- [5 个真实任务重载后的 HTTP 返回](live-api-after-reload.json)
- [与上一阶段基线相同的业务库与 Trace 库哈希](post-ui-database-proof.json)
- [完整后端测试](backend-regression.txt)
- [Admin 测试](admin-tests-release.txt)、[类型检查及构建](admin-build-release.txt)
- [源码变更范围](source-verification.json)
- [待审核完整页面截图](awaiting-approval-full.jpg)、[真实失败完整页面截图](planner-failed-full.jpg)

旧需求、源码快照、评测和失败日志全部保留。完成后停止，等待本轮评审。
