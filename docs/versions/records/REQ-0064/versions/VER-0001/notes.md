# REQ-0059 Lifecycle 状态机设计复核

依据本次用户只读评审要求，追加保存 REQ-0064，关联 REQ-0063/原 REQ-0059。旧设计不覆盖，本次为独立评审记录。

输出两份文档：REQ-0059-Lifecycle-状态流转表.md 与 Trace-数据契约评审报告.md。逐项核对 12 个真实节点的进入/正常退出/业务结果/异常/重试/恢复/Trace 位置；梳理 8 类记录及 6 类关键恢复路径；每项结论有实际代码路径与函数引用。

关键复核：共享 TraceRun 枚举 9 值已能通过语义映射覆盖目标 8 态，但 Workflow Root 仓储当前拒绝 complete/partial；Report 分支的终态不可重开必须保留；Admin RunStatus 缺两个等待态。最小方案优先只读 Lifecycle 视图，不要求新建业务状态机表或改共享枚举；后续 Root 推进按 kind 增量约束。Report attempt 可靠历史是条件性仓储扩展，不把它作为本轮已实现。

还明确：Planner timeout 不自动内部重试；Report partial 对应 completed generation，当前不可新 attempt；Fact 全拒/核心遗漏仍会失败；Report Persistence 的正常提交与 stale no-op 同为 None，需要最小提交回执避免误报；真实取消可先只有 Trace interrupted，业务待原启动恢复；真实结果存在与节点过程未采集须分开。

验证仅用源码阅读、AST、引用和哈希，不导入应用/不运行生命周期恢复。248 个源码文件前后哈希一致；181 处本地引用存在且行号有效；未修改源码/参数/Prompt/UI，未触发模型/业务执行/数据库迁移。未运行新业务测试或真实工作流验收，不用既有测试日志冒充本轮通过。

本轮新增仅为评审文档、校验材料与需求档案，完成后停止，等待评审，不进行埋点开发。
