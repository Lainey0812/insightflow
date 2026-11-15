# REQ-0092 Report Draft V2 交付

2026-11-05。实现及真实评测完成，整体业务验收仍有缺口，等待评审。没有修改Admin、Planner、HITL、Engine、状态权威、模型参数或公开报告Schema。

## 实际修改

新增：

- `backend/app/reporting/draft_v2.py`：内部严格选择Schema及动态ID枚举。
- `backend/app/reporting/recommendations.py`：真实字段绑定的受控建议目录、验证和渲染。
- `backend/app/reporting/materialize_v2.py`：证据验证、受控表达、候选隔离及P0覆盖。
- `backend/tests/test_report_draft_v2.py`：23项专项测试。

修改：

- `backend/app/services/analysis_report.py`：新生成路径显式使用V2，非法旧格式无回退；公开结果保持兼容。
- `backend/app/reporting/prompt.py`：report-insights-v2.0；历史V1 Schema helper保留。
- `backend/app/reporting/presentation.py`：明确保留v1.2.3已保存洞察的历史展示兼容。
- `backend/app/llm/templates.py`：登记真实V2组合及动态变量，不修改Intent/Planner指令。
- `backend/app/observability/recorder.py`：新增受控诊断键，不改变Trace行为或状态。
- `backend/app/observability/snapshots.py`：V2输出只读脱敏投影，旧记录继续读取。
- `backend/tests/report_fixtures.py`、`test_report_module.py`、`test_insight_composition.py`、`test_insight_reliability.py`、`test_prompt_registry.py`、`test_workflow_trace.py`：新服务夹具采用V2，保留旧materialize安全测试与历史快照；拒绝、部分状态和实际调用持久化继续验证。

生产调用接口仍为 `AnalysisReportService.generate(intent, validated, execution, profile, ...)`。没有新增业务API，报告生成、查询、页面及下载接口保持原样。原始计算结果继续单独保存和查询。

## 验证

- 后端最终完整回归：1541 passed，约75.73秒。23项新专项均通过。
- Frontend：67 passed；生产构建通过。
- Admin：88 passed；类型检查与生产构建通过。
- 一个既有Starlette/httpx弃用警告保留，无新增测试失败。
- 28例真实qwen3.8-flash链路：80/80 HTTP正常返回；22次Engine执行、27项任务与独立基准一致。
- 已见24例：报告16 complete、4 partial；2预期能力阻断、2审批阻断；报告生成失败0。
- 独立4例：2 complete、2审批阻断。不能据此宣称整体MVP通过。

初次完整回归23处旧格式夹具失败；更新夹具后发现全拒绝错误详情循环引用和V2 Trace投影兼容问题，均在最终回归前修复。初始失败日志同样保留，未用删除安全测试消除失败。原始公开Schema源码未修改。

## 存档和边界

需求原文在 `docs/versions/records/REQ-0092`。before.zip/before.json为改动前源码基线；after.zip/after.json及source-changes.diff为实际交付代码，prompt-v1-v2.diff为新旧Prompt对照。完整评测见 `docs/evaluations/report-draft-v2-2026-11-05/README.md`。

本轮没有重新设计页面或执行浏览器端到端交互，用户看到的Presentation已通过真实API保存与读取复核。历史报告未重写，没有开启Workflow Switch、第二Root或新LLM节点。

剩余风险是：受控说明比自由分析安全，但解释深度有限；建议常偏来源核查；模型仍可能重复或选错类型而导致partial；Intent/审批仍有自然表达映射阻断；长小数及升序叙述需另做产品评审。本轮先交付实际结果，不自动继续优化。
