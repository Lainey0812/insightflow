# Workflow 详情质量信号 V1（REQ-0113）

## 修改依据

REQ-0113：用户确认继续 Admin 路线第 3 步中的“详情页质量信号”。人工标注与“存为 Bad Case”不在本版本范围内。

## 实现

- 新增 `backend/app/observability/quality.py`：`quality_signals(nodes, llm_calls, business, reports)` 只从已采集的 Span 属性、Prompt Registry 调用记录和业务生命周期推导信号，并分为 `normal`、`attention`、`unavailable` 三档；未采集的项 `value=None`，不按 0 计。
- `recorder.py`：`SAFE_KEYS` 增加 `f0_count/f1_count/f2_count/unmet_core_count`；新增 `feasibility_counts(validated)`。
- `analysis_planner.py`、`plan_review.py`：两处 `plan_validator` Span 写入上述计数。
- `workflow_observability.py`：详情与列表项都增加 `quality`。
- Admin：类型、`isWorkflow` 校验、`QualityCard`（详情页按阶段分组）、列表“质量提示”列、样式。

## 信号清单

需求澄清轮数、规划覆盖度、规划中被阻断的任务数、F0 不可执行任务数、F1 需数据转换任务数（仅提示，不计入需关注）、未覆盖的核心需求数、用户修改计划次数、执行结果（以业务库为准）、洞察候选数与事实校验拒绝数（以被采用的报告尝试为准）、报告生成尝试次数、报告完整度、目标覆盖、模型请求重试次数、模型调用失败数。

## 验证

- 后端：`tests/test_quality_signals.py` 4 项通过；全量测试 1655 项通过、2 项失败。`test_trace_comparison.py::test_git_unknown_without_repo_and_actual_commit_when_available` 是已知的沙箱限制；`test_planner_v1_live_contract.py::test_total_deadline_shared_by_retries` 只在全量负载下因计时失败，单独复跑 3 次均通过。
- Admin：`tsc -b` 通过；vitest 14 个文件、99 项通过（新增 `quality-signals.test.tsx` 3 项）；`npm run build` 通过。
- 真实库副本（复制 `var/` 到临时目录，未改动原库）上的 10 个 Workflow：部分成功的一条标出用户修改计划 1 次、事实校验拒绝 1 条、报告完整度 partial；一条成功的报告尝试了 2 次；画像阶段失败的 4 条全部为“未采集”；旧记录的 F0/F1/未覆盖核心需求数显示“未采集”。

## 修改前副本

`before/` 目录保存修改前的 10 个文件。
