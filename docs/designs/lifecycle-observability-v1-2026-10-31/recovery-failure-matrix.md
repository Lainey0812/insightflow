# Recovery & Failure Matrix

所有恢复规则标记为目标；现有行为单独说明。依据冻结Lifecycle V1.2，不修改任何已有恢复服务或Span枚举。

## 1. C19四个边界

C19-A许可、原子事务、持久事实核验、Trace写入是**同一report_persistence节点内的检查点**，不新增Span层或Agent。

| 标记 | 故障点 | 业务证据/判定 | Trace合法动作 | 禁止 |
|---|---|---|---|---|
| 目标 | 进入节点前/授权前崩溃 | 没有提交证据；未查库为unknown | 没有真实开始就无Span；已开始且确认停止可interrupted | 补造started/complete |
| 目标 | C19-A已allow，事务未开始 | allow不证明accepted；先查现存事实与作业状态 | 确认原作业停止后interrupted；保留授权Event，不发commit.accepted | 把Policy allow当交付 |
| 目标 | 事务写Report后/写Generation后、COMMIT前崩溃 | 一致读、旧Writer隔离且无提交记录可确认not_committed；否则unknown | 明确失败/中断；真实回滚记录可commit.rejected | 部分插入当成功；因无返回值猜回滚 |
| 目标 | COMMIT失败/归属链接约束失败 | 原子回滚，无新合法提交 | failed并区分技术/业务拒绝，不发Span.complete | 关闭FK、孤儿Report、跳过链接 |
| 目标 | COMMIT已成功但返回前崩溃 | 一致读取Report+Generation.completed+归属+提交元数据，匹配则accepted=True | 原Span仍running且C19-B通过才complete | 因丢回执写failed、重复生成报告 |
| 目标 | 已拿到accepted，B核验前崩溃 | 不能只用内存布尔；恢复查同样持久证据 | 同上，受精确Span约束 | 用当前active key覆盖提交时token |
| 目标 | B已allow，Trace写入前崩溃 | 业务已交付；B allow不是观测已完成 | 重读Span与提交证据；running可幂等再尝试B | 修改Root、伪造结束Event |
| 目标 | Trace事务执行中失败 | 业务保持已提交；Span/Event观察事务应一起回滚 | observation gap；同一running Span合法时再观察 | 回滚业务、把报告状态改failed |
| 目标 | Span完成，响应/确认Event返回丢失 | 业务事实完整，已存在同一合法终态 | 只读幂等，不第二次转换/新增执行 | 重开complete或改节点身份 |
| 目标 | 业务成功，Span已在启动恢复中被标interrupted | accepted仍True，Span终态不可改 | 保留历史interrupted与collection incomplete；记录恢复事实 | 篡改成complete、生成新假历史Span |
| 目标 | 提交成功但无物理Span/Root | 业务成功，persistence_span_id可空 | gap，不创建未执行过的Span | 用提交时间编造原开始时间 |
| 目标 | 证据缺失/跨Workflow/错attempt/hash | unknown/inconsistent，保留已见记录 | 拒绝B；受控诊断，不改当前分支 | 选最近成功结果消除冲突 |

**[现有]** ReportRepository.finish已在同库事务保存Report/Generation后才返回True；旧attempt返回False，ReportWorkflow对False以REPORT_STALE_CALLBACK处理。现有生产并没有原生Workflow提交元数据Writer或C19-B实际接入。

**[现有]** V1.2独立Policy及先前临时SQLite测试已覆盖提交后无回执和调用内存丢失的协议；本次C1只审计这些测试/源码，不重跑业务或声称部署了恢复程序。

## 2. 全节点故障/恢复

| 标记 | 场景 | 业务处理/证据 | 观察契约 |
|---|---|---|---|
| 目标 | Intent clarify | 保存意图与问题，暂停Planner | Intent.complete，clarification.required；无Planner Span |
| 目标 | F0/blocked计划 | 保存完整F0与未满足核心要求，拒绝非法批准 | Planner/Validator.complete + business_outcome=blocked；无Engine Span |
| 目标 | 准备节点技术失败 | 保存错误及合法检查点 | 原Span.failed；显式Retry真实重入新span/node_attempt |
| 目标 | HITL业务拒绝 | 真实资格判断得到拒绝，无Approval写入 | 节点确有执行则complete/outcome=denied；入口无可信归属不造Span |
| 目标 | Engine一任务失败 | 其余独立任务可继续，保存真实ExecutionResult.partial_success | Engine.partial；任务失败Event/日志，不建任务子Span |
| 目标 | Engine全部任务失败 | 无成功结果，保存错误 | Engine.failed，failure_kind按实际业务数据/技术错误；不把HTTP状态码当分类唯一依据 |
| 目标 | Engine进程中断 | Recover保留progress，未完成skipped；不Resume task/step | 原执行被确认中断的Span.interrupted；业务可以partial_success；不涂改已有终态 |
| 目标 | Engine结束但Report未queued | 已有真实结果，report_not_started | 不补造Reporting Span；可记录已确认的执行完成事实 |
| 目标 | 无有效Evidence | Evidence.complete/count=0；报告可unavailable | 实际进入NO_EVIDENCE的Insight/Fact才skipped；没有Call |
| 目标 | 部分合法候选、部分拒绝 | 保留合法候选和限制，core覆盖仍须合法 | Fact.partial；accepted+rejected=candidates；不宣称已全部生成 |
| 目标 | 全候选拒绝或核心方向无合法洞察 | 当前materialize_candidates抛明确错误，报告生成失败 | Fact.failed/business_safety，之后Assembler未执行就无Span；不能造partial成功 |
| 目标 | Chart fallback table | 真正规则返回可用配置 | Chart.complete，不标failed；前端切换不重跑后端 |
| 目标 | 旧revision/active key/Report attempt | 旧业务回调拒绝，不修改有效分支 | Root级callback.rejected引用旧作业；不把当前Span写failed/complete |
| 目标 | 重复执行请求 | 同键同载荷返回原结果/进行中，不重算 | 不创建新Engine Span，不递增node_attempt |
| 目标 | 内部LLM重试 | 同节点执行与operation，新增真实Call记录 | 不创建第三层Span；Call失败不被后续成功覆盖 |
| 目标 | Trace DB不可用/锁/配额 | 不影响正常业务 | 受控日志/gap；无持久Event不声明已采集 |
| 目标 | Registry.begin失败 | 必需请求快照无法保存，HTTP不发 | 节点failed/technical，Call可能不存在，不能造HTTP成功 |
| 目标 | Registry.finish失败 | 实际调用可能发生，但结果不交业务 | LLM_CAPTURE_FINALIZE_FAILED；已发生调用不假装未发，Call可能待恢复interrupted |
| 目标 | 并发两个Workflow | owner/branch/key隔离 | Root及node_attempt/Event sequence各自隔离，不用Session最新 |
| 目标 | 旧Report Run | 仍按execution+attempt和旧manifest解释 | 不改为新Root节点，不改历史嵌套 |
| 目标 | 超过事件/快照预算 | 原业务结果仍真实 | 记录已知drop/截断或unknown，不以零错误事件保证成功 |

## 3. C20未决路径

**[现有]** 旧生产ReportRepository.finish可提交unavailable报告，旧Persistence Span正常退出时complete。**[目标]** 新native V1.2 C19-A/B只授权可交付complete/partial报告，不能直接拿C19-B核验C20的Generation.unavailable。C1不改V1.2，也不虚构已实现的C20-B。

**[目标]** 在C20原生持久化观测终结规则经架构决议前，C2不得激活这一新native路径；保持旧scope兼容，真实业务unavailable不被改成failed/success，未能证明的采集结果明确gap。这个缺口阻断“全路径埋点已完成”的验收，而不是阻断已有业务。

## 4. 启动恢复顺序与时间

**[现有]** main.lifespan依次恢复Engine、Workflow、Report、Trace、Registry，均基于单进程边界。Trace.recover只扫描queued/running Run并将其中running Span标interrupted；waiting Root下遗留running Span未独立扫描。这不是全Workflow/多Worker恢复。

**[目标]** C2先确认旧Worker失主/隔离，读取已提交业务事实并处理C19；可观察的仍running持久化Span经B确认后再对剩余真实失去执行者的Span标中断。已终结Span不重开；不依据Trace批量中断结果反写业务失败。生产改变恢复顺序须另行批准、测试，不由本稿执行。

**[目标]** 正常duration_ms使用同次实际单调时钟测量。跨进程恢复无可靠原始测量时为null，不把停机/等用户时间算计算耗时。finished_at可记录实际观察终结时点并标reconciled，业务完成时间另引用可信原记录；缺失开始/结束不补猜时间。
