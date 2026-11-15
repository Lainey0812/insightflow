# 洞察模板组合版本 v0.14（REQ-0122）

## 修改依据

REQ-0122。用户询问 `PROMPT_VERSION_CONFLICT`「同一模板版本已有不同内容，需登记新组合版本」应该怎么处理。

## 原因

Insight Generator 的版本号仍是 `report-insights-v2.1.1+composition-v0.13-confirmed-text-scope-v1`，库中内容哈希为 `4ec1b787f390`。当前加载内容是 `pt_1e3080163df80`。差异只在受跟踪的 `app/review/confirmed_scope.py` 源码、源码哈希和已加载代码指纹。报告 Prompt 正文没有变化。登记库拒绝覆盖同一版本，模型请求因此不会发出。意图理解和计划生成当时已经登记成功。

## 处理

组合版本升为 `composition-v0.14-hitl-scope-question-v1`。新快照另存，不改旧行。Prompt 正文和模型参数未改。后端由文件监视重新加载。

## 验证

- `test_prompt_startup_registration.py` 与 `test_prompt_registry.py` 共 35 项通过。
- 日常库现在 12 条模板。三个节点的运行登记都是 `registered`，各 4 个版本。
- 旧洞察哈希 `4ec1b787f390` 仍在。
- 新版本：`intent-v1.3.3+composition-v0.14-hitl-scope-question-v1`、`planner-v1.2+composition-v0.14-hitl-scope-question-v1`、`report-insights-v2.1.1+composition-v0.14-hitl-scope-question-v1`。
- 启动日志不再出现模板登记失败。没有替用户重新生成报告。

## 修改前副本

`before/backend/app/llm/templates.py`。
