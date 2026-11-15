# 验收矩阵（设计基线，未执行运行验收）

REQ-0082。这里是C2必须转化为自动化/真实链路测试的Given/Then，不是伪造Run或本次业务测试结果。

## 全节点状态矩阵

12个节点分别覆盖6×6状态组合，另有真实开始/未调用规则；节点不支持的partial/skipped明确拒绝。running同态仅表示合法属性更新，不生成第二个Span或完成事件。

| 节点 | start/未调用 | 状态组合 | 终态重开 |
|---|---|---|---|
| data_profiler | 2 | 36 | 全部拒绝 |
| intent_parser | 2 | 36 | 全部拒绝 |
| analysis_planner | 2 | 36 | 全部拒绝 |
| plan_validator | 2 | 36 | 全部拒绝 |
| hitl | 2 | 36 | 全部拒绝 |
| analysis_engine | 2 | 36 | 全部拒绝 |
| evidence_builder | 2 | 36 | 全部拒绝 |
| chart_builder | 2 | 36 | 全部拒绝 |
| insight_generator | 2 | 36 | 全部拒绝 |
| fact_validator | 2 | 36 | 全部拒绝 |
| report_assembler | 2 | 36 | 全部拒绝 |
| report_persistence | 2 | 36 | 全部拒绝 |

详细每项在[contract.json](contract.json)的acceptance_cases中；上述是设计判定，必须同时验证真实证据、作用域和token，不能只用status字符串判断。

## 跨节点/故障场景

| ID | Given | Then |
|---|---|---|
| scope.two_workflows | 同Session两个真实Workflow并发，同node_key | Root/span/Call/sequence/attempt按Workflow隔离，不选Session最新 |
| retry.reenter | 同Workflow一次失败后显式真实重入 | 同Root新span_id/node_attempt；旧Span保留 |
| retry.http | 单节点内两个真实HTTP尝试 | 一个节点Span，两个CallRecord，sequence/retry_index独立 |
| retry.replay | 同幂等键同载荷且原结果已完成 | 返回已有结果；无新Node Span，无业务重复执行 |
| retry.conflict | 同幂等键不同载荷 | 明确拒绝，不重算、不把旧审批给新版本 |
| fencing.revision | 旧revision回调，当前作业已更新 | 拒绝旧业务/当前Span写入，callback.rejected指旧操作 |
| fencing.key | 同revision但active key不同的旧Worker | 拒绝；不能读取新key后重放旧结果 |
| fencing.attempt | 报告旧attempt在新attempt后返回 | 不提交旧报告，不标Persistence complete，不改当前Root |
| cas.root | 同business_revision两个旧Root对象写入 | observation_revision只允许一个CAS；旧对象不能覆盖 |
| cas.span | 两个进程读到running后并发终结 | 一次终态与Event原子提交；不能后来的旧running覆盖 |
| root.terminal | 已complete Root收到新节点开始或重开命令 | 不创建新执行；仅V1.2精确B确认原有running Span例外，不改Root |
| flat.node | 新Node Span带parent_span_id | 拒绝新结构；历史嵌套仍可读 |
| validation.blocked | Validator返回P0/F0且coverage=blocked | Validator.complete/outcome=blocked；禁止批准/Engine，保留缺口 |
| engine.partial | 一成功一失败任务且结果保存 | Engine.partial，业务部分成功；失败任务Event/日志不丢 |
| engine.empty | 合法计算返回空表且有结果引用 | 计算成功不伪装failed；Evidence可为空 |
| engine.recover | 中断前有已保存任务，另有未完成 | 保留结果，剩余skipped，不Resume；原失主Span可interrupted，业务可partial_success |
| intent.clarify | Intent合法clarify | Intent.complete，业务waiting_input；不启动Planner |
| insight.no_evidence | 明确进入NO_EVIDENCE分支 | Insight与Fact处理器真实skipped，CallRecord数量0 |
| fact.partial | 部分候选合法、部分拒绝且核心覆盖允许 | Fact.partial，报告partial，规则和拒绝数保留 |
| fact.core_missing | 有accepted候选但核心方向无合法洞察 | Fact.failed，Report生成失败，不伪造Assembler Span |
| chart.fallback | 真实ChartBuilder返回table替代不适用图表 | Chart.complete，fallback不是节点失败 |
| trace.down | Trace DB从开始不可用 | 业务继续；日志gap；不造Root/Span/Event来满足FK |
| trace.end_event_atomic | 终态Event写后状态更新发生冲突 | 目标同Trace事务回滚观察；读端不宣称已完成 |
| registry.begin | 模板/请求日志登记失败 | HTTP不发，明确失败；不得套用Trace fail-open |
| registry.finish | HTTP返回但必需请求日志终结失败 | 结果不交业务；Call记录按真实状态或待恢复保留 |
| registry.protocol_success | Provider succeeded但Intent/Insight JSON非法 | Call成功保留，节点failed；不伪装语义成功 |
| legacy.report_run | 历史独立Report Run和嵌套Span | 保留ID/kind/manifest/父子关系，不改成native Root子层 |
| event.sequence | 同Root多个Context并发写Event | 库内sequence唯一，按入库顺序；不当作因果/业务总序 |
| event.budget | 达到256事件/8KiB或白名单截断 | 受控gap与drop/unknown；业务不失败，数据缺失不算零失败 |
| snapshot.retry | 同Root报告第二次生成同kind快照 | 不覆盖旧快照；未决策略显式gap，C2先审兼容方案 |
| c19.before_a | 未实际进入持久化节点便崩溃 | 没有Persistence Span；不造授权或完成 |
| c19.a_only | A已allow但未尝试/未提交事务 | 无accepted；不得Span.complete，先查实际事实 |
| c19.mid_tx | 写Report或Generation后COMMIT前进程退出 | 隔离旧Writer后一致读回滚事实；不伪造提交 |
| c19.after_commit | 事务成功但返回accepted前进程退出 | 从Report/Generation/归属/元数据核验accepted=True，不能因无回执判失败 |
| c19.memory_lost | 所有调用内存丢失，只有execution_id可查 | 在一致读中从generation/report.audit重建提交身份，不靠当前配置/时间猜 |
| c19.before_trace | B已allow但Span/Event写入前崩溃 | 业务已交付；重读同Span，仅合法running可B确认 |
| c19.trace_write_failed | Report已提交而Trace事务失败 | 业务不回滚；观察事务失败gap；不重跑报告 |
| c19.no_span | 持久提交完整但物理Span未采集 | 业务accepted，collection缺口；不造历史Span |
| c19.terminal_span | 业务已提交但Span已interrupted | 保留业务事实与Span终态，不能改complete |
| c19.complete_root | Root已complete但对应Persistence Span仍running | 按精确B证据只确认该Span，不重开Root |
| c19.wrong_span | 同node_key但不是提交元数据绑定的span_id | 拒绝B，不结束其他Span |
| c19.bad_facts | 缺Report/Generation/链接/audit或hash/attempt冲突 | unknown/inconsistent，不猜成功或删数据重试 |
| c20.unavailable | C20提交unavailable后尝试套C19-B | 按V1.2拒绝；新native观测协议未决，不修改原业务结果 |
| recovery.waiting_root | waiting Root内遗留running Span | 不能因现有扫描未找到就判成功；C2失主核验后按合法规则收敛 |
| privacy.trace | 用户数据含密钥/指令/长原文 | Trace只存受控引用/hash/计数，原文不进Event，脱敏错误不影响业务 |

另外逐一检查32个事件的最小字段、版本化白名单和落库/日志降级。设计总计533条：12×(2+36)个节点规则、32个事件Schema规则、45个关键跨节点场景；没有运行真实模型或业务数据库。
