# 通用分析口径登记与审批绑定 V1 — REQ-0100

## 交付范围

已实现通用的记录粒度声明、实际计数/去重/聚合定义展示，以及计划版本、审批、执行和报告之间的口径绑定。字段来自真实画像和操作链，没有写死销售字段，不引入新模型或Agent节点。

本轮不是完整业务语义识别系统。未知粒度保留unknown；默认审批仅批准已展示的实际字段/函数，不冒称未知的实体含义已确认。已有clarify、defer和约束未映射阻断不被声明解除。单位、币种、税费、退款、任意公式及组合标识的编辑尚未实现。

## 契约与行为

初始计划、删除任务的计划在原业务事务内登记不可变计划口径侧车。粒度声明为unknown/record/detail/entity。entity必须指定当前数据集画像中非空且全局唯一的字段；这是必要的数据核验，实体业务含义仍来自用户声明，不是LLM已验证。声明只描述上传数据，不改变中间聚合表的含义。

修改声明通过 POST /api/v1/sessions/{session_id}/analysis-basis，参数为expected_revision、plan_id、plan_version、row_grain、entity_field_id。服务端验证当前版本、revision及合法待审/已批准状态。原事务生成新PlanVersion（change_type=basis_updated）、重新调用Validator、登记新口径、清空旧批准。完成/执行中的分析不能在此重开。计算操作与原始意图保持不变；调整字段/函数需重新提出明确需求。重复旧revision拒绝，不静默追加新版本。

删除任务继承同数据版本的粒度声明，重新生成剩余任务指标定义。批准时在原审批事务内复制精确口径快照。Engine执行前核验计划hash、版本、数据集、session与批准副本一致，新计划缺失批准口径副本时拒绝。批准后的口径摘要随正常执行元数据保存，再由原Report Module传递到报告；页面与HTML均可展开“审批绑定的指标定义”。旧载荷不回填，保持unknown。

## 数据库存储

业务SQLite新增 plan_analysis_bases(session_id,plan_version,record)，组合主键/外键引用原plan_versions。approval_analysis_bases(approval_id,session_id,plan_version,record)引用计划侧车与同session审批。为组合外键新增原审批表的唯一索引approval_basis_owner(approval_id,session_id)。两表都有UPDATE/DELETE不可变触发器，使用现有SQLite外键开启连接。

初始化沿用现有PlanReviewRepository的幂等建表机制；无Backfill、Workflow Switch、第三层Trace或新Attempt实体。业务状态权威仍是Session单流程；这些session/plan_version作用域未来进入1:N Switch时也需迁移，不宣称本轮已支持多Workflow。

重载前使用SQLite在线backup API分别备份业务、Trace、Registry，三份integrity_check均ok，见backup.json。未直接复制活动WAL主文件，三库备份不宣称跨库原子快照。

## 实际改动

21个源码/测试/样式文件，详见changed-files.json与after.zip。包括新模块review/analysis_basis.py、两个持久侧车、审核新入口、Engine核验与传递、页面/HTML读取、API与测试。

前端沿用工作台绿色/白色视觉体系：可选展开区、中文函数名称、清晰字段标签、禁用重复/缺失标识、保存版本与重新审批提示。保存期间禁用审批与任务删除。审批不符合条件时仍可登记粒度，但不能解除其他阻断。

Prompt正文与模型参数未修改。契约源码属于实际组合快照依赖，组合版本追加到composition-v0.8-analysis-basis-v1，历史快照保留。

## 自动化验证

- 完整后端：1609 passed，87.17秒。最后仅做来源说明文字调整后，口径/报告/API定向回归65 passed。
- 前端：82 passed；TypeScript及Vite构建通过。
- Admin：88 passed，构建通过。
- 新测试覆盖四主题真实字段映射、原操作定义、版本失效、旧请求、重复标识拒绝与事务回滚、实体标识核验、任务删除继承、不可变表、缺审批口径副本拒绝、原defer不可被确认解除、UI保存回调及审批问题与声明编辑的分离。
- 初始测试有一项StopIteration：原销售样例确实没有全局唯一列。测试改用追加真实唯一标识列的隔离样本，没有修改原文件或放宽唯一校验；失败日志保留。

## 真实模型与页面验收（不能混成一个成功率）

使用4行合成CSV：记录编号、类别、处理分钟。三次独立用户需求共7次真实qwen3.8-flash请求，真实Intent/Planner参与；未使用Mock伪装真实模型。

1. “通用口径验证：按类别统计记录数，按记录数降序排列。记录数按行计数，不要求分析处理分钟。”：Intent/Planner完成，但“不要求分析处理分钟”无法被原约束审计映射，审批保持阻断，未执行。
2. “口径入口验收：按类别统计记录数，按记录数降序排列。记录数按上传记录逐行计数。”：原审计对“记录数按上传记录逐行计数”亦未映射。真实页面成功保存实体粒度为v2，原阻断仍保留，未执行。
3. “按类别统计记录数”：真实页面声明entity，选择记录编号，保存v2、重新审批并执行。咨询2条、投诉2条；计划/批准口径digest、执行与报告元数据精确一致。Report已持久化并可读取，但report_status=partial：一条候选触发REPORT_INVALID_EVIDENCE_TYPE被拒绝，保留另一条合法洞察，没有伪装complete。

第三条：workflow_id=wf_d5f123209ea641edaba85007c7968d0a；session_id=c48ef698bac24a68b95a0f4a35ac2036；report_id=report_87b21283bec0446e959806483fdd3cc3。对应Root、计划和完整关联见real-ui-results.json；调用ID、实际快照引用、耗时、response_hash见real-llm-call-refs.json；不是完整原始HTTP响应文本。

下载验证：保存的entity声明与计划第2版均进入HTML。basis-editor-final.png、report-approved-basis.png等为真实页面截图，阻断与partial均保留。原用户销售Session、PlanVersion、Approval、Execution、Report原始JSON与备份逐项相同，见original-records-unchanged.json。

## 尚未解决与下一步

当前机制不自动识别所有业务实体/口径歧义，不允许通过声明修改计算函数，也不解决任意单位/公式。最紧迫的后续问题是上述两种通用自然表达的约束证明误拦截，以及Report候选与证据类型的匹配可靠性。不能因本轮新增侧车、页面和测试通过而宣称专业分析质量已验收。

新代码兼容旧记录，但旧版严格读取器不认识basis_updated和新的执行元数据；回滚旧源码前必须保留兼容读取和口径核验补丁。新增侧车不可因回滚删除；没有覆盖历史审计载荷。

before.zip保存17个原文件；样式原文另存before-chat-workspace.css；原前端审核测试从已冻结REQ-0094源码快照恢复，已核对与本次只追加测试前的前缀完全相同。旧版本需求、Prompt、评测及失败记录未覆盖。
