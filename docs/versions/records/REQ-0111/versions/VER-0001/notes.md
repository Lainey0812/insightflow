# 失败诊断 V1：节点输入摘要与失败归因

日期：2026-11-09。需求：REQ-0111（确认 REQ-0109 建议顺序第一步），关联 REQ-0110。

## 改动

后端
- 新增 `backend/app/observability/failures.py`：按 error_code 确定性归类为 file_input / data_content / model_service / model_output / capacity / plan_blocked / interrupted / unclassified；常见代码给出具体排查提示。`first_failure` 取最早失败/中断节点；无失败节点时依次使用业务 error、报告生成 error。
- `observability/recorder.py`：SAFE_KEYS 增加 11 个 input_* 键。
- `workflow/orchestrator.py`：`observed_node` 在 Span 开始时写入输入摘要（data_profiler：表头行、工作表、编码、分隔符、扩展名、文件大小；intent_parser：需求字数、澄清答复数、字段数、数据集版本；analysis_planner：字段数、数据集版本）。摘要构造异常时置空，不影响业务。不记录文件名、需求原文、数据值。
- `services/workflow_observability.py`：详情与列表项新增 `failure`；列表支持 `failure_category` 过滤（未知类别 422）。该过滤需逐条读取完整视图。
- `api/admin.py`：列表路由增加 `failure_category` 参数。

Admin
- `types/workflows.ts`、`api/workflows.ts`：WorkflowFailure 类型与响应校验。
- `features/workflows/WorkflowShared.tsx`：failureLabels、InputSummary、FailureCard。
- `pages/WorkflowDetailPage.tsx`：失败定位卡片；节点“输入摘要”；失败/中断节点默认展开，卡片可锚点跳转到节点。
- `pages/WorkflowsPage.tsx`：失败归因筛选；异常列显示类别与 节点/错误代码。
- `styles.css`：卡片样式。

修改前副本：docs/implementations/failure-diagnosis-v1-2026-11-09/before/。

## 验证

- 后端新增 tests/test_failure_diagnosis.py 5 例；全量 1643 passed，1 failed 为既有 test_git_unknown_without_repo...（沙箱禁止写 .git/hooks），与本次无关。
- Admin 新增 failure-diagnosis.test.tsx 4 例；全量 92 passed，typecheck、build 通过。
- 真实数据核验：真实库的临时副本（未写入原库）+ 临时后端 8010 + 临时 Admin 5175。历史 4 个 EMPTY_HEADER 归为 file_input，无输入摘要（早于本功能）；成功/部分成功/待审批 failure=null。用 TC07 数据 recruitment_header6.csv 故意填 header_row=5 新建一次：画像失败 CSV_ROW_WIDTH_MISMATCH，输入摘要 header_row=5、utf-8-sig、","、.csv、526 字节，页面卡片与节点展开正确，列表筛选 file_input 共 5 条。验证后关闭临时服务并删除临时副本。

## 过程中修正

- 首版把 CSV_ROW_WIDTH_MISMATCH 归为 data_content。真实样本显示表头行填错也触发该错误，改为 file_input，提示同时检查表头行与分隔符。
- InputSummary 对 null 值原显示“未采集”，改为“未指定”。

## 限制

- 运行中的 8000 后端未重启，尚未加载本次代码；需用户按原环境变量重启后生效。
- hitl、analysis_engine、报告各节点不经 observed_node，未新增输入摘要；其失败仍可按 error_code 归类。
- 归类仅基于错误代码，不判定根因；新错误代码需补规则，否则为 unclassified。
- 模型原始返回仍只存 hash（下一步）。
