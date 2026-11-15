# Lifecycle Observability Contract V1.0

项目：InsightFlow；阶段：Phase 03-C1；日期：2026-10-31（Asia/Shanghai）。  
需求：REQ-0082；业务基线：冻结Lifecycle Contract V1.2（REQ-0081/VER-0001）。  
性质：**只读源码审计与目标埋点设计，等待架构评审；不是已上线埋点、生产Trace示例或状态权威切换。**

## 1. 交付导航

| 交付物 | 文件 |
|---|---|
| Lifecycle Observability Contract V1.0 | 本文件及结构化[contract.json](contract.json) |
| Node Instrumentation Matrix | [12节点矩阵与逐节点证据](node-instrumentation-matrix.md) |
| Event Dictionary | [32个稳定事件、类型与最小字段](event-dictionary.md) |
| Trace Identity & Correlation Contract | [身份、分支、revision、Call与Legacy](trace-identity-correlation.md) |
| Recovery & Failure Matrix | [恢复、崩溃与C19四边界](recovery-failure-matrix.md) |
| Implementation Gap Report | [当前覆盖与19项缺口](implementation-gap-report.md) |
| Phase 03-C2建议与准入 | [实施顺序与阻断门槛](phase03-c2-admission.md) |
| 验收矩阵 | [533条设计用例概要](acceptance-matrix.md)与contract.json逐例Given/Then |
| 真实源码依据 | [73个函数/类的路径行号](source-index.md)、[完整摘录](source-evidence.md) |
| 静态检查 | [check_contract.py](check_contract.py)与[verification-release.json](verification-release.json) |

本契约使用“现有”表示源码可证事实，“结构已具备”表示空Schema/只读基础，“目标”表示待实施规则。覆盖成熟度另用“已实现/部分实现/未实现”，两种标签不互相替代。

## 2. 审计结论

**[现有]** 当前全流程已有真实业务记录，但Trace并非全节点统一埋点：

- 准备Root、Profiler/Intent/Planner及部分Validator有真实Span；Root按Session创建/解析，终止在waiting_approval的采集边界。
- HITL与Engine有审批/任务/执行记录，尚无独立统一Trace Span；Chart Builder实际执行但没有自己的Span。
- Reporting在独立Report Run中有Evidence/Insight/Fact/Assembler/Persistence Span、候选诊断、受控快照和真实Call关联。
- Root有原子CAS；Span的终态检查和Event先写后状态并非等价CAS/原子终结。
- V1.2 C19-A/B已经独立实现和测试，但生产Report Workflow/Writer/Recover没有接入。

**[现有]** 按完整统一契约逐节点评估为9个“部分实现”、3个“未实现”；不把局部功能存在宣称为端到端采集完成。组件级Root CAS/HTTP日志等已有实现可复用，详见缺口报告。

**[现有]** 本轮只读源码/SQL文件，不打开业务数据库、不调用前台/API/LLM、不运行会初始化存储的app或自动化业务测试。没有新的真实Run/Span/Event可展示，也不生成Mock运行数据。

## 3. 权威与身份不变量

**[目标]** 业务状态以可信Session/未来Workflow及PlanVersion、Approval、Execution、Report提交事实为准；Trace仅是观察。既有Control COMPLETED只说明Engine结束，不能推出报告交付。Business Lifecycle、Activity、Execution Outcome和report_delivery保持V1.2分维度定义。

**[目标]** 一个Business Workflow在业务创建事务内预留一个不可变root_run_id。真实Trace Root行可缺失，不能为FK或图完整度补假Run。新Node Span直接run_id=root_run_id，parent_span_id=null；Event、CallRecord、提交元数据、task/step日志不构成第三层。

**[目标]** 每次真实节点重入新span_id/node_attempt；HTTP内部重试只新CallRecord，不重复节点Span；幂等重放不重新计算、不造新Span。Workflow ID、Root ID、operation ID、node_attempt、业务revision、observation_revision、report attempt各有独立语义。

**[目标]** 缺字段、错分支、旧key/revision/attempt必须明确拒绝对应旧结果/观测，不修改当前有效业务或Span。不以“最近成功”、当前配置或报告反推历史过程。

## 4. Span状态字典与转换

**[现有]** 合法Span枚举严格沿用：running、complete、partial、failed、skipped、interrupted。没有waiting_approval、clarify、unknown、blocked等Span状态。

| 状态 | 目标语义 | 必须避免 |
|---|---|---|
| running | 当前合法作业真实进入节点，尚未可靠结束 | 排队、等用户或前端固定延迟当运行 |
| complete | 节点定义的工作与接纳/阶段输出真实完成；不等于全Workflow成功 | 把F0/clarify/denied当技术异常；把候选生成当报告交付 |
| partial | 当前节点确实产生可保留的部分结果，且本节点业务契约支持 | 只因全计划coverage partial就给所有前序节点partial |
| failed | 已执行节点未满足正常结束；附failure_kind与真实错误 | Trace写失败回滚业务；把模型文本自报失败当可信事实 |
| skipped | 真实进入已定义skip处理分支并记录原因，无计算/HTTP | 根本没有调度的节点也补一个skipped |
| interrupted | 确认失主/取消/旧令牌使本次范围未正常结束，实际结果可能部分保存 | 用UI超时或丢回执推断业务失败 |

**[目标]** running可在同身份/作业下更新属性，或以证据进入一个合法终态；所有终态不能重新打开或改为另一个终态。同态running不是新执行。每个节点不支持的partial/skipped明确“不适用”，不能凑状态。

**[目标]** F0/F1/F2属于校验结果：合法F0/blocked结果可使Validator.complete，阻断的是审批/执行。Intent clarify可complete并使业务waiting_input；审核资格denied是正常业务决定。空结果有真实计算引用可complete，不自动failed。

**[目标]** failure_kind区分business、technical、interruption、observation和unknown：数据/业务约束与安全拒绝、HTTP/Schema/存储错误、进程中断、观察写失败分别展示；不能只按HTTP状态码或是否抛AppError分类。

## 5. 生命周期与观测顺序

**[目标]** 每个节点按真实业务执行入口开始。准备节点/事务节点在对应检查点被当前作业接纳后结束；纯Reporting计算阶段以真实产物/摘要结束，不等待最终Report提交，也不宣称已交付。

**[目标]** normal evidence与root source refs必须能追溯；C19节点的正常结束额外要求业务事务已提交、持久证据成立、B获准。Span完成与结束Event在同一Trace事务原子提交；Trace事务失败只产生gap，不修改业务结果。

**[目标]** Registry请求日志是另一种强制设施：begin失败不发HTTP、finish失败不交业务结果。这与Trace fail-open不同。Call.succeeded仅说明Provider协议，节点仍可能因Schema/事实失败；没有HTTP不造CallRecord。

**[目标]** 事件信封、受控字段、类型、source_phase、源引用与版本必须校验。sequence仅为按Run入库顺序，不是业务因果总序。旧事件没有本contract_version时按旧语义读，不能因为同名span.finished就当作原子终结已实现。

## 6. C19四步与异常边界

**[目标]** Report Persistence是一个节点，其中：

1. **C19-A**只授权尝试业务事务；此时不存在可信accepted结果。
2. **业务事务**原子保存Report、Generation、归属、提交元数据与必要revision。
3. **持久核验**从一致业务读确认Report/Generation/归属/audit及提交身份相符；丢返回值仍可以accepted。
4. **C19-B及Trace写**只更新唯一对应的running Persistence Span；B allow还不代表观察写入已成功。

**[目标]** 提交前/中崩溃不能伪造报告成功，提交后/Trace写前崩溃不能因没收到返回值把报告改失败。未知/不一致保守核查，原Span已interrupted则终态保留，业务已提交仍有效。所有细节及跨阶段结果见Recovery Matrix。

**[目标]** C20 unavailable不在V1.2 C19-B的可交付报告范围。这个新native观测终结规则仍未决；本稿不修改V1.2，不虚构C20-B，不在未决前激活该路径或声称全流程埋点验收。

## 7. C2准入与停止点

**[目标]** C2应先做安全记录器/适配测试，后做经批准的身份与真实节点接入。可信Workflow身份、原生Writer/提交核验、Root完整语义、C20观测协议、Span原子终结、受控字段与预算未解决前，不生产宣称统一全Workflow Trace可用。

**[目标]** 本轮不修改Lifecycle V1.2、不切状态权威、不删除Session唯一Root索引、不做Backfill/Switch、不改旧Root/Report Run/历史Span、不新增Trace层或Attempt。完成文档静态检查后停止，等待架构评审。

## 8. 检查的含义

**[现有]** 本轮检查源码AST、字段/引用、节点/事件覆盖、533条设计规则的唯一性与证据约束，以及前后源码/配置与冻结V1.2哈希。533条是待C2实现的验收设计，不是533次已执行的业务测试；静态检查通过不证明生产埋点完成。

**[目标]** 本目录的检查脚本仅运行标准库AST/JSON/哈希校验，不导入app、不打开数据库、不生成Trace或执行Policy。旧源码和冻结V1.2不因文档检查而更新；输出保存在本目录，后续修订另建版本。

## 9. 本轮实际验证与保留记录

- **静态契约检查1358项通过，0失败**，最终结果见verification-release.json；330个源码/配置及冻结V1.2文件哈希前后不变，也没有新增/删除运行代码文件。隔离核对见[isolation-verification.json](isolation-verification.json)。
- 没有打开数据库、没有API/LLM请求、没有Run/Span/Event写入；运行级测试数为0。没有擅自复跑会初始化存储的旧业务测试。
- 已提供12节点、32事件、73源码符号引用、533条C2设计验收用例。统计检查通过不代表这533条已经运行或全流程已实现。
- 两次设计样例生成的类型解析错误另存first/second-failure.txt；首次两轮静态结果verification.json、verification-final.json保留。静态缺项为身份文档少列Registry错误码/策略名称，已补文档而非放宽规则；没有删除历史失败记录。
- 核心未决项包括可信原生Workflow身份/Root生命周期接入、Span原子终结与Event一致性、C19生产事务证据读取、C20 unavailable原生观测协议、字段白名单/预算及多attempt快照策略。准入条件见C2建议，不能仅凭静态检查通过自动实施。

本稿与需求已归档；完成后停止，等待架构评审。后续变更另存版本，不覆盖本目录或Lifecycle V1.2。
