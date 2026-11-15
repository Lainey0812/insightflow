# 验收、运行与浏览器验证记录

## 1. 生命周期只读验收

执行 `backend/tests/test_lifecycle.py`：31 passed。完成于 UI 实施前，日志 `read-model-acceptance.txt`。没有修改 Read Model。

读取原业务库 5 个 Session，结果保存 `acceptance-existing-sessions.json`：

- 1 个当前计划待审批，consistency=consistent。
- 3 个准备失败，consistency=consistent。
- 1 个旧 Mock 完成记录，status=unknown，不当作真实成功。

报告失败、重试、旧分支、Engine partial、Trace 缺失等由既有 31 项后端测试覆盖；本轮没有在生产数据库造成功/失败报告或新增模型调用。

## 2. 后端重载

重载前实际查询 Session 活跃状态、executions running、report_generations queued/generating 均为 0，见 `pre-reload-active-check.json`。另查询活跃 Trace Run 和 running LLMCallRecord，均为 0。

旧后端 PID 4034 通过正常 SIGTERM 退出。首次重载从项目根目录启动，配置 `INSIGHTFLOW_DATA_DIR=../var` 解析到上级空目录，真实 Session 查询返回 404。立即停止该进程 PID 10651，从原 `backend/` 工作目录重新启动，现运行 PID 10734、8000 端口。没有修改配置文件或删除任一数据库，误启动的空存储未被当前进程使用。原数据保留。

纠正后逐个查询 5 个实际 Session，新 API 均 HTTP 200，返回与重载前完整相等；`Cache-Control=no-store`。旧报告 Runs API 总数 0；kind=workflow 总数 2；Prompt 查询 200。保存 `live-api-after-reload.json`。

保留现有一分钟超时、本地测试权限、Trace 配置；不更换模型，不调用 LLM。历史失败 Span 的 30.01 秒保持原值，不能用当前 60 秒配置填补历史。

## 3. 浏览器端到端（真实数据）

使用原有 In-app Browser Admin 标签 15，不上传新数据、不批准执行、不发送模型请求：

| 操作 | 实际结果 |
|---|---|
| 原 `/traces` 报告列表 | 返回 0，真实空状态；有“查看分析流程记录”入口 |
| 点击分析流程入口 | URL `?kind=workflow`；显示原有 2 个 Root Run |
| 打开待审核 Root | Lifecycle=等待确认方案；没有关联计算/报告；明确只采集准备阶段 |
| 展开版本依据 | Session revision 8，plan version 1、validation 1.0；只有真实 Root 跳转，没有伪造 Report Run |
| 浏览器刷新 | 原 URL 重新加载；仍为相同待审核状态，5 条真实 Span 保留 |
| 独立刷新任务状态 | 只重新 GET Lifecycle，状态与关联保持一致 |
| 打开失败 Root | Lifecycle=分析失败；原 Planner 的两次 LLM_TIMEOUT 和独立 Span 均保留 |
| 最终页面 | 回到待审核 Root 详情，留给用户查看 |

浏览器控制台本轮最终检查无 error。使用原浏览器默认窄屏宽度检查了纵向布局；没有为截图强行调整视口，没有宣称完整多设备矩阵测试。

截图：`awaiting-approval.jpg` 为默认视口；`awaiting-approval-full.jpg`、`planner-failed-full.jpg` 为原页面完整截图。

## 4. 自动化

- 后端全量：837 passed，1 个既有 TestClient/httpx 弃用警告。
- Admin：78 passed；原 59 项 + 新增 19 项。
- Admin build：包含 `tsc --noEmit`，通过。

新增 UI/API 测试覆盖：严格响应契约、会话错配、非法枚举、遗漏字段、矛盾成功状态、无权限；业务成功但 Trace 缺失；Engine 成功而 Report 失败；旧报告与新计划分离；unknown/inconsistent；API 失败及独立重试；旧 Trace 无 Session；取消请求与丢弃旧响应；实际 Run 链接；kind 过滤与 Root 等待态；Lifecycle 加载失败不隐藏节点。

测试 fixture 只在测试目录，不进入生产 bundle；未使用 Mock 回填真实 API。原测试的报告 fixture 显式补充同一会话的生命周期 fixture，避免意外真实联网。

保留首轮新增测试失败日志：`admin-tests-r2.txt` 与 `admin-tests-final.txt`。失败源于测试选择器：状态文本同时出现在筛选 option 和徽标，报告失败文字同时出现在摘要和原因。修正为按展示区域/元素定位，没有修改或放宽业务判定。`admin-tests-first.txt` 只包含原 59 项基线测试，不能作为新增功能验收。最终以 `admin-tests-release.txt` 为准。

## 5. 兼容和数据保护

本轮没有修改 backend 或原数据分析前端源文件。业务库、Trace 库与上一阶段只读验收 dump 哈希相同（`post-ui-database-proof.json`）；原注册表仍有 6 个模板快照、14 次历史调用。没有生成额外模型调用、Trace 或业务结果。

API/权限/Schema、Report Trace 默认筛选、Prompt Registry 和只开放 Trace/Prompt 的菜单规则保持不变。UI 新增可选的 kind=workflow，不更改后端默认 kind=report_generation。

## 6. 仍然存在的边界

- ReportGeneration 只保存最新 attempt，UI 明示历史不保证完整。
- Lifecycle 的跨库查询非原子，running 仅是保存活动，不是进程心跳。
- 准备阶段与 Report 外的节点埋点仍有缺口；本轮只读展示，没有补 Span 或改变 Root 状态转换。
- 当前真实数据库没有已批准执行/报告记录；报告失败、部分成果及旧报告分支提示由后端真实临时仓储链路和组件测试验证，未宣称生产浏览器跑过这些不存在的记录。
- 节点 Inspector 仍主要适配报告诊断，Intent/Planner 独立调用详情可到现有 Prompt 管理核查；未额外扩展调用查询和节点埋点。
- 不做自动重试、审批、报告修复、轮询或新的 Progress UI。
