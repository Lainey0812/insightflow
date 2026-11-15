# Lifecycle Contract V1.2 — C19 定向修订

日期：2026-10-31（Asia/Shanghai）；REQ-0081。基线：REQ-0079/VER-0001 的冻结V1.1。  
本版是用户明确确认的C19拆分方案，作为本次纯Policy实现依据；不是生产Writer、恢复程序或状态权威的上线。

## 1. 继承与变更范围

**[目标]** V1.2完整继承[V1.1契约](../lifecycle-contract-v1.1-2026-10-31/README.md)的所有非C19规则、业务枚举、状态矩阵、Legacy兼容、32行中其余31条命令。唯一命令变化：旧C19不再是有效V1.2命令，由C19-A、C19-B替代。共33个检查点，不是33个Agent或Trace节点。

**[目标]** [contract-tables.json](contract-tables.json)保存全部33行和继承矩阵。未改变的31行必须与冻结V1.1逐字一致。V1.1及其旧Policy语义继续保留，不能把旧C19在原适用域静默改为新规则。

**[现有]** Session仍为现行业务状态权威，现有ReportWorkflow/ReportRepository不接入本次新Policy。当前ReportRepository.finish在提交后返回True；已有Report/Generation同库事务，但原生Workflow归属/完整提交元数据Writer尚未启用。

## 2. C19-A：Report Commit Authorization

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 前态 | 当前generation=generating；业务control=COMPLETED；当前Execution必须有真实成功结果，允许partial_success |
| 目标 | 作用域 | 精确session/workflow、Dataset、PlanVersion、validation、Approval、Execution、execution_request_id、report_attempt |
| 目标 | Fencing | 当前revision、当前active key、提交命令幂等键/载荷必须匹配；旧Worker/旧attempt/旧执行拒绝 |
| 目标 | 报告资格 | report.complete或partial，合法Evidence引用与有效核心洞察；目标覆盖不能虚增；Engine.partial不能声称全目标完整成功 |
| 目标 | 授权结果 | allow只允许尝试一次业务事务，预期generation.generating→completed；不代表已提交，不得更新Span成功 |
| 目标 | 禁止前提 | 不要求accepted=True；不允许传一个自称成功的receipt绕过前置资格 |
| 目标 | 幂等 | 相同已完成请求仅返回原结果，不重新提交；键同载荷不同拒绝；实际预约和CAS仍由未来Writer负责 |

**[目标]** C19-A的报告验证使用可信业务/确定性Fact Validator投影，不让LLM自己宣布“校验通过”。没有任何有效证据或有效核心洞察，走原C20 unavailable规则，不伪装C19交付。

## 3. Business Transaction（非新增Policy命令）

**[目标]** 未来Writer在同一业务库事务内重新核对授权的Workflow/branch/revision/key/attempt，原子写入：

1. 不可变AnalysisReport。
2. ReportGeneration.completed与report_id、当前attempt。
3. Workflow归属链接，精确execution与accepted_report_attempt。
4. 提交元数据：授权的session/workflow/root、完整业务引用、report_id及内容摘要、提交请求ID/载荷hash、authorized_revision/active key、committed_revision；已采集时绑定唯一persistence_span_id，Trace缺失时允许为空。
5. 必要Workflow当前引用及revision；本次提交committed_revision=authorized_revision+1。

**[目标]** 提交元数据是可信业务audit的一部分，建议使用既有报告audit载荷；不是新Attempt表，不强制增加新表。本阶段只定义和验证内部证据投影，不修改数据库或业务Writer。

**[目标]** allow后发生CAS失败、链接失败或事务回滚时，不得产生可信accepted=True。Trace不参与该业务事务；业务成功但Trace失败仍是交付成功。

## 4. C19-B：Report Completion Observation

| 标记 | 项 | 契约 |
|---|---|---|
| 目标 | 前置事实 | 真实事务已提交；Report、Generation、归属链接、提交元数据在一致读快照中相互匹配 |
| 目标 | accepted来源 | 从可信提交记录核验产生，而非HTTP字段、LLM文字、Trace.complete或内存返回值本身 |
| 目标 | 精确目标 | 仅对应Workflow Root下直接report_persistence Span；唯一span_id、session/workflow/root、execution、attempt、report_id/digest、原提交请求与授权token均一致 |
| 目标 | 允许效果 | Span.running→complete；不修改Report/Generation、业务控制状态或Root，不新增Span/Attempt |
| 目标 | 幂等 | 同一提交证据下已complete的同一Span只读replay，不执行二次完成 |
| 目标 | 终态兼容 | failed/interrupted/partial/skipped等已终结Span不重开；保留采集缺口，业务提交事实仍成立 |
| 目标 | Root已complete | 可确认这个仍running的精确Span；不是Root.complete→running，也不重开Root |
| 目标 | key/revision | 核对提交时的authorized token和目标Span；提交后当前key可合法清空，不能错误要求等于提交前key；当前Workflow revision至少包含committed_revision |
| 目标 | 当前分支 | 本版保守要求仍为同一精确分支；已切新执行/attempt则拒绝对当前观测作更新，历史已提交报告仍保留可读 |
| 目标 | Trace缺失 | 不补造Span；拒绝当前观测并展示collection gap，不将真实业务交付改failed |

**[目标]** Span.complete只表示对应持久化步骤完成。report.partial的提交也可使该持久化Span完成，业务仍partially_succeeded；不把Span.complete当成整份报告/目标完整成功。

## 5. 提交成功但返回前崩溃

**[目标]** Recover必须先查询持久化事实。以下为只读reconciliation规则，不能因缺少accepted返回值直接标报告失败或再次生成：

| 标记 | 持久化查询结果 | accepted判断 | 合法后续 |
|---|---|---|---|
| 目标 | Report、completed Generation、归属链接、提交元数据全部一致 | True，即使调用方没有收到返回值 | 保留业务交付；只对合法running Span执行C19-B |
| 目标 | 事务已回滚，原generating仍在且无Report/链接/提交元数据；旧Writer已隔离，一致读已确认 | False/not_committed | 走原受控失败收敛/显式Retry；不能假装已提交 |
| 目标 | 只缺内存返回值，尚未查询 | None/unknown | 先查库，不派发新报告、不写failed |
| 目标 | 数据库不可读、读取不一致、Writer未隔离时缺记录 | None/unknown | 重读/隔离；不能推断回滚 |
| 目标 | Report存在但Generation/归属/元数据缺失或冲突 | None/inconsistent | 保留事实并调查，不伪造成功，也不删除Report当作重试准备 |
| 目标 | 持久成功，但Span已被重启恢复标interrupted | 业务accepted仍True | 不重开终态Span；collection incomplete，不重跑业务 |

**[现有]** 当前生产恢复函数没有启用上述原生Workflow提交证据协议。本轮使用纯领域reconciliation与临时SQLite协议测试证明规则，不宣称已部署真实恢复程序。

## 6. 适用域、兼容与本轮边界

**[目标]** 新Policy入口明确为native_v1.2；native_v1.1继续保持旧C19冲突拒绝，不因升级修改历史契约。legacy_session_v1继续委托旧路径。旧Report Run和嵌套Span原样保留；本次C19-B只处理目标两层结构的新直接Span。

**[目标]** C20仍处理unavailable；不开放unavailable Retry、Engine Resume、Root重开或已完成Workflow修订。Business Lifecycle/Activity/Execution Outcome枚举不变。

**[目标]** 本次不执行Backfill、Switch，不接入生产Policy，不改变ReportRepository、ReportWorkflow、Engine、HITL、Prompt或模型参数。仅修改独立Policy及测试；完成后停止。

## 7. 验收基线

**[目标]** 至少覆盖：C19-A合法complete/partial报告；跨Workflow/执行/attempt/revision/key拒绝；A未提交不能B；accepted自报无效；事务成功且回执丢失仍可从持久事实确认；回滚/缺失/错位/读失败不误成功；重复A/B；Span缺失/终态/错归属；Root.complete不重开；原31命令与V1.1回归不退化。

**[目标]** 提交元数据的persistence_span_id在实际Span存在时必须精确匹配，不能仅凭相同node_key关闭另一个Span。若Trace未采集则该字段为空，不阻止业务提交；C19-B不得凭空创建/猜测对应Span。

## 8. 设计验证与源码索引

**[现有]** [design-verification.json](design-verification.json)核对：其余31行逐字继承、继承状态表不变、33个检查点具备允许样例、A不要求accepted、B只操作Span、Root.complete无重开边、V1.1完整冻结内容未改。未运行或部署新的业务Writer。

**[现有]** [source-index.json](source-index.json)提供当前ReportRepository.finish/recover_interrupted、ReportWorkflow.generate及新增纯Policy/证据核验函数的真实路径与行号。

**[目标]** V1.2冻结标识见[freeze-manifest.json](freeze-manifest.json)；后续修订追加新版本，不覆盖V1.1或本目录。这里的冻结是本地哈希与需求归档，不冒充外部不可篡改存储。
