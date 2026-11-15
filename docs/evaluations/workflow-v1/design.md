# Workflow V1 集成前审查与实施方案

复用已有Orchestrator、SessionRepository、PlanReviewRepository及ExecutionRepository。保留旧API/历史Mock的隔离兼容，新前端入口显式使用real_workflow=true。新主流程不调用Mock Planner/Engine/Report，不调用新的Insight Generator。

## 状态映射（扩展同一SessionStatus枚举）

profiling→PROFILING，parsing_intent→PARSING_INTENT，planning→PLANNING，validating→VALIDATING；clarification_required→已有WAITING_FOR_CLARIFICATION；awaiting_approval→已有AWAITING_APPROVAL；executing→已有RUNNING；completed/failed→已有COMPLETED/FAILED。保留CREATED/APPROVED和旧PREPARING。没有第二个业务状态机。

同一Session JSON增加workflow_kind、profile_options、planner_result和状态事件，旧记录默认兼容。关键阶段通过现有SQLite事务写入，生成计划与校验结果用已有不可变PlanVersion审计表原子保存。审批和执行仍用原服务及接口，不改其规则。

## 兼容差异与边界

1. 现有人工计划导入要求intent.business_goal逐字等于user_goal，不适用于LLM规范化目标。因此Workflow新增仅服务端调用的生成计划保存适配，复用PlanReviewService.validate_v1和audit.append_version，原user_goal、IntentArtifact和Planner结果完整保留，不改人工导入或审批规则。
2. HITL无条件拦截非空Intent constraints，且defer不能勾选解决。当前契约没有约束验证证明/解除工具；本轮严格保留并明确显示。因此明确指标/筛选/时间等可能生成F2计划却仍不能批准。不能清空约束、伪造确认或修改意图绕过。浏览器真实执行使用满足既有规则的探索式需求，受限案例验证阻断并单列，不宣称这些请求已能执行。
3. POST创建先返回会话ID及访问凭证，再以进程内BackgroundTasks运行；前端存储后轮询GET恢复。进程中断不自动重跑LLM或计算，保存失败与检查点；提供受版本检查的显式准备阶段重试。已有Engine执行恢复机制原样复用。
4. Planner内部已调用一次Validator；Workflow在VALIDATING时再通过原HITL验证器确定性重检并保存审批可重现结果，绝不增加LLM可行性修复循环。

## 文件计划与实施顺序

- domain/enums.py、models.py、workflow/transitions.py：扩展现有状态、检查点及同枚举审计事件。
- workflow/orchestrator.py：真实分支、画像→意图→澄清→规划→校验→持久化、Mock来源拒绝、错误/中断与重试；保留旧演示分支。
- main.py、api/routes.py：依赖注入、异步主入口、澄清和准备重试接线；原审批、执行接口复用。
- storage/session_repository.py、plan_review_repository.py、execution_repository.py：仅追加真实Workflow状态事件，事务/批准/执行规则不变。
- frontend/api、App、contracts及必要组件：主入口真实生成，状态轮询/刷新/澄清/任务审阅/删除/原审批执行/结果查询，移除新流程人工JSON导入。
- tests及docs：16类验收矩阵、原回归、真实模型浏览器CSV验收、独立Pandas核对和重启恢复记录。

不改Engine、Validator、HITL服务、Intent/Planner Prompt或Report业务实现。先完成受控接口/浏览器组件测试，再启动真实模型及CSV浏览器验收；不得把受控Provider测试记成真实LLM调用。
