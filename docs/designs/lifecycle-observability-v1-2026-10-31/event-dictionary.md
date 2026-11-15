# Event Dictionary — Lifecycle Observability V1.0

所有条目为**目标**。名称固定，不把它们说成当前已经发出；existing_equivalent仅指出真实旧事件。当前调用点见[observed-call-sites.json](observed-call-sites.json)。旧payload缺contract_version时按legacy语义读取，不自动套用新定义。

## 事件信封

**[现有]** TraceEvent结构只有event_id/run_id/span_id/sequence/event_type/recorded_at/payload。**[目标]** 复用结构，新的关联字段放受控payload；本轮不改API、Schema或安全白名单。

**[目标]** event_id稳定、全局唯一，sequence由TraceRepository分配且只表示该Run的持久写入顺序；recorded_at是实际收集时间，不是未知历史节点结束时间。下表最小业务字段都加上统一common字段；允许null的场合必须说明缺失原因，不填虚构ID。

| 目标common字段 | 类型 |
|---|---|
| contract_version | literal:lifecycle-observability-v1.0 |
| session_id | id |
| workflow_id | id |
| root_run_id | id |
| operation_id | id / null |
| node_key | node_key / null |
| node_attempt | int>=1 / null |
| business_revision | int>=0 / null |
| source_phase | admission / stage_result / business_commit / observation / recovery |
| source_ref | controlled_ref |

**[目标]** node_key/node_attempt/operation_id在Root级事件可为null；Span级事件必须有对应真实值。source_ref是实际业务记录、请求/阶段输出摘要或提交证据引用，source_phase区分接纳、阶段输出、业务提交、观测和恢复，防止把“准备提交”写成“已经提交”。

## 32个稳定事件

### `span.started`

**[目标]** 触发：真实进入并成功登记节点Span后；未接纳请求和重放不发。

| 项目 | 值 |
|---|---|
| source_phase | admission |
| 除common外最小字段 | span_id、status |
| 字段类型 | span_id: id / null；status: span_status |
| 采集通道 | trace_or_gap_log |
| 当前对应 | span.started |
| 源码证据 | S12 |

### `span.finished`

**[目标]** 触发：对应Span终态CAS成功，与终态Event同Trace事务；C19必须B通过。

| 项目 | 值 |
|---|---|
| source_phase | observation |
| 除common外最小字段 | span_id、status、business_outcome、failure_kind |
| 字段类型 | span_id: id / null；status: span_status；business_outcome: bounded_code；failure_kind: business / technical / interruption / observation / unknown / null |
| 采集通道 | trace_or_gap_log |
| 当前对应 | span.finished（当前事件先写，目标语义需要版本标记） |
| 源码证据 | S13、S27 |

### `span.skipped`

**[目标]** 触发：实际进入已定义skip分支，记录原因；Span仍须正常终结为skipped。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | span_id、skip_reason |
| 字段类型 | span_id: id / null；skip_reason: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | span.skipped |
| 源码证据 | S12 |

### `workflow.clarification.required`

**[目标]** 触发：合法Intent clarify与问题引用已保存。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | parse_id、question_count、questions_hash |
| 字段类型 | parse_id: id；question_count: int>=0；questions_hash: sha256 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S34 |

### `workflow.clarification.received`

**[目标]** 触发：补充消息和答案集事务保存。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | answer_message_id、answers_hash |
| 字段类型 | answer_message_id: id；answers_hash: sha256 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S36 |

### `workflow.approval.required`

**[目标]** 触发：审核计划及验证结果保存，明确待用户确认。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | plan_version_id、validation_version |
| 字段类型 | plan_version_id: id；validation_version: id |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S35 |

### `workflow.approval.accepted`

**[目标]** 触发：有效批准事务实际提交。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | plan_version_id、approval_id、command_request_id、warning_ids |
| 字段类型 | plan_version_id: id；approval_id: id；command_request_id: id；warning_ids: bounded_ids |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S44 |

### `workflow.approval.denied`

**[目标]** 触发：真实资格计算明确拒绝；不新增审批，不把勾选当作已解决。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | plan_version_id、denial_code、command_request_id |
| 字段类型 | plan_version_id: id；denial_code: bounded_code；command_request_id: id |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S44 |

### `workflow.plan.revised`

**[目标]** 触发：删除任务形成新不可变版本并重新验证、旧批准引用失效。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | previous_plan_version_id、plan_version_id、removed_task_ids、validation_version、command_request_id |
| 字段类型 | previous_plan_version_id: id；plan_version_id: id；removed_task_ids: bounded_ids；validation_version: id；command_request_id: id |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S43 |

### `execution.claimed`

**[目标]** 触发：服务端claim事务保存执行和批准快照。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、execution_request_id、approval_id、plan_version_id |
| 字段类型 | execution_id: id；execution_request_id: id；approval_id: id；plan_version_id: id |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S56 |

### `execution.task.completed`

**[目标]** 触发：真实任务结果保存；空表也可成功。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、task_id、result_ref |
| 字段类型 | execution_id: id；task_id: id；result_ref: controlled_ref / null |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S57 |

### `execution.task.failed`

**[目标]** 触发：真实失败任务与错误/步骤保存，独立任务可继续。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、task_id、step_id、error_code、failure_kind |
| 字段类型 | execution_id: id；task_id: id；step_id: id / null；error_code: bounded_code / null；failure_kind: business / technical / interruption / observation / unknown / null |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S57 |

### `execution.task.skipped`

**[目标]** 触发：已有真实task skipped记录，例如F0或中断剩余任务。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、task_id、skip_reason |
| 字段类型 | execution_id: id；task_id: id；skip_reason: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S46、S57 |

### `execution.completed`

**[目标]** 触发：完整ExecutionResult和任务状态已提交，不等于报告交付。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、execution_outcome、success_count、failed_count、skipped_count |
| 字段类型 | execution_id: id；execution_outcome: success / partial_success / failed；success_count: int>=0；failed_count: int>=0；skipped_count: int>=0 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S58 |

### `report.queued`

**[目标]** 触发：generation queued已持久化；幂等fresh=False不重复发排队。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、report_attempt |
| 字段类型 | execution_id: id；report_attempt: int>=1 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S52 |

### `report.authorization.allowed`

**[目标]** 触发：C19-A实际允许，只授权尝试事务，不写accepted=true。

| 项目 | 值 |
|---|---|
| source_phase | admission |
| 除common外最小字段 | execution_id、report_attempt、report_id、authorized_revision、authorized_active_key_digest、command_request_id、commit_payload_hash |
| 字段类型 | execution_id: id；report_attempt: int>=1；report_id: id；authorized_revision: int>=0；authorized_active_key_digest: sha256；command_request_id: id；commit_payload_hash: sha256 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S67 |

### `report.authorization.denied`

**[目标]** 触发：C19-A真实拒绝，未提交报告。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | execution_id、report_attempt、denial_code |
| 字段类型 | execution_id: id；report_attempt: int>=1；denial_code: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S67 |

### `report.commit.accepted`

**[目标]** 触发：持久提交证据成立，不只凭内存返回；未观测到可缺Event。

| 项目 | 值 |
|---|---|
| source_phase | business_commit |
| 除common外最小字段 | execution_id、report_attempt、report_id、report_digest、commit_evidence_ref、committed_revision |
| 字段类型 | execution_id: id；report_attempt: int>=1；report_id: id；report_digest: sha256；commit_evidence_ref: controlled_ref；committed_revision: int>=1 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S54、S69 |

### `report.commit.rejected`

**[目标]** 触发：提交尝试已明确CAS拒绝或回滚，未形成新提交；缺少回执不能发此事件。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | execution_id、report_attempt、denial_code |
| 字段类型 | execution_id: id；report_attempt: int>=1；denial_code: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S54 |

### `report.commit.reconciled`

**[目标]** 触发：恢复只读查询事实，按证据记录accepted/not_committed/unknown/inconsistent。

| 项目 | 值 |
|---|---|
| source_phase | recovery |
| 除common外最小字段 | execution_id、report_attempt、accepted_status、accepted、commit_evidence_ref、writer_isolated |
| 字段类型 | execution_id: id；report_attempt: int>=1；accepted_status: accepted / not_committed / unknown / inconsistent；accepted: bool / null；commit_evidence_ref: controlled_ref；writer_isolated: bool |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S69 |

### `report.completion.observed`

**[目标]** 触发：C19-B允许且精确Span终态写入成功，不修改Root；缺Span只记gap。

| 项目 | 值 |
|---|---|
| source_phase | observation |
| 除common外最小字段 | execution_id、report_attempt、report_id、span_id、commit_evidence_ref |
| 字段类型 | execution_id: id；report_attempt: int>=1；report_id: id；span_id: id / null；commit_evidence_ref: controlled_ref |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S68 |

### `insight.candidate.validated`

**[目标]** 触发：确定性Fact Validator检查实际候选，不记录被拒绝原文。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | candidate_index、candidate_status、evidence_refs、rule_ids |
| 字段类型 | candidate_index: int>=0；candidate_status: accepted / rejected；evidence_refs: bounded_ids；rule_ids: bounded_ids |
| 采集通道 | trace_or_gap_log |
| 当前对应 | candidate.validated |
| 源码证据 | S51 |

### `insight.candidates.summarized`

**[目标]** 触发：真实候选校验完成或在失败前已取得可靠数量；计数一致。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | candidate_count、accepted_count、rejected_count |
| 字段类型 | candidate_count: int>=0；accepted_count: int>=0；rejected_count: int>=0 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | candidates.summarized |
| 源码证据 | S51 |

### `llm.started`

**[目标]** 触发：Journal成功且真实进入HTTP dispatch attempt；不声称远端已收到。

| 项目 | 值 |
|---|---|
| source_phase | admission |
| 除common外最小字段 | call_id、request_snapshot_id、template_snapshot_id、call_sequence、retry_index、dispatch_state |
| 字段类型 | call_id: id；request_snapshot_id: id；template_snapshot_id: id；call_sequence: int>=1；retry_index: int>=0；dispatch_state: attempted / not_attempted / unknown |
| 采集通道 | trace_or_gap_log |
| 当前对应 | llm.started（当前Reporter仅表示准备调用） |
| 源码证据 | S61、S60 |

### `llm.returned`

**[目标]** 触发：Provider协议完成/返回；Schema/事实校验仍可失败。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | call_id、request_snapshot_id、provider_outcome |
| 字段类型 | call_id: id；request_snapshot_id: id；provider_outcome: succeeded / failed / cancelled / interrupted |
| 采集通道 | trace_or_gap_log |
| 当前对应 | llm.returned |
| 源码证据 | S59 |

### `workflow.callback.rejected`

**[目标]** 触发：旧revision/key/attempt/绑定回调已拒绝，不修改当前Span；挂Root事件或日志。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | refused_operation_id、refused_span_id、received_revision、current_revision、received_active_key_digest、current_active_key_digest、refusal_code |
| 字段类型 | refused_operation_id: id；refused_span_id: id / null；received_revision: int>=0 / null；current_revision: int>=0；received_active_key_digest: sha256 / null；current_active_key_digest: sha256 / null；refusal_code: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | workflow.callback_ignored / report.callback_ignored |
| 源码证据 | S33、S53 |

### `workflow.recovery.detected`

**[目标]** 触发：确认未完成记录及失去执行者，未宣布业务失败或成功。

| 项目 | 值 |
|---|---|
| source_phase | recovery |
| 除common外最小字段 | recovery_reason、writer_isolated、restored_source_refs |
| 字段类型 | recovery_reason: bounded_code；writer_isolated: bool；restored_source_refs: bounded_ids |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S30、S46 |

### `workflow.recovery.reconciled`

**[目标]** 触发：已核对业务持久事实后的恢复结果，不能从Trace反推业务。

| 项目 | 值 |
|---|---|
| source_phase | recovery |
| 除common外最小字段 | recovery_outcome、restored_source_refs、failure_kind |
| 字段类型 | recovery_outcome: bounded_code；restored_source_refs: bounded_ids；failure_kind: business / technical / interruption / observation / unknown / null |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S55、S69 |

### `observation.gap_detected`

**[目标]** 触发：实际发现采集失败/限流/缺字段，写不可用时只走受控日志，不造回补Span。

| 项目 | 值 |
|---|---|
| source_phase | observation |
| 除common外最小字段 | gap_code、affected_node_key、missing_count、detected_at |
| 字段类型 | gap_code: bounded_code；affected_node_key: node_key / null；missing_count: int>=0 / null；detected_at: utc_time |
| 采集通道 | gap_log_then_optional_trace |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S17、S20 |

### `workflow.command.replayed`

**[目标]** 触发：已确认幂等只读重放，不新节点；只在仍活动Root可记录，终态查询不复活Root。

| 项目 | 值 |
|---|---|
| source_phase | stage_result |
| 除common外最小字段 | command_request_id、recorded_result_ref、scope_status |
| 字段类型 | command_request_id: id；recorded_result_ref: controlled_ref；scope_status: bounded_code |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S45 |

### `workflow.root.created`

**[目标]** 触发：实际登记预留Root ID成功；业务Workflow可以存在而此事件缺失。

| 项目 | 值 |
|---|---|
| source_phase | observation |
| 除common外最小字段 | root_status、observation_revision |
| 字段类型 | root_status: run_status；observation_revision: int>=0 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S23 |

### `workflow.root.state_changed`

**[目标]** 触发：真实业务证据支撑，Root CAS成功后与状态原子入Trace库；不从Event单方面驱动业务。

| 项目 | 值 |
|---|---|
| source_phase | observation |
| 除common外最小字段 | previous_root_status、root_status、observation_revision |
| 字段类型 | previous_root_status: run_status / null；root_status: run_status；observation_revision: int>=0 |
| 采集通道 | trace_or_gap_log |
| 当前对应 | 没有明确的现有同义事件；不得伪造历史 |
| 源码证据 | S25 |

## 顺序、幂等与采集缺口

**[目标]** 事件不会触发业务状态转换。已提交事件须有持久source_ref；同一event_id重试不重复追加，改变payload拒绝；可按实际source事务/事件ordinal提供幂等来源，但不得按当前时间生成“历史开始”。跨库无exactly-once，业务提交后事件缺失必须承认gap。

**[目标]** 原子Trace终态写：在同一Trace库事务内完成Span CAS与对应span.finished/report.completion.observed事件。写失败整笔观察回滚，业务提交不回滚。不依赖Event存在来反推Span状态，也不依赖Span状态替代业务提交。

**[现有]** 目前span.finished/run.finished先写事件再写状态，尚未满足该原子规则。Workflow Root事件在库内MAX(sequence)+1；Legacy Report Run主要用Context本地sequence。两种情况不能视为同样的并发顺序保证。

**[目标]** 终态事件含业务outcome和failure_kind。F0、clarify、审核denied是确定性业务结果，不一定是Span.failed；解析坏JSON/Provider不可用是技术失败；旧回调拒绝只解释该旧作业，不能把当前Span标失败。

**[目标]** llm.started只证明本地HTTP尝试边界，不证明远端收到。Call.succeeded仅是Provider协议完成，后续Schema/事实可失败。Registry.begin成功但在dispatch前取消时，Call可能interrupted且dispatch未知，不补造远端成功或另一次HTTP请求。

**[目标]** 当前256事件/Context、Workflow Run全局256上限和8KiB payload限制仍是现状。C2必须在不丢关键提交事实的设计下评审摘要/限额；受限时写gap日志，不把“没有错误事件”宣称为无错误。每行、每step不逐一无限埋点，采用有界任务摘要和真实执行日志引用。

**[目标]** Trace DB不可用时observation.gap_detected只进入受控日志；恢复后最多追加“现在发现缺口”的事件，不补造过去的Span。missing_count未知就null，不把日志速率限制隐藏成零丢失。

## 脱敏与权限

**[目标]** 不记录原始API Key、完整数据行、完整用户消息、被拒绝洞察原文或raw active key；记录key digest、约束/问题hash、引用与有限计数。Trace摘要不承诺能恢复原文。完整模型请求只走现有独立授权Registry快照与保留策略；到期显示unavailable。

**[现有]** recorder.safe的SAFE_KEYS不会放行本文全部字段，字符串截断160字、列表80项。C2必须做字段迁移与截断标记测试，不能假设attributes里传入了就已经保存。

## 字段值约束与设计样例

**[目标]** id为不含空白的受控引用，最长128字符；sha256为64位小写hex；bounded_code最长96字符；controlled_ref为不暴露本地任意路径或原文的短引用；bounded_ids最多80项且每项128字符。计数使用有限非负整数，不能NaN；UTC时间须有明确时区。

**[目标]** 必需身份/分支引用不得截断成另一个ID。超预算/超长时拒绝该观察并gap，不影响业务；可选数组要截断必须同时给truncated_fields/payload_sha256及可靠源引用，不能让截断子集看起来完整。

**[目标]** span.started只允许status=running，span.finished只允许五个终态；llm.started只允许本地attempted，llm.returned代表provider_protocol=succeeded；root.created只允许queued/revision0。候选汇总accepted+rejected必须等于candidate_count。reconciled的accepted仅与四态核验结果一致，不能在unknown时填false。

**[现有]** [event-fixtures.json](event-fixtures.json)是明确标记design-only的32个字段样例，没有入库，不是历史运行或伪造Trace。它仅用于本次静态校验，不构成LLM或业务执行证据。
