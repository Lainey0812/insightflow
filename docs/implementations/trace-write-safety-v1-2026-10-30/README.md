# Trace 写入与旧回调安全修复 V1

需求：REQ-0075；架构约束：REQ-0073；审查依据：REQ-0072、REQ-0074。日期：2026-10-30。

## 本轮结果

修复 Root 非原子 revision 比较、同业务 revision 旧对象覆盖，以及未提交的旧报告仍被标记 Trace complete 三类问题。保持 Workflow Root + Node Span 两层；不新增第三层节点、Attempt 实体、Root 表或其他数据库表；不改变 Session 与 Workflow 的现有一对一关系，不扩展 Root complete/partial，不改变 Report 独立 Run 的历史兼容边界。

## 修改文件与机制

### 1. domain/tracing.py：观测版本号

TraceRun 增加 observation_revision，整数、默认 0。它是该 Trace 行的乐观并发令牌，与 Session.business_revision、Node Span.node_attempt、Report attempt 及 LLM 调用序号分别使用，不表达新的业务执行实体。

旧 JSON 记录缺少此字段时按 0 读取，无须批量改写历史行；新写入将该字段保存在现有 record JSON 中，没有表迁移。公开 Trace API 增加此元数据字段，Admin 当前解析器兼容。

### 2. storage/trace_repository.py：原子 CAS 和类型各自的迁移边界

update_run 返回 bool：True 表示事务已成功提交，False 表示陈旧或不允许的更新未接受。读、校验、写入全部置于 BEGIN IMMEDIATE 事务中；同时比较 observation_revision 和业务 revision。SQL 写入成功并提交后才推进调用对象中的 observation_revision。

同一旧版本的并发对象只有一个能够提交；较低或空业务 revision 不能覆盖已知新版本；CAS 冲突不会自动用新令牌重放旧内容。调用方应按真实业务操作重新读取和判断，不能自动刷新令牌后重试旧回调。

Root 使用准备阶段迁移矩阵：queued 可进入 running/interrupted；running 可进入 running、等待补充、等待审批、failed、interrupted；等待补充、failed、interrupted 只能用更高业务 revision 恢复 running；waiting_approval 不允许旧准备回调改成失败。Root 仍不支持 complete/partial，未擅自扩大生命周期。

Report Run 沿用 queued/running/终态规则，终态不重开；Root 的合法恢复规则不会应用到 Report。Manifest、Run 身份及 historical Span 的不可变检查保留。

recover 同样使用写事务，并递增 observation_revision，使恢复前持有的对象失效；原单进程恢复范围不变。

### 3. observability/workflow.py：只有接受的状态变化才记成功迁移事件

start_preparation、checkpoint、interrupt 先尝试仓储提交。提交成功才记 workflow.started/resumed/failed/interrupted 等对应事件；被拒绝的回调记 workflow.callback_ignored，包含受控错误码或业务 revision，不伪装成已接受状态。

重复开始不能接管已 running 的观测；被明确拒绝的开始取消该上下文的 Root 关联。Trace 写异常仍经过已有 fail-open 边界，不阻断原本合法的分析；缺失观测保留为缺口，不伪造节点成功。

### 4. workflow/orchestrator.py：迟到业务结果与错误都受到现有 Session revision 保护

仅给真实准备流程的异步回调增加乐观并发检查。每次持久化成功后，局部 guard 更新为已提交的 Session revision；NodeRun、画像、Intent、Planner 结果、计划保存及失败状态必须匹配该 revision。它是当前函数调度中的局部数值，不是新表、实体或 Trace 层。

旧 Planner 返回成功或错误时，如果 Session 已恢复并向前推进，STALE_SESSION 只产生忽略事件，不修改当前 Session、批准或执行。原取消仍传播；如果 Session 已换分支，旧取消不再把 Root 标为中断。Node Span 与调用日志继续保存原历史，终态 Span 不被旧回调覆盖。

合法重试入口、资格、原检查点和 Session/Root ID 均保留，未改变业务分析算法或自动触发审批。

### 5. storage/report_repository.py：明确业务提交接受结果

finish 在事务提交后返回 True；缺少记录、attempt 不匹配或状态已结束时返回 False，且不写报告或 Session。异常仍抛出，不伪造提交成功。报告及生成状态继续在原业务数据库事务中保存。

### 6. workflow/reporting.py：Trace 成功取决于实际接受的报告提交

report_persistence Span 内检查 finish 的返回值。旧报告未接受时抛出 REPORT_STALE_CALLBACK，使该持久化 Span 不被标记成功；不保存旧报告投影，不携带旧 report_id 结束成功 Trace。

迟到成功或失败统一记 report.callback_ignored；尚在运行的旧 Report Run 结束为 interrupted。若旧 Run 已有 failed/interrupted 等终态，仓储保护原终态。当前新 attempt 不被旧错误回写。只有报告真实保存成功，才允许对应 Trace 以报告 complete/partial/unavailable 状态结束。

### 7. 测试

新增 backend/tests/test_trace_write_safety.py，11 个展开场景：

- 两个同步开始的并发 Root 回调只有一个 CAS 胜者；失败者不能再覆盖。
- 新业务 revision 不被旧 revision 或空 revision 覆盖。
- 同 revision 的旧 checkpoint 和 interrupt 只记录忽略事件。
- 失败后合法高 revision 重试复用 Root，保留旧失败 Span；同 revision 不能冒充重试。
- 历史 JSON 默认版本读取、不新增表、Manifest 保持、Report partial 终态不重开。
- 旧 Planner 成功/错误两种情况，在恢复的新流程完成后均不改变 Session 或 Root。
- 部分恢复/完整恢复，分别组合旧 Report 成功/错误四种情况；拒绝旧提交、保留旧 Run，新 attempt 仍能正常生成并保存报告。

调整 backend/tests/test_workflow_trace_v031.py 的重启夹具：模拟已接受重试时带上真实增加后的 business_revision，避免用同 revision 旧对象伪造合法恢复。首轮失败记录 regression-first.txt 保留，不放宽生产规则来迁就旧夹具。

## 复现前后对照

旧冻结审计中的部分恢复调度曾得到：旧报告未保存、当前 attempt=2/queued，旧 Trace 却 complete。用同一保留脚本在修复代码重新运行，report-stale-fixed.json 显示：

| 检查项 | 修复前 | 修复后 |
|---|---|---|
| Engine 结果 | success | success |
| Session 状态 | COMPLETED | COMPLETED |
| 当前报告 | attempt 2 / queued | attempt 2 / queued |
| 旧报告是否落库 | false | false |
| 旧 Trace | complete，带不存在的 report_id | interrupted，report_id=null |
| 新旧 Report Run 的 Root 关联 | 相同 | 相同 |

完整恢复的负对照仍为旧 Trace interrupted。自动化测试还继续执行新 attempt，验证其 complete 对应已保存的 report_id；不是通过让所有报告失败来规避错误成功。

这些是实际运行代码、真实临时 SQLite、原 Validator/Engine 和受控本地模型 Provider 的集成验证，不是生产运行记录或真实外部 LLM 质量评测。本轮没有发送外部模型请求。

## 回归与运行核验

- 最终后端：848 passed，1 个现有 Starlette TestClient 弃用 warning，backend-release.txt。
- 前端：67 passed，9 文件，frontend-tests.txt；TypeScript/Vite 构建通过，frontend-build.txt。
- Admin：78 passed，10 文件，admin-tests.txt；类型检查与构建通过，admin-build.txt。
- 原 Lifecycle Read Model、Planner、HITL、Engine、Report 测试包含在完整后端回归内，业务判断未被放宽。
- 启动最终本地后端进程 24023；健康检查 real/ok；Admin Runs 返回 observation_revision，原有历史记录可读取。
- 三个 LLM 节点的 runtime_registration 均为 registered，使用既有不可变 Prompt 快照，见 runtime-prompt-check.json。未更改 Prompt 内容、模型或参数，也未覆盖旧快照。
- 一次中间诊断错误文案调整触发 Report 模板源指纹登记冲突；已撤回该无关文案改动、完整重启并验证原快照登记正常。没有放宽 Prompt 一致性检查，也没有发起模型调用。最终 observability/recorder.py 与基线一致。
- 在无活跃 Session/Report 的情况下加载服务。runtime-before.json 与 runtime-after.json 核对十张业务/Trace 表的行数及内容哈希，既有记录未改变；未回填、删除或重写历史。

## 兼容边界与剩余限制

1. 新代码可读取旧记录；新增 JSON 字段不是对旧二进制的回滚兼容承诺。旧 TraceRun 的 extra=forbid 可能拒绝已写入 observation_revision 的记录。如需降级，应先设计保留元数据的兼容读取方案，不能删除历史字段来掩盖版本变化。本轮未实施降级迁移。
2. 仍是单进程本地部署语义，没有新增跨进程租约、任务队列或自动接管。原子 CAS 解决写入竞争，不等于已经支持多 worker 的全局恢复调度。
3. Trace 仍可能缺失或降级，业务提交成功但观测写失败时不伪造成功 Trace；Lifecycle 继续独立核对业务结果和采集完整性。
4. 不扩展 Root complete/partial，不改变 Session 唯一 Root、计划版本命名空间、审批规则、执行算法或报告内容质量。

## 归档

source-before/after.json 与 ZIP、source-diff.json、final.diff 保存最终变化及源码。没有删除源文件；frontend/src、admin/src 与基线一致。review.diff 是中间检查记录，最终变更以 final.diff 和 source-after.zip 为准。失败日志与中间/最终回归均保留，不覆盖旧审计或旧需求。
