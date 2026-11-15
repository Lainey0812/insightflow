# InsightFlow Phase 02-A：Expand Only 实施任务

## 目标

基于已完成的 Business Workflow 数据契约设计与迁移方案，实施第一阶段 Expand。

参考文档：

- `docs/designs/business-workflow-phase02-2026-10-30/README.md`
- `docs/designs/business-workflow-phase02-2026-10-30/migration.md`

本阶段目标是为 Session 1 Business Workflow 建立数据基础，**但暂不开放多 Workflow，也不切换现有业务状态权威**。

## 一、实施前补充设计约束

先审查并补充以下五项设计，发现冲突时先报告，不得自行改变核心架构：

1. Workflow 创建、root_run_id 预留和创建幂等键必须在同一业务事务内提交。
2. 新业务事实与 Workflow 归属链接必须原子提交，不能产生无归属的新审批、执行或报告。
3. 明确迁移 Switch 的活跃任务检测、旧 Worker 隔离和 fencing 前置条件。
4. 明确 Session 消息、origin_message_id、workflow_id 和 parent_workflow_id 的归属语义。
5. 明确 ReportGeneration 当前状态、历史 Report Run 和已提交 Report 的区别，不伪造历史 Attempt。

将补充内容记录在设计文档中。

## 二、Expand 实施范围

允许：

- 新增 Business Workflow 相关数据库表、约束、索引和迁移版本记录。
- 新增统一 WorkflowPlanVersion 版本仓结构。
- 新增必要的 Approval、Execution、Report 归属链接结构。
- 新增 Session 消息、数据集关联及迁移路由结构。
- 实现幂等的 Expand Schema 迁移。
- 实现只读 Repository / Resolver。
- 编写数据库约束测试、迁移测试和兼容性测试。

禁止：

- 创建第二个业务 Workflow。
- 修改现有 Session 当前分析状态的权威来源。
- 将新表投入真实审批、执行或报告写入路径。
- 修改现有 Planner、Engine、Reporting 的执行逻辑。
- 删除旧 Root 唯一索引。
- 修改旧 PlanVersion 主键。
- 修改历史不可变业务载荷。
- 开始 Backfill、Switch 或 Contract。
- 新增 Trace 第三层或 Attempt 实体。

## 三、数据库迁移要求

1. 保留所有旧表、主键、唯一约束及不可变触发器。
2. 所有新 Schema 迁移必须可重复执行，并能检测部分迁移及 Schema 不匹配。
3. 外键约束必须在 SQLite 实际启用的条件下验证。
4. 新表应具备明确的同 Session / 同 Workflow 归属约束。
5. 不允许以关闭外键或删除历史数据的方式通过迁移。
6. 对三个 SQLite 数据库分别处理迁移版本和失败恢复。
7. 迁移前确认备份及 WAL 一致性策略，不直接复制运行中的数据库文件作为一致性备份。

## 四、测试要求

至少验证：

- 旧数据库执行 Expand 后，原有业务记录和不可变载荷不变。
- 重复执行 Expand 不产生重复表、索引或迁移版本。
- Workflow ID、Root ID、创建幂等约束有效。
- 同 Workflow / Session 的组合外键有效。
- WorkflowPlanVersion 支持不同 Workflow 各自拥有版本 1 的数据约束。
- 旧 PlanVersion 仍可按原键读取。
- 归属链接拒绝跨 Workflow 的错误引用。
- 旧 Session 单流程 API 行为不变。
- Trace Root CAS 与 Report stale callback 保护不退化。
- 现有后端、前端和 Admin 回归测试通过。

测试可以使用独立临时数据库构造两个 Workflow 的约束场景，但生产业务入口仍不得开放第二个 Workflow。

## 五、交付报告

完成后输出：

1. 实际修改的文件及原因。
2. 新增表、字段、索引、外键和触发器清单。
3. 数据库迁移执行与幂等验证结果。
4. 新增测试及完整回归结果。
5. 原有业务数据和 Schema 兼容性检查结果。
6. 尚未解决的风险。
7. 是否满足进入 Phase 02-B Backfill 的条件。

不得将“Schema 已存在”解释为“Session 1 已可使用”。

**完成 Expand 后停止，不自动开始 Backfill。**
