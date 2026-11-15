# InsightFlow ↔ Admin 打通现状只读审计

日期：2026-11-09（Asia/Shanghai）。需求：REQ-0109，关联 REQ-0107、REQ-0108。本轮只读：不改业务代码、Prompt、数据库或历史记录。

## 检查范围

- 代码：admin/src（路由、导航、Workflow/Trace/Prompt 页面）、backend/app/api/admin.py、services/workflow_observability.py、observability/*、frontend/src。
- REQ-0107 审计后 admin/src、backend/app、frontend/src 无文件变动，其结论仍适用。
- 运行态：后端 127.0.0.1:8000 与 Admin 127.0.0.1:5174 在运行；用户前端 5173 未运行。后端实际数据目录为工作区上层 vibe-coding/var（非 insightflow/var）。
- 真实数据：11 个 Session，10 个已登记 Workflow；另 1 个为 manual_review 兼容模式，按设计未登记 Workflow，Admin 不可见。

## 真实 Workflow 分布（Admin API 实际返回）

| 业务状态 | 数量 | 说明 |
|---|---:|---|
| succeeded | 2 | 16 节点全链路，3 次 LLM 调用 |
| partially_succeeded | 1 | fact_validator=partial，报告 partial，Admin 正确标出 |
| waiting_approval | 3 | 停在 HITL，节点 5–7 个 |
| failed | 4 | 全部 data_profiler / EMPTY_HEADER，均为指定表头行（header_row=5 或 1）与文件不符 |

全部 collection=observed，无采集缺口 finding。

## 已完成

- 身份：每次 real_v1 会话登记 workflow_id + root_run_id，Root + Node Span 两层。
- 节点覆盖：data_profiler、intent_parser、analysis_planner、plan_validator（4 个校验位置）、hitl、analysis_engine、evidence_builder、chart_builder、insight_generator、fact_validator、report_assembler、report_persistence；无证据时 insight/fact 记录 skip。
- 生命周期事件：started / resumed / waiting_input / waiting_approval / failed / interrupted / callback_ignored。
- 业务状态与 Trace 分离：业务状态只读 Business DB，Trace 故障不推翻业务结论；Session 读取期间变化标 unknown。
- Admin 页面：Workflow 列表（筛选、分页）、Workflow 详情（业务卡片、关联 ID、节点时间线、事件、LLM 调用、重入、报告尝试）、Run Explorer、Trace 对比、Prompt 列表/历史/版本/Diff/调用详情。
- LLM 调用与 Prompt 模板快照关联；完整请求需额外 snapshot token。
- 测试：Admin 88 passed + typecheck 通过；前端 97 passed；后端 1638 passed、1 failed（test_git_unknown_without_repo...，沙箱禁止写 .git/hooks 导致 git init 失败，非代码缺陷）。
- 15 例测试集离线自检通过（verify_suite.py）。

## 未完成 / 缺口

1. 两个前端互不连通：frontend 不接收、不显示 workflow_id，无跳转 Admin 链接；只能在 Admin 手动按时间猜对应运行。
2. 无自动刷新：Workflow 列表与详情仅手动刷新，运行中节点不能实时看到。
3. 失败诊断信息不足：失败 Span 仅 error_code，无输入参数（如 header_row、文件名）和可读原因；本次 4 个 EMPTY_HEADER 仅凭 Admin 无法知道用户填了第几行。
4. LLM 响应只存 hash，无法还原模型原始返回或被拒候选文本（REQ-0107 P0）。
5. 节点展开以原始 JSON 为主，缺少统一诊断面板（REQ-0107 P0）。
6. Dashboard、工作流管理 5 页、版本与发布、评测中心、Bad Case、角色/审计均为占位。
7. 未覆盖真实样本：clarification 暂停/继续、LLM 超时或失败、Engine 失败、retry-preparation、进程中断、Trace 故障；代码已有埋点，但库中无真实记录。
8. 15 例测试集尚未执行（docs/testing/runs 不存在）。
9. 小问题：/health capabilities 仍写 planning_and_reports=real_planning_report_not_connected、workflow=v1_real_until_execution_result，与已接通报告的现状不符；list 接口对每条记录做完整读取，数据量大时会慢；manual_review 会话不在 Admin 中。

## 建议顺序

1. 前端显示 workflow_id 并提供“在 Admin 中查看”链接（最小打通）。
2. 失败 Span 记录安全的输入参数摘要与可读原因。
3. 非终态详情页自动轮询。
4. 用 15 例测试集跑一轮真实回归，补齐 clarification、失败、partial 样本，并核对 Admin 定位能力。
5. 再做 LLM 响应受控快照与统一诊断面板。
