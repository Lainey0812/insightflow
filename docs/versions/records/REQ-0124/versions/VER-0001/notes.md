# Trace 页面与状态重构

REQ-0124，关联 REQ-0123。这一版把 Trace Run 和 Trace Span 的状态改成五项，并按五项重做 Admin 的 Trace 列表和详情。REQ-0123 只做了页面上的归类显示，写入仍使用旧词；本版替换写入和读取后的规范值。

## 状态

Trace Run 与 Trace Span 只使用 `success`、`error`、`running`、`skipped`、`suspended`。

历史记录不改写 SQLite 原文。读取和属性赋值时把旧词归进五项：

- `complete`、`succeeded` → `success`
- `failed`、`partial`、`unavailable` → `error`
- `queued` → `running`
- `interrupted`、`waiting_input`、`waiting_approval`、`cancelled` → `suspended`

`model_copy(update={'status': ...})` 不会触发校验。`update_run` 在检查转移之前先对 `run.status` 赋值，让旧词在落库前变成新词。

Workflow 根记录允许的转移：`running` 可以到 `running`、`suspended`、`error`；`suspended` 和 `error` 可以回到 `running`。`waiting_approval` 并进 `suspended` 之后，暂停中的准备阶段可以恢复。报告生成记录只从 `running` 转到 `running`、`success`、`error`、`suspended`。

列表筛选 `success` 会同时命中旧的 `complete`、`succeeded`。直接查询一个旧词（例如 `partial`）仍只匹配该原文，不会把已经写成 `error` 的新记录算进去。

进程恢复仍按库里的 `queued` 和 `running` 查找未结束记录，写回时使用 `suspended`。

## 没有并进来的状态

业务生命周期仍是 `created`、`running`、`waiting_input`、`waiting_approval`、`succeeded`、`partially_succeeded`、`failed`、`interrupted`、`unknown`。报告任务、执行任务、回归、回放、Bad Case、LLM 调用状态，以及 workflow policy 里的 `observed_root_status`，都保持各自的词。生命周期里的 `report_status` 仍是 `complete`、`partial`、`unavailable`；和 Trace 对比时先做同样的归并，避免成功报告因为 `complete` 对不上 `success` 而被判成冲突。

## 页面

`/traces` 列表列：Trace ID、用户问题摘要、触发时间、状态、耗时、Tokens / 费用、查看详情。状态筛选项是全部和五项。搜索按 Trace ID，或按业务会话里的用户目标做包含匹配。摘要最多 80 字，只出现在列表接口，不写入 Trace 记录。

Token 和费用没有采集，列表和节点 Metrics 显示「未采集」，不写成 0。temperature 未知时同样显示未采集。

详情仍是 `/traces/:runId`。左侧按 `parent_span_id` 显示节点。真实节点归类：`intent_parser`、`analysis_planner`、`insight_generator` 为 LLM；`plan_validator`、`fact_validator` 为 Condition；`data_profiler`、`evidence_builder`、`report_assembler`、`report_persistence` 为 Tool。没有 Router 和 RAG 节点，页面不补造；对不上的名称显示未归类。

右侧四个页签：Input / Prompt、Raw Output、Metrics & Token、Error Stack。原始 prompt 和输出仍不放进 Trace 事件；已有的模板快照链接保留。节点没有 `error_code` 时，Error Stack 使用已保存事件里的错误代码，并说明没有异常栈原文。

列表上的对比勾选去掉。对比仍从「通过 Run ID 对比两次运行」进入。

生命周期接口里的 observed span 状态改为这五项。Admin 校验原先只接受旧词，真实返回 `success` / `error` 时会把整份生命周期当成请求失败。业务生命周期字段没有改。

## 验证

后端相关测试在排除既有的 git sandbox 失败后通过。Admin 的 Trace、对比、Prompt、生命周期测试和 `tsc --noEmit` 通过。

浏览器打开 `http://127.0.0.1:5174/traces?status=error`。错误筛选返回记录；详情节点显示成功 / 错误，以及 Tool、LLM、Condition。切换到洞察生成后 Inspector 标题变为洞察生成。Metrics 中 temperature 和 Token 为未采集。事实校验的 Error Stack 显示事件中的 `REPORT_UNVERIFIED_FACT`，并说明没有异常栈原文。生命周期面板能加载，显示本分支活动已结束。
