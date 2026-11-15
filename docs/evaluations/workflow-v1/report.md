# Workflow V1 验收记录

日期：2026-10-27。真实模型：qwen3.8-flash；Prompt：intent-v1.3.3 / planner-v1.2；原 Intent/AnalysisPlan/ExecutionResult Schema 不变。两节点均 enable_thinking=false，30 秒超时、最多 2 次尝试。没有调用报告模型。

## 结论与限制

已通过真实浏览器上传 CSV → 真实画像 → 真实 Intent → 真实 Planner → 原 Validator → 原 HITL 删除/批准 → 原 Engine → 持久化/刷新恢复，并与独立 Pandas 计算逐行一致。澄清、服务重启恢复及显式约束阻断在浏览器实测。

**尚不能作为全部需求场景的无保留验收：现有 HITL 缺少结构化约束验证/解决入口，对所有非空 Intent constraints 拒绝批准。** 本轮忠实保留约束并阻断，未放宽原审批规则。带筛选、时间、指标或 Top N 的请求可能产生 F2 计划，但不能直接完成执行。后续需独立补齐验证证明契约。本轮终点是 ExecutionResult，无 Report Insight Generator 接线。

## 真实浏览器测试

浏览器通过 127.0.0.1:5173 的正常界面操作。实际文件为 [workflow-sales.csv](../../../examples/workflow-sales.csv)，8 行 3 列，是明确的合成验收文件；并非客户生产数据或 Mock 统计返回。文件 SHA-256：388522fd4942b01bec122cbf6539b0d16459058c23c1d4b34f5adaa884ef81f1。

为保护已有数据，服务使用独立目录 `var/workflow-v1-e2e`。测试记录器仅包装原真实 Provider，记录 purpose、模型、Prompt/Schema 哈希、必要上下文与实际返回，未增加推理节点，也未保存 API Key。完整 [7 次真实调用](live-model-calls.json) 均正常返回且 is_mock=false：4 次 Intent、3 次 Planner；请求中无完整数据集，未调用报告节点。日志不构成大样本语义质量验收。

### 1. 完整执行及版本恢复

- 原问题：“探索这份数据的主要特征和差异。”
- session_id：a8f4816ff2cd483e8e7d52f2958c4be2。
- 页面提交后立即得到会话；模型处理中刷新，恢复到 PLANNING，继续得到 3 个真实 P0/F2 任务。
- 在浏览器删除产品分析 T3，生成不可变 v2，保留总体与地区任务。版本记录见 [plan versions](browser-plan-versions.json)。删除并不自动批准。
- 停止并重新启动后端，重新加载页面仍为 v2/awaiting_approval；未重新调用模型、无执行。见 [重启前状态](browser-before-restart.json) 与 [重启后截图](awaiting-after-restart.jpg)。
- 用户测试操作点击“确认并执行”，原 HITL 保存 approval_2410f7ce1183459387e13e44f3694e06；原 Engine 返回 exec_b3d8c957d5d348eab66b87dec2f39365，整体 success、两个任务 success。
- 完成后刷新仍读取同一 execution_id、同一结果。另一次后端重启后的恢复记录见 [browser verification](browser-verification.json)。
- 原始 [审批快照](approval-record.json)、[执行结果](execution-result.json)、[最终会话](completed-session.json)、[完成后再次重启的结果截图](completed-after-restart.jpg)。未创建 Report，也没有旧 Mock plans/execution_result。

独立 Pandas 从原始上传 CSV 重新计算，不调用任何 Engine 内核。两个任务的所有返回行逐项一致，见 [Pandas 对照](pandas-verification.json)，可运行 `python docs/evaluations/workflow-v1/verify_saved_result.py` 复核保存产物。

| 项目 | Pandas / Engine 一致结果 |
| --- | --- |
| 数据量 | 8 行 |
| 销售额总和 | 3648 |
| 销售额均值 | 456 |
| 最大 / 最小 | 809 / 101 |
| 华南 | 1515 / 3 条 |
| 华东 | 1117 / 3 条 |
| 华北 | 1016 / 2 条 |

### 2. 真实澄清暂停与继续

session_id：a2e85020bffb4a3aac937ff00deca50b。

“帮我处理一下。”实际返回 undetermined/clarify，保存问题后暂停，没有 Planner/审批/执行。见 [暂停状态](clarification-paused.json) 与 [截图](clarification-paused.jpg)。补充“先探索这份数据的主要特征和差异。”后重新解析，再调用真实 Planner，进入待审核。原始 user_goal 保留，intent_history=2、clarification_answers 保留完整答复，仍无批准/执行。见 [恢复状态](clarification-resumed.json) 与 [截图](clarification-resumed.jpg)。

### 3. 显式约束与审批阻断

session_id：c04d2a936bd64b8f88587bf035c1b3fc。

请求：“只看华东地区，按产品统计销售额总和，取前一名。”真实模型保留筛选、指标、分组和 Top 1，计划为一个 P0/F2，链路 filter → group_aggregate → top_n，coverage=complete。原 HITL 仍要求验证 constraints，页面逐条展示阻断，确认按钮 disabled；无批准、无执行。见 [真实状态](constraint-blocked.json)、[DOM](constraint-blocked-dom.txt)、[截图](constraint-blocked.jpg)。

这条是可见的集成限制，不是“显式约束执行通过”。没有通过修改意图或自动勾选规避。

## 自动化检查与 16 类场景

最终后端：527 passed，7.89 秒，1 个既有 Starlette/httpx 弃用警告。前端：30 passed（原 24 + 新 6）。TypeScript/Vite 构建通过。原 511 个后端测试保持通过，本轮新增 16 个参数化实例。

离线 Workflow 测试显式注入受控 Provider；真实 Profiler/Validator/HITL/Engine/SQLite 均运行，但**这些 Provider 输出不能被记作真实模型质量证据**。受控错误用于确定性验证失败分支。真实模型证据仅以上浏览器 7 次调用。

| 场景 | 自动化覆盖 / 浏览器证据与边界 |
| --- | --- |
| 1 明确需求正常执行 | CSV/XLSX 整合与 Pandas 对照；显式 constraints 的真实请求按既有 HITL 阻断，见案例 3，不宣称全部打通 |
| 2 澄清后继续 | test_clarification_pauses_then_continues_and_versions_answers；真实浏览器案例 2 |
| 3 单一统计 | 删除后保留一个任务的实际执行；浏览器受限请求也只生成一个任务 |
| 4 多筛选多步骤 | test_multi_filter_exclusion_group_sort_top_n_chain_as_reviewed_exploration；真实内核/Pandas，输入为待审核探索提案，不冒充显式约束已验证 |
| 5 排除条件 | 同上含 ne 排除；Intent 显式约束的保留/拒绝另测 |
| 6 排序/Top N | 同上 sort/top_n 及真实浏览器案例 3 的受控计划（审批阻断） |
| 7 F0 核心 | F0 任务保留，blocked 拒批；partial 保留 F0，要求警告确认并由 Engine 跳过 |
| 8 F1 派生 | derive extract_year → group_aggregate，原 Validator 判 F1，执行与 Pandas 一致 |
| 9 未确认统计口径 | defer 保留，BLOCKING_UNCERTAINTY；不能勾选解除 |
| 10 删除重验 | 版本不可变；浏览器 T3 删除生成 v2 并执行 |
| 11 旧审批失效 | 批准 v1 后删除生成 v2，旧请求被拒，新版重新批准 |
| 12 重复执行 | 相同 execution_request_id 返回同一结果；原幂等回归保持 |
| 13 单任务失败 | 注入单内核故障，其他任务保留 success，整体 partial_success，错误绑定 step_id |
| 14 LLM 超时/失败 | 受控 LLM_TIMEOUT/LLM_HTTP_ERROR，持久化 FAILED，显式重试复用检查点；禁止 Mock 来源 |
| 15 刷新恢复 | 6 个前端测试含活动状态轮询/澄清/令牌/重试；浏览器规划中与完成后刷新 |
| 16 重启恢复 | 待审核重启读取；中断 VALIDATING 保存失败后仅重试验证，无新增模型调用；浏览器批准前及完成后真实重启 |

执行空结果、支持类型、版本不一致、未批准、不支持操作、完整结果与预览、来源/权限和不可变审计的既有回归同时通过。没有为了接线改变操作内核或 Schema。

## 剩余风险与 Bad Case

1. 高影响：UNVERIFIED_CONSTRAINTS 使带显式约束的计划无法批准，即便操作参数看似正确且 F2。需要确定性约束证明契约，不应放宽当前闸门。
2. 未解决 defer 只能阻断，当前没有结构化答复/解决接口；不能靠规划假设消除。
3. 进程内准备任务不具备持久队列能力；中断后明确失败，需显式重试。只支持单进程本地运行。
4. 既有 Intent/Planner 语义 Bad Case 未在本轮消失；7 次调用只验证接线和样例。用户此前确认的 Planner 评测优先级不代替每个运行时计划的实际审批。
5. 兼容 API 在两个模式标志均省略时仍是旧 Mock；新 UI 固定选择 real_workflow，真实执行入口拒绝旧批准。若未来删除兼容路径，应单独迁移历史客户端。
6. 会话、文件和令牌仍沿用本地单用户设计，无多用户权限体系。未扩展 Report、AI 修订、复杂派生或队列。

核心保护文件 13/13 哈希未变，修改明细、状态图及接口见 [Workflow 文档](../../workflow-v1.md)。
