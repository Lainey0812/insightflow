# InsightFlow Admin — Workflow Trace V0.1

## 任务目标

在现有 InsightFlow 中建立真实、可持久化、可追溯的 Workflow Trace 基础设施。

本轮优先实现后端数据契约与最小埋点，不开发复杂的监控 Dashboard。

## 具体要求

1. 首先审计现有 Workflow、数据库、任务状态、模型调用日志和报告失败记录，识别可以复用的 Run ID、执行记录与版本信息，避免重复建立两套事实来源。
2. 设计最小 Run、Span、Event、RunManifest 数据模型，明确 ID 关联、生命周期、状态机、异常与部分成功语义。
3. 优先在 Report Workflow 中接入真实埋点，覆盖 Evidence Builder、Insight Generator、Fact Validator 和 Report Assembler。随后设计可扩展到 Intent Parser、Planner、HITL 和 Engine 的统一接口。
4. 记录节点开始、完成、失败、耗时和错误代码。对 Insight Generator 保留 LLM 调用元信息、Prompt 版本、模型配置、候选数量、合法数量、拒绝数量及规则 ID。
5. 所有 Trace 必须持久化，服务重启后仍可查询。避免直接保存未脱敏的完整用户数据；必要的原始内容使用受控快照引用和权限隔离。
6. 实现只读 Admin API：
   - `GET /admin/runs`
   - `GET /admin/runs/{run_id}`
   - `GET /admin/runs/{run_id}/spans`
   - `GET /admin/spans/{span_id}/events`
7. 保证 Trace 写入异常不会使原本可成功的业务分析失败。对观测写入失败提供受控日志与降级策略，同时明确可能出现的追踪缺口。
8. 实现并发运行隔离、重试关联、异常结束处理及基本数据保留策略。
9. 添加自动化测试，验证成功、失败、partial、无证据跳过 LLM、并发、重试、重启后查询和权限边界。
10. 不改变 Planner、HITL、Engine 和 Report 的业务决策逻辑，不引入新的 Agent 节点。

## 本轮交付

- 现有追踪能力审计。
- 数据模型与生命周期说明。
- 修改文件清单。
- 真实 Report Workflow 的 Trace 示例。
- API 响应示例。
- 测试结果及尚未覆盖的节点。

先提交审计与数据契约，再实施代码。不要在不了解现有 Workflow 状态与日志结构的情况下直接新建一套平行追踪系统。
