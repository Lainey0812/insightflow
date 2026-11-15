# Phase 03-C2 实施建议与准入

REQ-0082。以下全部是待评审建议，不是自动继续执行的授权。

## 1. 推荐分阶段

1. **基础记录器安全**：受控字段、平铺Span、稳定node_key、数据库内node_attempt、Span终态CAS及Event同事务、事件预算和fail-open。先在临时数据库/合成可信Workflow快照验收，不接业务权威。
2. **身份适配准备**：明确新native Workflow/root预留来源、运行上下文和路由；复用Expand结构，不用Session冒充Workflow，不新增平行Run或Attempt。
3. **真实节点适配**：准备、各角色Validator、HITL、Engine、Reporting，按本契约真实入口包围范围，保留旧scope。生产激活须有对应可信业务引用/Writer能力，不仅是添加装饰器。
4. **C19优先接入**：A、原子事务、持久一致读、B、Trace原子终结，实际故障注入覆盖丢回执/丢内存/写Trace失败。不能只测试正常调用的accepted=True。
5. **兼容查询与验收**：稳定节点对齐、旧Report Run/嵌套Span原样、无权访问拒绝、刷新/重启/并发/partial等真实运行验证。不得用静态设计用例当真实Trace。

## 2. 生产整链路准入门槛

| 门槛 | 必须可评审的证据 | 当前结论 |
|---|---|---|
| A01 架构接受本契约 | 12节点、32事件、身份/失败语义及验收矩阵确认 | 等待本轮评审 |
| A02 可信Workflow身份 | Business Workflow原生Writer/关联或已批准的明确路由；唯一Root预留而非Session推断 | 未具备生产接入；Expand结构不等于完成 |
| A03 全Root语义兼容 | 与Lifecycle V1.2一致的kind/capture_scope守卫方案；旧Root和Report Run不可变 | 当前只支持准备Root，需另行批准 |
| A04 C20观测协议 | 不修改本轮V1.2的前提下取得后续明确决议，说明unavailable提交如何合法终结观察 | 未决，阻断全路径新native验收 |
| A05 事务/防旧回调 | 可信业务fencing、Span CAS、原子终态Event、业务提交与观察隔离测试 | 局部已有，未全链路 |
| A06 C19持久恢复 | 提交元数据Writer、一致读Reader、精确span_id绑定、失主隔离与崩溃用例 | 仅独立Policy/协议测试存在 |
| A07 事件和快照兼容 | SAFE_KEYS/字段契约、计数/幂等、预算、Root多attempt快照策略与旧数据读取 | 需实施评审 |
| A08 故障及隐私 | Trace fail-open与Registry fail-closed分别验证，原文权限/过期/日志脱敏 | 部分已有，需整链路验证 |

**[目标]** A02/A03/A04/A06未满足时，C2只能先交付基础适配/测试，不宣称已生产开放全Workflow埋点。不得为了完成埋点而顺带Backfill、Switch、删旧索引或修改业务状态权威。

## 3. 预计涉及的文件（非本轮修改清单）

- `observability/recorder.py`、`context.py`、`workflow.py`：稳定身份、显式结束语义、脱敏和上下文。
- `storage/trace_repository.py`：Span原子终结/事件计数与幂等；如需约束变化，单独提供兼容迁移。
- `domain/tracing.py`及安全字段定义：只做经批准的最小兼容扩展，不增加Span状态或Trace层级。
- `workflow/orchestrator.py`、`workflow/reporting.py`、相关真实服务：只在批准的真实边界接入，不改变计算/规划/批准决策。
- 可信Workflow Writer/只读提交核验适配：单独任务定义；本契约不把这些必需能力当作已存在。
- 自动化及实际前台链路验证：按acceptance-matrix覆盖，输出真正的持久Run/Span/Event/Call，而非生成演示数据。

## 4. 停止点

本轮仅文档与静态检查，完成后等待架构评审。不自动进入C2，不新建任何Run/Span，不切Workflow身份或状态权威。
