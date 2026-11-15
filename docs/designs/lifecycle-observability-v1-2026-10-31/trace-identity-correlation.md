# Trace Identity & Correlation Contract

REQ-0082；目标适用Lifecycle V1.2与新原生Workflow，历史按原capture_scope读取。本文件不修改当前身份模型。

## 1. 当前传播链路（源码事实）

| 标记 | 路径 | 当前实际关联与限制 | 源码 |
|---|---|---|---|
| 现有 | 上传/创建Session | API保存Session后调用trace_created；不是业务事务内预留Business Workflow Root ID | create_router / WorkflowOrchestrator.trace_created |
| 现有 | register_root | 随机生成run_id，kind=workflow、workflow_run_id指自身，manifest只有session/file等初始绑定；按Session唯一Root索引去重 | register_root / TraceRepository.create |
| 现有 | 准备调度 | preparation_context按session_id找Root；bind_trace以ContextVar限制在当前异步上下文；不是持久Workflow ID | preparation_context / bind_trace / prepare_real |
| 现有 | 节点子调用 | SpanHandle以active父节点拼node_key，可能有parent_span_id；准备Span用库内node_attempt分配 | SpanHandle.__init__ / reserve_workflow_span |
| 现有 | Intent/Planner LLM | parse/operation_id、call_sequence和retry_index，通过TemplateSource.binding从真实active Trace获取run/span；Trace不存在时它们可空 | IntentParserService.parse / AnalysisPlannerService.plan / TemplateSource.binding |
| 现有 | HITL与Engine | 以session_id、Plan/Approval/Execution记录运行；没有从请求贯穿到统一Root的Span/Context | PlanReviewService / AnalysisEngineService |
| 现有 | Report排队 | 按execution_id+generation.attempt创建独立kind=report_generation Run；workflow_run_id仅在找到Session准备Root时有值；retry_of_run_id指上个真实Report Run | TraceRecorder.queue / ReportWorkflow.enqueue |
| 现有 | Reporting LLM | 显式trace参数传给TemplateSource.binding；operation_id每次新生成，但没有统一放入Span属性；CallRecord有run/span引用，没有workflow_id字段 | AnalysisReportService.generate / LLMCallRecord |
| 结构已具备 | Expand关联 | Business Workflow预留root_run_id、trace_workflow_links、llm_call_workflow_links与只读Reader存在，生产Writer尚未启用 | workflow_expand_*_001.sql / WorkflowReader.observation_links |

实际行号见[source-index.md](source-index.md)。`workflow_run_id`现在是Trace Run关联，不等于已存在的Business Workflow ID；禁止把两者或session_id混为一体。

## 2. 目标两层身份

```text
Session（对话空间）
  Business Workflow（一个独立目标，业务对象）
    root_run_id（在业务创建事务预留，实际Root可缺失）
      Node Span（直接run_id=root_run_id，parent_span_id=null）
      Node Span（新的真实重入，新span_id/node_attempt）
```

**[目标]** Session和Business Workflow不是新的Trace层；Event、CallRecord、请求快照、commit元数据不构成第三层。一个Workflow逻辑上唯一Root ID，真实Root行是0..1，不为了FK补造未采集Run。新Node Span没有Span父级；技术子步骤改用Event/业务日志。

**[目标]** Root身份在Workflow创建事务与幂等键一起预留；Trace创建另库best-effort。实际Root.create只能登记预留ID，不生成第二个随机Root替换它。已有不同ID必须报关联不一致，不静默采用Session最新Root。

**[现有]** 当前Root.create使用INSERT OR IGNORE后按Session读取，仍依赖Session唯一索引；不满足上述新原生语义。本轮不删索引、不切解析器，也不创建Business Workflow或Root。

## 3. 分层字段与存放位置（目标）

| 字段组 | 必需语义 | 建议复用位置，不是本轮迁移 |
|---|---|---|
| 初始身份 | session_id/workflow_id/root_run_id、输入授权与原目标hash、policy_scope | Root.manifest.bindings在创建时登记；后续不得改成当前配置 |
| 每次节点执行 | node_key、span_id、node_attempt、operation_id、开始业务revision、active_key_digest、输入hash | Span结构现有字段+受控attributes；目标字段需扩白名单与校验 |
| 当前业务分支 | Dataset/PlanVersion/validation/Approval/Execution/report attempt | 每次Span/Event的精确source refs；不能通过改不可变Manifest填入未来ID |
| 提交证据 | request/hash、authorized/committed revision、授权key摘要、report ID/digest、唯一persistence_span_id | 业务report.audit及可信只读投影，Trace只存受控引用 |
| 事件关联 | run/span、按Run持久sequence、业务source_phase/source_ref | 现有TraceEvent结构+受控payload |
| 模型调用 | node_id、operation_id、sequence/retry、实际模板与最终请求/Schema/参数hash | 现有LLMCallRecord/RequestSnapshot；Workflow关联复用现有link结构，禁止猜历史 |

**[目标]** 尚未生成的ID不填空字符串或假版本：Profiling开始只要求input file，DatasetVersion在结果后；Intent有Dataset但无Plan；Engine开始加载可尚无execution_id，claim后必须补精确引用；Report Persistence在提交前已有report_id但没有accepted；B依持久证据核验。

**[目标]** 关联容器必须可序列化并由可信业务层传递，不能在背景任务中只带session_id然后重新“查最新”。ContextVar只做本任务便捷读取，不能成为独立事实来源；必须在finally reset，防止不同Workflow/并发调用串上下文。

## 4. 五种revision/计数不能互换

| 标记 | 名称 | 语义 |
|---|---|---|
| 现有 | business_revision | 当前准备Root携带Session revision；目标来自Workflow，不得回退 |
| 现有 | observation_revision | Run更新CAS令牌，独立于业务revision；同business revision旧对象也会拒绝 |
| 目标 | node_attempt | (root_run_id,node_key)内的真实执行重入序号，须原子预留，不靠列表位置；不单建Attempt实体 |
| 现有 | call_sequence/retry_index | 一次模型业务operation内每次真实HTTP尝试的日志序号；不等同节点重入 |
| 现有 | ReportGeneration.attempt | 当前报告执行尝试，精确绑定Execution；不代表完整业务历史Attempt表 |

**[目标]** node_attempt不因为页面刷新、错误重放或内部HTTP重试而递增；重新进入节点的真实新调用才递增。不同validation_role仍共用node_key=plan_validator，用属性/operation区分，不把role拼进node_key导致无法稳定对齐。

**[目标]** Root.owner_instance是不可变的创建者标识，不是可转移的Worker lease。不能把它当作恢复后的当前执行权；实际Worker隔离依业务活动令牌/可信失主证据，不以此字段更新来接管Root。

## 5. Trace CAS、Span终态与Event顺序

**[现有]** Root update_run用BEGIN IMMEDIATE、不可变身份/Manifest及observation_revision，保证原子读比写；准备Root只支持queued/running/waiting_input/waiting_approval/failed/interrupted的特定边，waiting_approval无继续边。Report Run有独立终态规则。现有Span save_span没有同等独立CAS令牌，先SELECT再upsert，有并发旧running读覆盖终态的推导风险。

**[目标]** 新Span终结必须在Trace库事务中验证原run/span/node身份、running前态与本次operation/尝试、不可倒退的绑定，原子更新并追加终态Event。持久化节点还须B许可及commit evidence，不能只验证一份旧内存Span。C1不新增列/令牌；C2须给出兼容实现，不得假设Root CAS已经覆盖所有Span。

**[目标]** Event的sequence是持久入库顺序，不是业务因果总序；跨库不能保证业务提交与Event exactly-once。业务occurred_at仅在可靠源时间存在时记录，recorded_at保留实际观测时间。不能从sequence、rowid或最后一个事件推导当前业务分支。

**[目标]** 重复终态写只有“同一个已完成观察”的只读幂等；不能先结束再重新打开。终态Span不改partial/complete/failed标签以迎合新报告；恢复改用真实业务投影和gap说明。

## 6. Legacy Report Run

**[现有]** Report Run：真实execution_id+attempt；重试关联retry_of_run_id。workflow_run_id可空，表示未采集准备Root。Report Span.run_id是Report Run，不能改写成业务Root。

**[目标]** 历史按(kind,capture_scope,manifest/source refs)区分，不用当前Prompt/配置填unknown。旧嵌套Span、旧Report Run和缺失Workflow归属原样读取；不重新排父子、不补假历史Run、Span、Event或Attempt。

**[目标]** 新native Root身份未具备时，C2不得偷用session_id=workflow_id，不得为Engine另建平行Run，不得把Engine挂在Report Run下冒充统一Workflow。可先交付协议/适配测试，生产整链路接入须满足准入条件。

**[目标]** C19-B只确认对应Span，不扩大Root转换。Root.complete时可核验同一仍running Persistence Span的真实提交，不触发Root.complete→running。历史已interrupted/failed等终态Span保持不可变。

## 7. 模型关联与失败分离

**[目标]** 真实HTTP请求尝试单独CallRecord，有限重试每次新Call ID/sequence/request snapshot；不因调用失败伪造响应。响应Schema/Prompt动态变化按实际请求记录，不用重渲染推测。

**[现有]** Registry.begin在实际发送前保存请求，取消可能发生在dispatch前；Call存在不能证明远端收到。Call.succeeded是provider_protocol，不保证节点语义成功。既有Insight llm.started发生在provider.generate前，不能视为已发HTTP证据。

**[目标]** Call关联真实Run/Span存在时用实际ID，不存在就null；Workflow/root预留身份可用关联link记录，但不能为了完整性插入假的Trace行。关联link的观测失败不改变业务；强制Registry请求快照/终结日志失败仍按既有fail-closed，不能混用。

**[目标]** 原始请求与密钥不进入Trace payload。完整请求按独立权限/过期策略取；过期或历史缺失显示unavailable。local_test不是生产鉴权完成，本轮不改权限行为。

**[现有]** 明确错误语义：请求日志begin无法保存时返回`LLM_SNAPSHOT_UNAVAILABLE`，本次HTTP不发；finish日志终结失败返回`LLM_CAPTURE_FINALIZE_FAILED`，已发生请求的结果不交付业务。Trace写失败则是`TRACE_WRITE_FAILED`受控日志/采集缺口，不能混为同一种恢复策略。

**[目标]** 两种策略名称固定：Trace采集为 **fail-open**，强制Prompt Registry请求日志为 **fail-closed**。前者可缺观察但保业务，后者本身是当前模型请求的强制条件；不得把它们合并为“所有日志失败都不影响请求”。
