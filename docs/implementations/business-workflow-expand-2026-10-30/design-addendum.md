# Phase 02-A 实施前设计补充

关联 REQ-0077；原 Phase 02 README.md/migration.md 已冻结，本补充以新文件保存，不覆盖旧稿。本阶段仅 Expand，生产业务 Workflow 数必须仍为 0，新表不接入业务写入。

## 1. 创建事务与幂等

未来 Workflow 创建必须在一个业务库事务内保存 workflow_id、session_id、origin_message_id、不可变 root_run_id、creation_request_id 和 creation_payload_hash。使用同一张 business_workflows 的 NOT NULL/UNIQUE 约束，避免先预留幂等键、再单独写 Root ID 的间隙。Trace 实体仍在侧库 best-effort 登记，不参与业务提交成败。

本阶段只有 Schema 和只读 Reader，没有 Workflow 创建服务或 API，也不插入默认 Workflow。临时数据库可以直接构造两个 Workflow 验证约束，不能据此宣称生产已开放 1:N。

## 2. 新事实与归属原子性

Workflow 原生审批、执行和报告将来必须由唯一事务仓储在同库保存事实、归属链接及 Workflow 当前引用/revision；链接失败应回滚该新事实，不能产生可见的无归属 v2 结果。组合 FK 和索引验证同 Session/Workflow；原 JSON 快照也必须核对，不能仅凭 ID。

阶段边界：当前旧业务路径仍属于 legacy Session 权威，不要求其立即写新链接，否则与“禁止接入新写入路径/禁止 Backfill”冲突。Expand 不添加会拦截现有业务的强制链接触发器；本阶段测试以显式事务验证结构支持原子回滚，不能把单向 FK 宣称为已经实施了未来 writer。Phase 02-B 也不能跳过后续 writer/Switch 审查。

## 3. Switch 的前置条件（本轮不执行）

除 Session.status 外，需要核对：executions.status=running、ReportGeneration queued/generating、Trace queued/running、LLMCallRecord running，以及内存/进程中的异步任务。业务库没有活动行不等于没有旧 worker。应进入维护/拒绝新写窗口，排空或终止旧 worker，核对实例清单和服务版本，并验证新回调 fencing 后才允许 Switch。

切换需 Workflow revision+active_execution_key+精确计划/批准/执行/report attempt 同时校验；旧 callback 不得取得新令牌后重放。原 Root observation_revision CAS、旧回调忽略和 Report accepted 提交确认继续保留。数据库写保护与路由隔离必须在新权威启用前部署并演练，不能只依赖前端按钮。

当前只新增 session_workflow_routes 元数据结构，不改变路由，也不启用上述 Switch 触发器。

## 4. 消息与父子关系

Session 是消息所有者；message_id 和 sequence 在 Session 内稳定。origin_message_id 必须属于 Workflow.session_id，表达最初提出本分析目标的消息，不等于“最后一条消息”。消息可为会话级（workflow_id 为空），也可关联明确 Workflow。

创建时可先插入未分配 Workflow 的消息，再插入引用该消息的 Workflow，最后在同事务设置消息归属。消息一旦有 Workflow 归属不可换给另一 Workflow；Workflow.origin_message_id、目标、Session 和 Root 身份不可变。parent_workflow_id 仅记录同 Session 已存在的来源，不授权执行、不继承审批；禁止自引用，创建后不得修改。历史缺失允许 archive 来源明确为空，不能造消息。

消息主键使用 (session_id,message_id)，不额外假定历史嵌入 JSON 的消息 ID 在所有会话间唯一。origin_message_id 是来源指针，不是“当前任务”解析器；不得通过它或消息的时间自动选择 Workflow。业务命令仍须明确 workflow_id，创建幂等以创建请求键控制，本阶段没有开放来源消息衍生多个分析的入口。

## 5. Report 三种事实

ReportGeneration 是每 execution_id 的当前状态和当前 attempt；不是完整历史尝试表。历史 Report Run 是旧观测及其诊断，保留原记录；不是新的业务 Attempt 实体。AnalysisReport 是实际提交的不可变报告，只有业务提交 accepted=True 才能声明交付成功。

本阶段 report_generations 不新增镜像状态表；Workflow 归属由 execution 链接及已提交报告链接确定。没有保留下来的历史 generation 不从 Trace 反推补造。

## 6. Schema 迁移与备份政策

显式离线维护命令处理三个数据库，不在应用启动时执行。每库独立 BEGIN IMMEDIATE、FK=ON、Schema checksum 与版本记录；不使用 executescript 的隐式提交，不关闭 FK。完整匹配的已登记 Schema 幂等；缺对象、同名错定义、缺版本的部分 Schema 明确报错，不自动删表/改记录。跨库部分成功单独报告；修复失败库后可重跑其余库的校验，不谎称分布式原子提交。

迁移前采用 SQLite backup API，纳入已提交 WAL 内容，备份副本做 quick_check/foreign_key_check，权限 0600。三个备份分别一致，并不天然跨库原子；活跃任务必须清空，停止后端写进程后再取得协调维护窗口。不能复制正在运行的 .sqlite3 文件充当一致备份。

原表、PK、唯一索引、不可变触发器全部保留。仅增加支持组合 FK 的唯一索引，保留 Session 唯一 Root 索引。新表为空，只写迁移版本行。旧应用不感知这些空表；新 Schema 不代表状态权威切换。
