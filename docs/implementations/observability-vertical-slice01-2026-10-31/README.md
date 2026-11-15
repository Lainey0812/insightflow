# Observability MVP Vertical Slice 01 — 归属检查阻断

REQ-0083；2026-10-31（Asia/Shanghai）。本文件为本轮实施状态与阻断证据，不扩展Lifecycle设计契约。

## 结论

第一步只读审计已完成。四个目标节点均存在部分埋点，不应再包一层造成重复记录；但当前生产准备入口没有显式Business Workflow归属，仍按Session选Root。

按照本次原文“若现有运行路径无法可靠确定 Workflow 归属，则停止该节点接入并报告阻断原因，不通过 Session 猜测 Workflow”，四节点接入均停止。没有通过造Workflow ID、按Session推断、临时回填或新增平行Run绕过。

**没有完成本次Vertical Slice验收。** 未新增Adapter/异常测试，未启动CSV/LLM新流程，未提供虚假的新Trace或耗时；未修改业务代码、数据库Schema、Engine、Reporting或冻结契约。

## 四节点实际入口与已有埋点

| 节点 | 真实入口 | 已有埋点 | 接入状态 |
|---|---|---|---|
| Data Profiler | `WorkflowOrchestrator._prepare_real`调用`observed_node(...,'data_profiler',...)` | 已有真实准备Span与行列数/数据版本摘要 | 被Workflow归属缺失阻断 |
| Intent Parser | 同函数调用`observed_node(...,'intent_parser',...)` | 已有准备Span、operation/Call关联、next_action | 同上 |
| Analysis Planner | 同函数调用`observed_node(...,'analysis_planner',...)` | 已有准备Span、覆盖和任务数 | 同上 |
| Plan Validator | `AnalysisPlannerService.plan`内部校验，以及`PlanReviewService.validate_v1`保存前复核 | 两次真实校验各有Span；内部校验可能嵌套 | 同上；不能额外再造第三次校验Span |

源码定位：

- `backend/app/api/routes.py:49` 创建Session；第75行调用`workflow.trace_created(state)`；没有原子创建Business Workflow或携带Workflow ID。
- `backend/app/workflow/orchestrator.py:44` `trace_created`没有保存/传递Workflow绑定；第48行`observed_node`已经记录节点。
- `backend/app/observability/workflow.py:11` `register_root`随机产生Run ID，manifest仅初始Session/file等绑定。
- `backend/app/observability/workflow.py:40` `preparation_context`调用`repository.workflow(session_id)`。
- `backend/app/storage/trace_repository.py:55` `workflow`只以Session过滤kind=workflow。
- `backend/app/workflow/orchestrator.py:249` `_prepare_real`仅收session_id、trace和revision guard。
- `backend/app/services/analysis_planner.py:48` 内部`plan_validator`；`backend/app/services/plan_review.py:113` 保存/复核的`plan_validator`。
- `backend/app/storage/workflow_reader.py:34` 只读Reader在无登记时明确报`BUSINESS_WORKFLOW_NOT_FOUND`，Expand不会自动创建。

精确函数起止行见[source-index-corrected.json](source-index-corrected.json)。

## 持久归属核对

按现有本地启动器`os.chdir(project/backend)`与`backend/.env`的相对Data Dir解析，实际项目数据位于`insightflow/var`。本轮未启动或确认某个运行中的后端实例，因此这里只断言这份本地项目存量数据，不声称采样了新活动请求。

[readiness-corrected.json](readiness-corrected.json)为`mode=ro`、`PRAGMA query_only=ON`和读事务结果：

| 事实 | 数量 |
|---|---|
| Sessions | 6 |
| real_v1 Sessions | 5 |
| Business Workflows | **0** |
| Session Workflow routes | **0** |
| WorkflowPlanVersion仓 | **0** |
| Workflow Root TraceRun | 3 |
| 独立Report Run | 1 |
| trace_workflow_links | **0** |
| Root manifest显式workflow_id | **0** |

已有目标节点记录：Profiler 3、Intent 4、Planner 4、Validator 2（其中1个嵌套）。它们证明有历史准备追踪，但不能代替缺失的Business Workflow归属。原始状态/时间/耗时见[existing-traces-readonly.json](existing-traces-readonly.json)，明确标记为旧记录而非本轮运行。

最初readiness.json按检查进程cwd解析相对路径，读到工作区层级另一份空库；保留原始结果。核对实际本地启动器后使用readiness-corrected.json，未通过改历史结果或删库消除差异。两库读取是各自事务，不宣称跨库原子快照；源代码缺乏Workflow传播这一事实独立于统计数量。

## 执行步骤完成情况

| 步骤 | 结果 |
|---|---|
| 1. 审计入口/避免重复 | 完成，确认4节点已有埋点和归属阻断 |
| 2. Adapter及接入 | 按严格边界停止，未修改 |
| 3. 新成功/失败/重试/超时/Schema/Trace故障测试 | 未新增、未执行；没有用旧测试冒充本次验收 |
| 4. 真实CSV新运行 | 未执行；新请求仍只会产生无显式Workflow归属的Session Root，无法满足验收 |
| 5. Trace/耗时交付 | 仅提供现有持久记录的只读证据，未声称Vertical Slice通过 |

## 解除阻断所需的最小前提

不是新增状态机或全量Writer重构，也不是Engine/Report改造。需要单独明确授权最小“单Session单Workflow身份登记与传播”：真实创建时原子登记来源消息、唯一Business Workflow、预留Root ID与创建幂等键；准备调度显式携带该持久绑定，Trace失败仍不改变Session业务权威。不开放第二个Workflow，不推断/回填历史。

当前任务明确要求缺归属时停止，且前序Expand禁止自动把新表投入真实写入，故本轮没有擅自做这一步。达到该前提后可继续本任务的四节点适配与真实CSV验证；旧历史是否回填需另外决议。

本轮仅保存REQ与阻断证据，不自动进入下一阶段。
