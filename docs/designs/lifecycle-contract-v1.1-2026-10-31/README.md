# InsightFlow Phase 03-A.1 — Lifecycle Contract V1.1

日期：2026-10-31（Asia/Shanghai）  
需求：REQ-0079，修订 REQ-0078 的 V1.0。  
冻结范围：本目录的契约、表格、验收样例与审计依据。冻结是本地哈希与追加版本归档，不冒充远端不可篡改存储。  
性质：设计基线，不是代码发布、API 变更、Policy Validator 实现或业务权威切换。

## 0. 阅读约定与规则适用范围

**[现有]** 当前 SessionState 仍是业务状态权威；Phase 02-A 新表尚未接入原生写入，生产不开放第二个 Workflow。当前 Workflow Root 只覆盖准备阶段，waiting_approval 是其现有采集边界；独立 Report Run 继续存在。

**[目标]** 本文对每项规则使用且仅使用以下实施标记。标记是实施成熟度，不是优先级：

| 标记 | 解释 |
|---|---|
| 现有 | 已由当前源码验证；不能把运行现状自动当作 V1.1 目标许可 |
| 结构已具备 | 已有 Expand 表、约束、字段或只读解析器；没有对应原生业务 Writer |
| 目标 | V1.1 的规范要求，需要后续开发与测试才能上线 |

**[目标]** 默认按 `native_v1.1` 契约执行未来原生 Workflow；当前业务按 `legacy_session_v1` 行为审计与兼容。两者的差异必须显式保留，不能混用同一条“允许”规则。这里只命名设计适用域，未向任何现有表/API 添加 policy 字段。

**[目标]** “允许命令”表示满足所有资格后可以接纳，不表示可以跳过 FK、版本、校验、审批、幂等或 fencing。所有未列出的新写命令默认拒绝。查询、复制、预览、下载不是业务重执行。新建 Workflow 是另一对象的创建，不是旧 Root 的恢复。

**[目标]** [contract-tables.json](contract-tables.json) 是本文矩阵的结构化配套；不是运行决策服务。矩阵描述的目标转换不得直接用于解释历史 Root。自动一致性检查只验证设计内部与源码证据，不证明尚未实现的业务安全性。

## 1. 实体、身份与状态权威

| 标记 | 实体 | 身份与权威契约 |
|---|---|---|
| 现有 | Session | SessionState.status/revision 与当前计划、批准引用等承载业务控制；不是只存聊天的容器 |
| 目标 | Session | 表示持续对话空间，拥有消息与 Workflow 列表；不再充当所有 Workflow 的共享当前状态 |
| 结构已具备 | Business Workflow | workflow_id、session_id、root_run_id、输入引用、目标、control_status/context、revision、active_execution_key、当前 plan/approval/execution 指针已在 Expand Schema |
| 目标 | Business Workflow | 每个独立分析目标一个 Workflow，锁定数据版本；澄清和执行前修订属于同目标；完成后不重开原目标 |
| 目标 | Workflow 创建 | workflow_id、Root ID 预留、creation_request_id/payload_hash、来源消息与输入授权在同一业务事务提交；Trace 实体在侧库 best-effort 创建 |
| 结构已具备 | 消息/父关系 | 消息主键 (session_id,message_id)，origin_message_id 同 Session；parent_workflow_id 同 Session、不可自引用、身份不可变 |
| 目标 | 来源语义 | origin_message_id 是最初提出目标的消息，非“最后一条消息”；parent 只记来源，不继承审批、不构成第三层 Trace |
| 目标 | PlanVersion | Workflow 内独立版本序列；所有新版本不可变；新 Workflow 可拥有自己的版本 1 |
| 现有 | Approval | 不可变审批记录与批准快照；当前引用决定是否仍有效，历史 approved 不等于现在可执行 |
| 目标 | Execution | 精确引用 Workflow、Dataset、PlanVersion、validation 与 Approval；结果不被报告状态覆盖 |
| 现有 | ReportGeneration | 每 execution_id 一条当前状态和当前 attempt；不是完整历史 Attempt 表 |
| 现有 | AnalysisReport | 实际提交的不可变报告；报告完整性与目标覆盖分开记录 |
| 目标 | Trace | 一个逻辑 Root，多个直接 Node Span；物理 Root 可因采集失败缺失；不以 Trace 存在作为业务实体存在条件 |
| 现有 | LLMCallRecord | 每次真实调用的请求日志；并非独立 Attempt，也不是 Trace 第三层 |

**[目标]** 不创建第二套可写 business_lifecycle 状态机。业务控制状态持久化；执行结果、报告生成/交付和覆盖状态来自其真实记录；business_lifecycle/activity/collection/consistency 由只读聚合派生。current_phase 是 activity 的展示映射，不增加另一套可竞争写入的权威。

**[结构已具备]** 组合 FK、唯一索引和 revision 触发器支持归属约束，不足以单独保证“每条业务事实都有链接”或 CAS。未来原生事实、归属链接、当前指针与 revision 必须同事务写入；本阶段禁止强制旧 Writer 写新表。

源码依据：[S01–S11、S56](source-index.md)；Expand SQL：`backend/app/storage/migrations/workflow_expand_business_001.sql:23` 起。

## 2. 状态与活动定义

### 2.1 Control Status

| 标记 | 状态 | 准确定义与边界 |
|---|---|---|
| 现有 | CREATED | Session 已保存，真实准备未完成 |
| 现有 | PREPARING | 旧准备路径兼容值；不能当作 native 新流程入口 |
| 现有 | PROFILING | 正在解析文件并计算确定性画像 |
| 现有 | PARSING_INTENT | 理解目标和约束；可能退出到等待澄清 |
| 现有 | PLANNING | 基于真实意图、画像和能力提出受控计划 |
| 现有 | VALIDATING | 对候选计划做确定性校验并准备保存 |
| 现有 | WAITING_FOR_CLARIFICATION | 用户必须补充阻断信息；不调 Planner |
| 现有 | AWAITING_APPROVAL | 计划已保存，待审核；可能含不可执行任务或阻断 |
| 现有 | APPROVED | 保存了当前有效批准；不表示 Execution 已开始 |
| 现有 | RUNNING | Engine 执行已 claim；不是 Reporting 状态 |
| 现有 | COMPLETED | 当前真实主链路 Engine 以 success 或 partial_success 结束；**不表示报告已交付** |
| 现有 | FAILED | 准备失败或 Engine 无成功任务等控制失败；阶段与错误决定恢复资格 |
| 目标 | COMPLETED 的授权 | Engine 之后保持此控制状态；允许受控报告命令，不因此重新允许计划修订或 Engine 执行 |

**[现有]** COMPLETED 的解释限定真实 Engine 主链路；旧 Mock 流程也使用该枚举，必须按 workflow_kind 区分，不能把 Mock 完成投影成真实业务成功。

### 2.2 三个不可混用的结果维度

| 标记 | 维度 | 合法值/来源 | 说明 |
|---|---|---|---|
| 目标 | execution_outcome | null/running/success/partial_success/failed | 来自 Execution 的真实阶段/结果；合同名称对应当前 business_lifecycle.execution_status，暂不改 API |
| 目标 | delivery_status | delivered/not_delivered/unknown | 来自有效 generation + report + 提交/归属验证；对应当前 report_delivery，暂不改 API |
| 现有 | business_lifecycle | created/running/waiting_input/waiting_approval/succeeded/partially_succeeded/failed/interrupted/unknown | 保留枚举；当前实现的组合规则与 V1.1 目标差异见第 5 节 |
| 现有 | report_generation_status | queued/generating/completed/failed/unavailable 或 null | 当前 generation；completed 允许 report_status=partial |
| 现有 | report_status | complete/partial/unavailable 或 null | 报告生成质量，不是整体任务结果 |
| 现有 | goal_coverage | complete/partial/blocked 或 null | 业务目标覆盖，不是报告是否已存储 |
| 目标 | 已知任务损失 | execution_partial、execution_failed 及实际 tasks/errors | 一经确定，Reporting 不得清除或覆盖；不得只给用户一个“运行中”徽标隐藏失败 |

**[目标]** execution_outcome=null 只表示该投影未得到执行结果；只有必要引用完整且确认未启动才能解释为“尚未执行”。缺行、读取失败或冲突必须附 unknown/inconsistent，不以 null 推断没有失败。

### 2.3 完整 Activity 集合

| 标记 | activity | 触发事实 |
|---|---|---|
| 现有 | not_started | 刚创建 |
| 现有 | preparing | 旧 PREPARING 兼容 |
| 现有 | profiling | 画像处理中 |
| 现有 | parsing_intent | 意图处理中 |
| 现有 | planning | 规划处理中 |
| 现有 | validating | 保存计划前校验 |
| 现有 | clarification | 等待用户补充 |
| 现有 | review | 待审核 |
| 现有 | approved_not_started | 已批准但未 claim |
| 现有 | executing | Execution running |
| 现有 | report_not_started | 已有 ExecutionResult，尚无 generation |
| 现有 | report_queued | generation queued |
| 现有 | reporting | generation generating |
| 现有 | finished | 当前没有待运行的已接纳活动 |
| 现有 | unknown | 必要事实不足或冲突 |

**[目标]** activity 是“正在做什么”，不是“做得是否成功”。`partially_succeeded + reporting` 合法；`finished` 不等于 succeeded。保留所有 Activity 值，V2 改进组合，不新加 Engine resume 活动。

### 2.4 采集与一致性

| 标记 | 维度 | 值与使用 |
|---|---|---|
| 现有 | collection.availability | available/not_collected/unavailable/unknown |
| 现有 | collection.integrity | incomplete/unknown；不能声称已证明端到端完整采集 |
| 现有 | consistency.status | consistent/unknown/inconsistent；跨库快照 non_atomic |
| 目标 | 异常优先级 | 必要业务关联冲突优先 unknown/inconsistent；仅 Trace 缺失不改真实业务成功 |

源码依据：[S02–S07、S28–S31](source-index.md)。

## 3. Control 与报告状态转换矩阵

### 3.1 现有完整 Control 矩阵

以下由当前 ALLOWED 提取；只代表 transition() 的边集合。真实服务有直接赋值及不同守卫，不能把此表当作命令授权。

| 标记 | 前态 | 允许后态 |
|---|---|---|
| 现有 | CREATED | FAILED、PREPARING、PROFILING |
| 现有 | PROFILING | FAILED、PARSING_INTENT |
| 现有 | PARSING_INTENT | FAILED、PLANNING、WAITING_FOR_CLARIFICATION |
| 现有 | PLANNING | FAILED、VALIDATING |
| 现有 | VALIDATING | AWAITING_APPROVAL、FAILED |
| 现有 | PREPARING | AWAITING_APPROVAL、FAILED、WAITING_FOR_CLARIFICATION |
| 现有 | WAITING_FOR_CLARIFICATION | PARSING_INTENT、PREPARING |
| 现有 | AWAITING_APPROVAL | APPROVED、AWAITING_APPROVAL |
| 现有 | APPROVED | AWAITING_APPROVAL、RUNNING |
| 现有 | RUNNING | COMPLETED、FAILED |
| 现有 | COMPLETED | AWAITING_APPROVAL |
| 现有 | FAILED | AWAITING_APPROVAL、PARSING_INTENT、PLANNING、PROFILING、VALIDATING |

### 3.2 native V1.1 目标 Control 矩阵

| 标记 | 前态 | 允许后态 |
|---|---|---|
| 目标 | CREATED | PROFILING、FAILED |
| 目标 | PREPARING | 无跨状态出口 |
| 目标 | PROFILING | PARSING_INTENT、FAILED |
| 目标 | PARSING_INTENT | WAITING_FOR_CLARIFICATION、PLANNING、FAILED |
| 目标 | PLANNING | VALIDATING、FAILED |
| 目标 | VALIDATING | AWAITING_APPROVAL、FAILED |
| 目标 | WAITING_FOR_CLARIFICATION | PARSING_INTENT |
| 目标 | AWAITING_APPROVAL | AWAITING_APPROVAL、APPROVED |
| 目标 | APPROVED | AWAITING_APPROVAL、RUNNING |
| 目标 | RUNNING | COMPLETED、FAILED |
| 目标 | COMPLETED | 无跨状态出口 |
| 目标 | FAILED | PROFILING、PARSING_INTENT、PLANNING、VALIDATING |

**[目标]** PREPARING 不接纳 native 命令，只保留枚举/历史读取。COMPLETED 没有新的跨 Control 状态出口；报告命令改变 ReportGeneration 而非把控制状态改为 RUNNING。FAILED 重试边仅限尚无已保存审核计划或执行的准备失败。

**[目标]** RUNNING 的任务进度命令不改变 control_status，只提交进度和 revision；AWAITING_APPROVAL 的自环必须伴随合法新版本/验证，不接受空操作重置版本。

### 3.3 ReportGeneration 转换矩阵

| 标记 | 前态 | 命令/事件 | 后态 | 持久证据/特殊说明 |
|---|---|---|---|---|
| 现有 | 不存在 | queue | queued，attempt=1 | execution 绑定、queued_at；不允许传旧 expected_attempt |
| 现有 | queued | start | generating | 精确 attempt，重复 start 返回 None |
| 现有 | queued/generating | finish(report) | completed 或 unavailable | 报告与 generation 同事务，accepted=True |
| 现有 | queued/generating | finish(error) | failed | 精确 attempt，错误持久化 |
| 现有 | failed | queue(expected_attempt) | queued，attempt+1 | 期望 attempt 精确相符；重试新调用记录 |
| 现有 | queued/generating | recover_interrupted | failed | REPORT_PROCESS_INTERRUPTED，不自动重新调用模型 |
| 现有 | 任意已有 | queue 不传 expected_attempt | 不变 | 返回已有记录 fresh=False，不表示重试成功 |
| 现有 | completed/unavailable | queue 即使传 expected_attempt | 不变 | 当前也返回 fresh=False，**不是获准 Retry** |
| 现有 | 旧 attempt/终态 | finish | 不变 | accepted=False，禁止 Trace complete |
| 目标 | generating | 正常交付提交 | completed/unavailable | 新 Worker 路径必须先成功 start；对 queued 直接成功 finish 的现有兼容能力不作 native 许可 |
| 目标 | unavailable | Retry/Resume | 禁止 | 无重试按钮，无重新发模型；原报告/说明可查询 |

**[目标]** 报告业务层严格区分初次生成、幂等查询、失败重试。所有重试以旧 generation.failed 为前置；completed（含 partial 报告）与 unavailable 都不是 Retry 源状态。

源码依据：[S08–S11、S38–S42](source-index.md)。

## 4. 命令授权矩阵

### 4.1 native 业务命令、守卫与提交证据

下表每个命令都映射到明确的状态 owner；控制状态不变的报告命令仍有合法 generation 转换。所有来源还需第 8 节 fencing。条件不足时拒绝，不“先跑再补链接”。

| 标记 | 命令ID / 命令 | 状态owner | 前态 / 后态 | 资格 | 必需持久证据 |
|---|---|---|---|---|---|
| 目标 | C01 开始准备 | control | CREATED / PROFILING | 固定输入、当前 revision 和新活动令牌 | 接纳命令、输入绑定和状态同事务 |
| 目标 | C02 画像完成 | control | PROFILING / PARSING_INTENT | 画像文件版本/hash/选项一致，当前活动令牌 | DatasetProfile+固定DatasetRef+状态检查点 |
| 目标 | C03 意图可规划 | control | PARSING_INTENT / PLANNING | 真实合法 Intent.next_action=proceed | 保存意图、parse标识与输入绑定 |
| 目标 | C04 意图需澄清 | control | PARSING_INTENT / WAITING_FOR_CLARIFICATION | 合法 Intent.next_action=clarify | 意图与澄清问题已保存 |
| 目标 | C05 补充澄清 | control | WAITING_FOR_CLARIFICATION / PARSING_INTENT | 同目标回答、revision；不复用旧Planner检查点 | 消息、答案集、新活动令牌、状态 |
| 目标 | C06 Planner回调 | control | PLANNING / VALIDATING | 意图快照/参数/活动令牌未替换 | 真实候选及来源保存 |
| 目标 | C07 保存验证计划 | control | VALIDATING / AWAITING_APPROVAL | 候选精确匹配；保留F0/P0；版本不可变 | PlanVersion+归属+validation+当前指针 |
| 目标 | C08 待审批删除任务 | control | AWAITING_APPROVAL / AWAITING_APPROVAL | 精确版本；无执行；删除任务合法 | 新PlanVersion+验证；清有效批准；历史保留 |
| 目标 | C09 已批准但未执行修订 | control | APPROVED / AWAITING_APPROVAL | 无已claim执行/报告；明确撤销当前批准引用 | 新版本+验证；原批准仅失去当前资格 |
| 目标 | C10 批准当前计划 | control | AWAITING_APPROVAL / APPROVED | 完整批准资格；精确版本/约束审计/告警确认 | 批准快照+归属链接+当前批准+审计 |
| 目标 | C11 执行claim | control | APPROVED / RUNNING | 有效批准；幂等请求；加载版本未变化 | 新Execution+批准快照+归属+当前执行+新活动令牌 |
| 目标 | C12 Engine成功结束 | control | RUNNING / COMPLETED | 当前execution、令牌、revision；全部任务结果已存 | ExecutionResult.success+控制检查点 |
| 目标 | C13 Engine部分成功结束 | control | RUNNING / COMPLETED | 当前execution；真实任务失败/skipped不可丢 | ExecutionResult.partial_success+控制检查点 |
| 目标 | C14 Engine全部失败结束 | control | RUNNING / FAILED | 当前execution；没有成功任务 | ExecutionResult.failed+错误+控制检查点 |
| 目标 | C15-CREATED 准备失败/中断收敛 | control | CREATED / FAILED | 仅当前准备作业；保存错误；recover需旧worker隔离 | 失败阶段+错误+有效检查点 |
| 目标 | C15-PROFILING 准备失败/中断收敛 | control | PROFILING / FAILED | 仅当前准备作业；保存错误；recover需旧worker隔离 | 失败阶段+错误+有效检查点 |
| 目标 | C15-PARSING_INTENT 准备失败/中断收敛 | control | PARSING_INTENT / FAILED | 仅当前准备作业；保存错误；recover需旧worker隔离 | 失败阶段+错误+有效检查点 |
| 目标 | C15-PLANNING 准备失败/中断收敛 | control | PLANNING / FAILED | 仅当前准备作业；保存错误；recover需旧worker隔离 | 失败阶段+错误+有效检查点 |
| 目标 | C15-VALIDATING 准备失败/中断收敛 | control | VALIDATING / FAILED | 仅当前准备作业；保存错误；recover需旧worker隔离 | 失败阶段+错误+有效检查点 |
| 目标 | C16-PROFILING 准备显式Retry | control | FAILED / PROFILING | 只限retryable准备失败；无已保存审核计划/执行；选择有效检查点 | 新活动令牌+revision+重试接纳；保留旧失败 |
| 目标 | C16-PARSING_INTENT 准备显式Retry | control | FAILED / PARSING_INTENT | 只限retryable准备失败；无已保存审核计划/执行；选择有效检查点 | 新活动令牌+revision+重试接纳；保留旧失败 |
| 目标 | C16-PLANNING 准备显式Retry | control | FAILED / PLANNING | 只限retryable准备失败；无已保存审核计划/执行；选择有效检查点 | 新活动令牌+revision+重试接纳；保留旧失败 |
| 目标 | C16-VALIDATING 准备显式Retry | control | FAILED / VALIDATING | 只限retryable准备失败；无已保存审核计划/执行；选择有效检查点 | 新活动令牌+revision+重试接纳；保留旧失败 |
| 目标 | C17 首次报告排队 | generation | 不存在 / queued | 精确已结束Execution与批准；全失败仅诊断，不生成成功事实 | generation attempt=1+当前作用域/报告令牌 |
| 目标 | C18 报告启动 | generation | queued / generating | 当前attempt/报告令牌；重复start不重复调用 | generation.started_at+作业检查点 |
| 目标 | C19 提交可交付报告 | generation | generating / completed | 合法证据、覆盖与有效当前分支；accepted=True | 报告+归属+generation.report_id同事务 |
| 目标 | C20 提交不可生成记录 | generation | generating / unavailable | 无有效证据或无有效核心洞察；不得complete | unavailable报告记录+原因+generation同事务 |
| 目标 | C21-queued 报告失败/Recover | generation | queued / failed | 当前attempt；Recover须确认旧worker退出 | 失败记录+错误；Execution不变 |
| 目标 | C21-generating 报告失败/Recover | generation | generating / failed | 当前attempt；Recover须确认旧worker退出 | 失败记录+错误；Execution不变 |
| 目标 | C22 报告显式Retry | generation | failed / queued | expected_attempt匹配、当前分支有效且未交付；已知Root只能running/partial/failed/interrupted，缺Trace不阻断 | attempt+1+新报告活动令牌+排队检查点 |
| 目标 | C23 提交任务进度 | control | RUNNING / RUNNING | 当前execution/task、revision与活动令牌；不重复任务结果 | 任务状态+完整结果/引用同事务 |
| 目标 | C24 创建独立新目标 | creation | 不存在 / CREATED | 新创建键；同Session消息文件授权；原Workflow不变 | Workflow+origin/root_id/幂等键同事务 |

**[目标]** 进入 FAILED 的准备错误必须保存阶段和有效检查点；不可只存一个通用失败状态。生成 plan_version_id、approval_id、execution_id 等由各自事务分配，不要求提前给未来实体造 ID。

### 4.2 Engine 结束后的授权（P0）

适用条件：真实已保存的 Execution，精确固定批准和当前 Workflow 分支，Root 非 complete；有成功任务时 control=COMPLETED，无成功任务时 control=FAILED。以下“可”还受 fencing 和 generation 守卫约束。

| 标记 | 报告事实 | 查询执行/报告 | 初次生成 | 失败Retry | Worker继续 | 改计划/再跑Engine |
|---|---|---|---|---|---|---|
| 目标 | 无 generation | 可查执行；无报告即明确未交付 | 可；创建 queued | 不可，无失败attempt | 未排队不可调用模型 | 禁止；新需求新Workflow |
| 目标 | queued | 可 | 仅幂等返回，不重复派发 | 禁止 | 仅合法 queued→generating 的当前Worker | 禁止 |
| 目标 | generating | 可 | 仅幂等返回 | 禁止 | 仅当前Worker可提交/失败 | 禁止 |
| 目标 | failed | 可查执行及错误 | 不冒充首次；必须显式Retry | 可，expected_attempt匹配，Root/分支仍合法 | 旧Worker不得继续 | 禁止 |
| 目标 | unavailable | 可查说明及原执行；不声称成功交付 | 不可再生成，返回已有不等于启动 | 禁止 | 禁止 | 禁止 |
| 目标 | completed，部分报告已交付 | 可预览/下载 | 不可重生成；原记录可查 | 禁止 | 禁止 | 禁止 |
| 目标 | completed，完整报告交付且Root.complete | 可预览/下载 | 禁止变更 | 禁止 | 禁止 | 禁止；新Workflow才可新分析 |
| 现有 | 任意上述阶段 | 精确execution/report查询可用 | API可返回已有或创建；fresh=False不派发 | 仅failed可真正重排 | attempt守卫 | legacy HITL仍可能修订；本轮不删除 |

**[目标]** 全失败 Execution 可以生成真实的失败/无证据诊断说明，但不得生成成功事实或可交付的成功分析报告。Reporting 活动也不能把 execution_outcome=failed 显示为运行成功；组合规则见第 5 节。

**[目标]** 执行请求的同键重放是查询/去重，不是新增执行授权。只有当精确旧请求与原记录相同才返回已有结果；新执行必须有 APPROVED 当前资格。Root.complete 下允许读旧结果，不得借重放接口追加报告或新事件来重开 Root。

### 4.3 HITL 批准资格

| 标记 | 规则 |
|---|---|
| 现有 | current_guard 验证当前保存计划，expected_revision 与 Dataset/validation 必须一致，重新 Validator 必须匹配保存结果 |
| 现有 | next_action 必须proceed；批准服务拒绝clarify/defer；ConstraintAuditor 必须all_verified；blocked/无可执行任务拒绝；限制告警必须完整确认 |
| 现有 | approve_v1 没有独立 `status == AWAITING_APPROVAL` 检查，主要依赖current_guard/revision_guard/既有批准与版本检查；不能宣称所有入口已有完整状态策略 |
| 目标 | native批准必须显式要求AWAITING_APPROVAL，且Workflow/Root未结束、无活动执行；前端按钮不能代替服务端资格 |
| 现有 | revise_v1 阻止RUNNING/PREPARING，但未检查活动ReportGeneration；可在Session.COMPLETED后删除任务并重校验 |
| 目标 | native删除/修订只允许执行前AWAITING_APPROVAL或APPROVED，且没有已claim执行/报告；不受legacy宽守卫授权 |

源码依据：[S21–S27、S54–S55](source-index.md)。

## 5. Engine / Report 组合结果（P0）

### 5.1 统一判定顺序

| 标记 | 优先级 | 规则 |
|---|---|---|
| 目标 | 1 | 精确核对当前Workflow、数据/计划/批准/执行/report与commit引用。读取缺失用unknown/unknown，明确矛盾用unknown/inconsistent；不选择最近成功记录 |
| 目标 | 2 | 固定execution_outcome、任务状态与中断/错误。Reporting变化不能清除其已知失败 |
| 目标 | 3 | 交付必须有实际提交报告与generation.report_id/attempt/audit匹配；unavailable文档虽已存储，delivery_status仍not_delivered |
| 目标 | 4 | 有success/partial_success但无报告交付时：报告进行中仍保留partial事实；失败/不可生成派生partially_succeeded |
| 目标 | 5 | 只有Engine.success、report.complete、plan与goal覆盖都complete且真实delivered，才可succeeded |
| 目标 | 6 | 完全无成功任务的failed不能被报告修复为成功；诊断生成中保持failed；若出现有效成功报告与此冲突则unknown/inconsistent |
| 目标 | 7 | 中断详情独立保留；Engine Recover有成功任务时保留partially_succeeded，无成功且无报告活动时可interrupted；不压掉任务结果 |

**[目标]** plan coverage=partial、report goal coverage=complete 是矛盾，不是成功。goal覆盖blocked而报告有部分有效证据可以是部分交付；无任何有效核心洞察不得report.complete。报告可读性不等于满足完整目标。

### 5.2 21 个固定组合

表格默认：业务记录一致、当前分支固定、没有额外process interruption；完整交付同时满足plan/goal覆盖complete。delivered_partial包括report.partial，覆盖不完整的扩展情况另见验收样例。failed+delivered是应识别的非法组合，保留为拒绝/一致性用例，不授权生成这种结果。

| 标记/ID | execution_outcome | 报告阶段 | delivery_status | business_lifecycle | activity | consistency | reason_codes |
|---|---|---|---|---|---|---|---|
| 目标/ER01 | success | absent | not_delivered | running | report_not_started | consistent | report_not_started、report_not_delivered |
| 目标/ER02 | success | queued | not_delivered | running | report_queued | consistent | report_not_delivered |
| 目标/ER03 | success | generating | not_delivered | running | reporting | consistent | report_not_delivered |
| 目标/ER04 | success | failed | not_delivered | partially_succeeded | finished | consistent | report_failed、report_not_delivered |
| 目标/ER05 | success | unavailable | not_delivered | partially_succeeded | finished | consistent | report_unavailable、report_not_delivered |
| 目标/ER06 | success | delivered_complete | delivered | succeeded | finished | consistent | 无 |
| 目标/ER07 | success | delivered_partial | delivered | partially_succeeded | finished | consistent | report_partial |
| 目标/ER08 | partial_success | absent | not_delivered | partially_succeeded | report_not_started | consistent | execution_partial、report_not_started、report_not_delivered |
| 目标/ER09 | partial_success | queued | not_delivered | partially_succeeded | report_queued | consistent | execution_partial、report_not_delivered |
| 目标/ER10 | partial_success | generating | not_delivered | partially_succeeded | reporting | consistent | execution_partial、report_not_delivered |
| 目标/ER11 | partial_success | failed | not_delivered | partially_succeeded | finished | consistent | execution_partial、report_failed、report_not_delivered |
| 目标/ER12 | partial_success | unavailable | not_delivered | partially_succeeded | finished | consistent | execution_partial、report_unavailable、report_not_delivered |
| 目标/ER13 | partial_success | delivered_complete | delivered | partially_succeeded | finished | consistent | execution_partial |
| 目标/ER14 | partial_success | delivered_partial | delivered | partially_succeeded | finished | consistent | execution_partial、report_partial |
| 目标/ER15 | failed | absent | not_delivered | failed | report_not_started | consistent | execution_failed、report_not_started、report_not_delivered |
| 目标/ER16 | failed | queued | not_delivered | failed | report_queued | consistent | execution_failed、report_not_delivered |
| 目标/ER17 | failed | generating | not_delivered | failed | reporting | consistent | execution_failed、report_not_delivered |
| 目标/ER18 | failed | failed | not_delivered | failed | finished | consistent | execution_failed、report_failed、report_not_delivered |
| 目标/ER19 | failed | unavailable | not_delivered | failed | finished | consistent | execution_failed、report_unavailable、report_not_delivered |
| 目标/ER20 | failed | delivered_complete | unknown | unknown | unknown | inconsistent | execution_failed、business_state_conflict |
| 目标/ER21 | failed | delivered_partial | unknown | unknown | unknown | inconsistent | execution_failed、report_partial、business_state_conflict |

**[目标]** Engine partial_success + Report queued/generating 的business_lifecycle固定为partially_succeeded，activity分别report_queued/reporting。execution_partial始终存在；这是V2待实现的规则。

**[现有]** 当前aggregate会在generation.queued/generating时写business_lifecycle=running，虽保留execution_status和execution_partial，但单看status会掩盖已发生损失。当前也可能在Engine.failed的诊断排队时投影running。V1.1不修改该API，冻结的目标不冒充已修复。

**[目标]** Report Retry可以使Engine.success + 原report.failed的投影从partially_succeeded变为running（正在补齐交付）；原Report错误仍在历史Run/Call可查。Engine.partial_success下同一Retry仍是partially_succeeded，不能回到无失败的running。

### 5.3 非结果阶段与异常覆盖

| 标记 | 输入事实 | lifecycle/activity | 保留内容 |
|---|---|---|---|
| 目标 | CREATED且无执行 | created/not_started | 未开始不是失败 |
| 目标 | 准备节点合法运行 | running/对应活动 | 不伪造Span |
| 目标 | Intent需要澄清 | waiting_input/clarification | clarification_required；不得规划 |
| 目标 | 当前计划待审 | waiting_approval/review | F0、coverage与审批阻断 |
| 目标 | APPROVED未执行 | running/approved_not_started | 有效批准，不代表已计算 |
| 目标 | Execution.running | running/executing | 进行中的任务错误/进度；不提前改最终outcome |
| 目标 | 仅COMPLETED，无可核实ExecutionResult | unknown/unknown | record_missing，绝不succeeded |
| 目标 | Engine中断Recover为partial_success，无generation | partially_succeeded/report_not_started | execution_partial+process_interrupted，不覆盖为单一interrupted |
| 目标 | Engine中断Recover为failed，无generation | interrupted/finished | execution_outcome=failed、execution_failed+process_interrupted |
| 目标 | 准备中断 | interrupted/finished | PROCESS_INTERRUPTED与检查点；没有自动Resume |
| 目标 | 仅Trace缺失，业务提交完整 | 按真实业务结果 | trace_not_collected/unavailable；不伪造Span |
| 现有 | Trace与业务绑定冲突 | 当前aggregate可unknown/inconsistent | 本轮不放宽Read Model v1；V2保留审计提示与保守规则 |

源码依据：[S28–S31、S33–S42](source-index.md)。

## 6. 完成后修订与 Legacy 边界（P0）

| 标记 | 情况 | 契约 |
|---|---|---|
| 目标 | Root.complete | 终态，无running出口；只读查询。新分析目标创建新Workflow，不复用Root |
| 目标 | control.COMPLETED但报告未交付 | 只是Engine结束；可补报告，不可修订计划或启动第二次Engine |
| 目标 | Root.partial且已部分交付 | 不通过“Retry”改写已提交报告；当前generation.completed不支持重试；新需求新Workflow |
| 目标 | Root.partial因报告failed且仍当前分支 | 允许显式报告Retry后Root.running；不更改计划/批准/执行；business结果按组合规则保留partial |
| 现有 | Session.COMPLETED→AWAITING_APPROVAL | transition.ALLOWED保留；真实revise_v1可新建删除任务版本，清当前批准，历史报告/执行保留 |
| 现有 | Session.FAILED后HITL修订 | 有当前审核计划且守卫满足时仍可能合法；不等于原Engine断点恢复 |
| 目标 | native已结束Workflow的未来修订 | V1.1不授权。未来必须另行定义分支身份、PlanVersion、批准、执行、历史报告保留、Root终态规则，再出新契约 |

**[目标]** 不删除legacy转换、不重写历史Session/Manifest、不把历史准备Root扩展成完整Root。未来Switch必须显式记录路由与policy适用域，禁止按“创建时间新/旧”猜测。旧客户端对多Workflow有歧义时不得静默选Session最新结果。

**[目标]** Legacy兼容并不保证native新限制已经在旧API生效。上线Policy前需要明确拦截范围和回滚：保留legacy读写行为时不应错误宣称已对其施加native完成封闭策略。本阶段两套规则显式并存，不实际切换。

## 7. Recover / Retry / Resume 矩阵（P0）

| 标记 | 操作 | 定义与资格 | 状态变化与保留 | 禁止 |
|---|---|---|---|---|
| 现有 | Recover准备 | 单进程启动确认旧进程已结束后，将遗留准备任务收敛到已知失败 | 保存PROCESS_INTERRUPTED、有效检查点，控制FAILED；不自动调LLM | 不把恢复扫描说成继续运行 |
| 现有 | Recover Engine | 扫描running执行，用已存progress/result结束它 | 已完成任务保留，未完成任务skipped/EXECUTION_INTERRUPTED；outcome重新按真实成功数计算 | 不从最后一个step或task继续执行 |
| 现有 | Recover Report | queued/generating在启动时改failed | REPORT_PROCESS_INTERRUPTED，Execution不变；等显式报告Retry | 不自动生成新报告、不覆盖旧已提交报告 |
| 现有 | Recover Trace/Call | 原queued/running Run/Span与running Call标interrupted | 历史记录保留，采集完整性降级 | 不以Trace中断覆盖已成功业务 |
| 目标 | Recover多Worker | 先确定实例死亡/隔离旧Worker，再事务内按fencing收敛 | 保留原身份；revoke/rotate活动令牌，旧回调拒绝 | 没有lease/实例隔离时不声称多Worker可恢复 |
| 现有 | Retry准备 | 显式请求、retryable、没有review_plan和engine_execution_ids，revision相符 | 有候选至VALIDATING；否则有效Intent至PLANNING；有Dataset至PARSING_INTENT；否则PROFILING | 不自动批准，不跳过校验 |
| 现有 | Retry模型调用 | 节点内有限次数，配置超时预算 | 每次调用新Call ID和请求快照；保留失败Call | 不引入新Attempt实体，不无限修复 |
| 现有 | Retry报告 | 仅generation.failed，expected_attempt精确 | queued且attempt+1，之后start；保留执行结果 | completed/unavailable不可Retry |
| 目标 | Retry报告 | 同上，另验Workflow/当前分支/Root与活动令牌 | 新报告执行活动；旧Report Run保留；目标新Span直接挂Root | 不从complete重开、不改Engine |
| 现有 | 重放执行请求 | 同execution_request_id且完整参数相同 | 运行中返回冲突/原ID，结束返回原结果 | 不是重算，不构造新的Execution |
| 目标 | Retry已结束Engine | V1.1不提供原Workflow再次计算命令 | 新分析请求走新Workflow/新审批；保留原执行 | 不借新request ID绕过Root完成边界 |
| 目标 | Resume等待澄清 | 同目标回答、合法revision，新解析活动 | WAITING_FOR_CLARIFICATION→PARSING_INTENT | 不称为Engine断点Resume |
| 目标 | Resume等待审核 | 通过真实批准命令继续，不能跳审 | AWAITING_APPROVAL→APPROVED，另行claim→RUNNING | 不自动批准 |
| 目标 | Resume Engine task/step | **不支持** | 无合法命令和状态边 | 不承诺从task/step检查点续跑 |
| 目标 | Resume Report候选/模型token | **不支持** | 只有失败后的完整Report Retry | 不声称候选级或流式续传已实现 |

**[目标]** Recover是“根据已提交事实结束失去执行者的活动”；Retry是“显式接纳新执行活动”；Resume是“从业务等待点继续”。三者不共用一个无条件“继续”按钮。recover触发的结果保存不是新的任务级执行。

**[现有]** 启动恢复顺序为Engine、Workflow、Report、Trace、Registry；实现依赖本地单进程。旧Worker仍运行时此扫描并不安全，V1.1将其作为Switch阻断项，而非宣称已解决分布式接管。

## 8. Workflow Fencing（P0）

### 8.1 通用规则

| 标记 | ID | 规则 |
|---|---|---|
| 目标 | F01 | 异步作业在接纳时捕获不可变session_id、workflow_id、input/branch摘要与活动令牌；业务回调不得按Session“最新计划”重新选目标 |
| 目标 | F02 | 同一业务库事务内核对owner、当前分支、允许状态、expected_workflow_revision、active_execution_key、精确业务引用和幂等请求；全部通过才写事实+归属+指针+revision |
| 目标 | F03 | active_execution_key是作业隔离令牌，不是Attempt实体。每次显式Retry/阶段新作业分配新key；旧Worker不允许读取新key后重放旧结果 |
| 目标 | F04 | revision乐观并发与active key必须同时满足；同revision旧key仍拒绝，同key旧revision也拒绝。Root observation_revision独立，不代替业务守卫 |
| 目标 | F05 | 一个Workflow内变更控制/分支的命令序列化。作业只在自己的成功检查点提交后取得新revision，继续下一步；不因CAS失败自动换取最新revision重放 |
| 目标 | F06 | Session会话消息与其他Workflow更新不推进本Workflow revision；本Workflow报告queue/start等合法提交要返回更新后的revision给当前作业 |
| 目标 | F07 | 报告引用Execution保存的批准快照，不从当前Session重建历史审批；但是否可作为当前分支交付必须核对Workflow.current_execution_id与对应批准/计划 |
| 目标 | F08 | 写入失败/迟到作业可留受控诊断，但不得更新当前Workflow状态/指针、插入可见成功报告、把Root标complete。历史结果只可通过受支持归档机制保留，本轮不新增该写能力 |
| 现有 | F09 | Session mutate、准备guard有revision校验；Root update_run有observation_revision CAS；Report finish有execution+attempt+状态accepted屏障 |
| 结构已具备 | F10 | active_execution_key字段和组合FK存在；workflow_revision_guard只保证+1，不自动提供WHERE expected_revision CAS或全回调fencing |

### 8.2 字段在何时必须存在

下表为**目标**。`M`表示必须存在并验证，`O`表示仅已存在才校验，`N`表示此阶段不应强求未来实体ID。所有阶段都必须验证业务状态/命令资格；root_run_id是业务预留ID，实际Trace/Span行不强求存在。

| 标记 | 阶段 | 归属/并发/幂等 | 输入/分支必需 | 后续实体 |
|---|---|---|---|---|
| 目标 | 创建 | M session_id、creation_request_id、payload_hash；workflow_id/root_run_id在事务内分配 | M同Session origin_message、授权input_file、目标；parent若有同Session | N dataset_version/plan/approval/execution/report |
| 目标 | Profiling接纳/回调 | M session/workflow/root预留、expected_revision、active key、operation/request标识 | M input_file/content_hash、profile_options摘要；回调profile必须对应这些输入 | N plan/approval/execution；dataset_id/version在成功回调形成并固定 |
| 目标 | Intent接纳/回调/澄清 | M owner/revision/key/operation；用户补充有独立命令键或受revision保护的稳定请求 | M固定DatasetRef/profile hash、目标/答案集hash；合法Prompt请求引用 | N plan/approval/execution；parse_id作为结果/作业引用，不造未来ID |
| 目标 | Planner接纳/回调 | M owner/revision/key/operation | M DatasetRef、Intent快照hash/parse绑定、capability版本、Prompt请求绑定 | N 已提交plan_version_id；草案plan_id/version若已生成则O且校验，不把草案当已保存Plan |
| 目标 | Validation/保存计划 | M owner/revision/key、保存命令键 | M候选hash、Dataset、Intent/能力、输出validation结果 | plan_version_id在事务内分配；N approval/execution |
| 目标 | HITL批准/修订 | M owner/revision、审批/修订请求键；无冲突活动作业 | M current_plan_version_id、plan_id/version、validation、Dataset、告警/约束审计 | 新approval_id在批准事务分配；修订不得要求未来Execution |
| 目标 | Engine claim | M owner/revision、execution_request_id；新execution key在claim事务分配 | M currentPlan、有效Approval、Dataset/validation精确匹配 | execution_id在事务分配；N report_id/attempt |
| 目标 | Engine任务/finish/Recover | M owner/revision/key、execution_id/request_id、当前作业绑定 | M当前Plan/Approval/Dataset、合法task/step、完整结果引用；重复task不得覆盖 | N report字段；Recover需原Worker隔离及新恢复授权，不继续计算 |
| 目标 | Report queue/Retry | M owner/revision、当前Execution、请求/期望attempt；新report key在事务分配 | M execution中批准/Plan/Dataset快照；真实finished结果；Retry旧generation.failed | attempt在事务分配；N未提交report_id |
| 目标 | Report start/生成/校验/组装 | M owner/revision/report key、execution_id、当前attempt/operation | M原批准/Plan/Dataset、结果hash、Evidence/Schema/Prompt引用；不得串范围 | report_id可在组装时分配，不以“已有ID”证明已提交 |
| 目标 | Report persistence | M上述owner/revision/key/execution/attempt、提交幂等依据 | M完整Report、有效Evidence/coverage、同分支精确引用、预定report_id | 原子提交Report+链接+generation；accepted=True后才成功观测 |
| 目标 | Trace写入 | M预留root、实际run/span owner和observation CAS（可写时） | 原始manifest不可变；采集缺失只记gap | 不要求Trace成功后才允许业务提交 |

**[目标]** Evidence/Chart/Fact/Assembler虽然可能不各自写业务表，但其输出影响最终提交；必须继承同一个报告作业上下文，最终报告事务再次验证，不能只在首次发模型前验一次。每次LLM重试保留独立CallRecord，不能靠重新拼Prompt猜历史请求。

**[目标]** plan/approval/execution/report关系不可由同名字段、时间相近或最新成功记录补全。各阶段幂等命令键的最终API字段名及存储位置须由Writer设计评审确定；本稿只规定必需语义，不谎称当前所有请求已带这些字段。

### 8.3 四类旧回调的拒绝条件

| 标记 | 回调 | 任一满足即拒绝业务写入 | 保留与错误语义 |
|---|---|---|---|
| 目标 | 旧Worker | 实例已被隔离；活动key改变；revision不匹配；owner/状态/route不符 | 受控stale诊断，不取得新token，不宣称当前节点失败/成功 |
| 目标 | 旧Planner | Intent/答案集/Dataset/能力输入改变；operation/key/revision不符；计划已保存或非PLANNING | 不保存旧候选、不覆盖新计划；源Call保留 |
| 目标 | 旧Execution | execution_id不是current；批准/Plan/Dataset或key/revision改变；请求参数不匹配；执行已finished | 不改新Workflow或新结果；同请求结果只读重放，不重新finish |
| 目标 | 旧Report | attempt非当前；generation不在允许状态；current execution/plan/approval/owner/key不符；Root已complete | 不提交报告、accepted=False；不标当前Root成功；旧Trace按stale/interrupted |

**[现有]** Report旧attempt保护并不等于已有完整Workflow fencing。当前enqueue/generate以execution快照为准，可在Session后来修订计划时继续处理历史execution；当前finish也会更新Session generation镜像。未来必须同时保护“历史报告合法保存”和“当前分支交付”边界；V1.1目标选择不接受旧分支异步新提交，既有已提交历史报告仍可读。

**[目标]** stale拒绝码可以使用既有STALE_SESSION/REPORT_STALE_CALLBACK等兼容码，新增精确Workflow错误码须经接口评审；本稿不直接扩展现有错误枚举。

源码依据：[S12–S20、S30–S45](source-index.md)。

### 8.4 幂等范围与合法重放

| 标记 | 操作 | 幂等范围/载荷 | 重复处理 |
|---|---|---|---|
| 目标 | 创建 | (session_id,creation_request_id)+creation_payload_hash | 相同返回原Workflow；不同目标/文件/parent拒绝，不能新造Root |
| 目标 | 澄清/准备Retry/修订 | (workflow_id,command_request_id)+命令载荷、输入快照 | 事务内去重；目前原API只有revision的部分不声称已有命令日志 |
| 现有 | 批准 | (session_id,approval_request_id)+完整请求 | 相同且仍当前返回原批准；不同载荷或已superseded拒绝 |
| 目标 | native批准 | (workflow_id,approval_request_id)+精确plan/validation/dataset/告警 | 对应旧键迁移需兼容，不把不同Workflow的批准混用 |
| 现有 | 执行 | 全局execution_request_id+完整ExecutionRequest | running不重复，finished原结果；不同参数冲突 |
| 目标 | native执行 | 保留全局请求唯一性，并把workflow_id纳入绑定载荷 | 同键跨Workflow拒绝；不能缩小唯一作用域产生重复执行 |
| 现有 | 报告排队/Retry | execution_id；Retry另有expected_attempt | 同一execution仅当前generation；旧attempt或终态不得重新派发 |
| 目标 | 任务/报告提交 | execution+task身份或execution+report_attempt；附当前作业绑定 | 仅首次合法提交可改变事实；重复完成无新任务/报告，冲突拒绝 |
| 现有 | Root观察CAS | run_id+observation_revision | 旧令牌返回False；不视为业务成功 |

**[目标]** 幂等先返回“原结果”也必须核对作用域与请求载荷，不用幂等命中绕过归属。实际命令键持久化方案仍需Writer阶段评审；本稿不增加表或API参数。

## 9. Trace Root / Node Span（P1）

### 9.1 当前准备Root与目标完整Root

| 标记 | Root前态 | 允许后态 |
|---|---|---|
| 现有 | queued | running、interrupted |
| 现有 | running | running、waiting_input、waiting_approval、failed、interrupted |
| 现有 | waiting_input | running |
| 现有 | waiting_approval | 无 |
| 现有 | failed | running |
| 现有 | interrupted | running |
| 现有 | complete | 无 |
| 现有 | partial | 无 |
| 现有 | unavailable | 无 |
| 目标 | queued | running、interrupted |
| 目标 | running | running、waiting_input、waiting_approval、complete、partial、failed、interrupted |
| 目标 | waiting_input | running |
| 目标 | waiting_approval | running |
| 目标 | failed | running |
| 目标 | interrupted | running |
| 目标 | partial | running |
| 目标 | complete | 无 |
| 目标 | unavailable | 无 |

**[目标]** 表中允许边必须同时有业务命令接纳或提交证据：

| 标记 | Root变更 | 必需证据/限制 |
|---|---|---|
| 目标 | queued→running | 当前Workflow准备作业已接纳；owner/revision/key有效 |
| 目标 | running→waiting_input/waiting_approval | 意图澄清或计划审核检查点已提交 |
| 目标 | waiting_input→running | 合法澄清命令已提交，新准备key |
| 目标 | waiting_approval→running | 合法计划修订活动或有效批准后的Engine claim；不能用刷新页面触发 |
| 目标 | failed/interrupted→running | 业务允许的准备Retry、报告Retry，或对已结束Execution合法首次报告接纳；Recover本身不自动获准新计算 |
| 目标 | partial→running | **仅**当前generation.failed的显式Report Retry；已部分交付、unavailable或改计划均不获准 |
| 目标 | running→complete | 当前已提交报告complete、Engine.success、plan/goal覆盖complete；accepted=True |
| 目标 | running→partial | 有真实成功结果但报告失败/不可交付/部分交付；明确交付状态 |
| 目标 | running→failed | 无有效成功业务结果且当前处理已结束；已保存失败/无证据说明 |
| 目标 | unavailable枚举 | 保留读取，但native V1.1无写入边；Report unavailable时Root按有真实成功计算归partial、无成功归failed，避免同事实两个终态 |
| 目标 | running/queued→interrupted | 已确认作业异常停止且尚无可信终态收敛；后续Recover依业务事实判定，不反向猜成功 |
| 目标 | complete、unavailable | 无重开边；新目标新Workflow；unavailable不提供不支持的Retry |

**[目标]** Root.status是观察活动聚合，不能与business_lifecycle逐字等同。Engine.partial且Report正在跑时Root可running，业务必须partially_succeeded；Engine.failed的诊断尚在处理时Root可running，业务仍failed。Root不能提前在COMPLETED时complete；观察成功须晚于业务提交。

**[目标]** Root缺失不能阻断合法业务命令；上述Root边只在真实记录可写时适用。业务终态边界以已提交generation/report和当前分支为证据，不能要求先读取到Root。已知Root.complete却与report.failed等矛盾时，按一致性问题拒绝变更并调查，不把它当作合法重试来源，更不能把complete改回running。

**[目标]** Engine已结束但尚无generation时，完整Root通常仍running等待交付流程，不因control.COMPLETED结束为complete/partial。partial终态必须有已确认报告失败、不可交付或部分交付证据。若前次进程中断使Root为interrupted，合法首次报告可在新业务接纳后回running；Engine全失败Root已failed时，只能开启真实诊断说明的首次生成，不能重新执行Engine。Root.partial却没有任何报告阶段事实属于不一致，不凭空授予Retry。

### 9.2 当前独立Report Run与新Span

| 标记 | 对象 | 约束 |
|---|---|---|
| 现有 | Report Run | queued可queued/running/interrupted；running可running/complete/partial/failed/unavailable/interrupted；终态不可重开；Retry新Run并关联retry_of_run_id |
| 现有 | 准备Root | 完整转换见上表；waiting_approval没有当前执行/报告继续边；不改kind语义 |
| 目标 | 新Node Span | run_id必须等于Workflow.root_run_id，parent_span_id必须为空；所有节点直接归Root |
| 目标 | 技术子步骤 | 使用Event/属性，不创建Span的Span，不新增第三层节点 |
| 现有 | 历史嵌套Span | 通用Schema/SpanHandle仍支持嵌套；原样读，不能把历史记录删掉或改写成新父关系 |
| 现有 | Span状态 | running结束为complete/partial/failed/skipped/interrupted；终态不可重新打开 |
| 目标 | 节点重入 | 新span_id，同稳定node_key、新node_attempt；不独立建Attempt实体 |
| 现有 | LLM内部Retry | 独立Call记录，属于当前节点执行；不强行每次HTTP重试造一层Span |
| 目标 | skipped | 必须真实走skip分支且记原因；没有采集证据不补假skipped |

**[目标]** 旧Report Run保持独立历史来源；未来新Reporting采集直接挂Workflow Root。Switch后须用capture_scope/已保存关联区分，不将旧Report Run显示成Root下第三层节点。

### 9.3 故障语义（P1）

| 标记 | 故障 | 策略与可见结果 |
|---|---|---|
| 现有 | Trace写失败 | TraceRecorder受控日志、gaps/degraded；业务不失败；collection明确缺口 |
| 现有 | PromptRegistry.begin失败 | 请求快照未保存，HTTP不发；LLM_SNAPSHOT_UNAVAILABLE等明确错误 |
| 现有 | PromptRegistry.finish失败 | 模型可能已返回，但日志终结失败，结果不交业务；LLM_CAPTURE_FINALIZE_FAILED |
| 目标 | 两者展示 | 分别标“追踪缺口”和“模型请求记录失败”；不能统一包装为模型超时或普通Trace降级 |
| 目标 | 历史版本缺失 | unknown/unavailable；不得用当前模板和参数反推历史实际请求 |

源码依据：[S43–S52](source-index.md)。

## 10. Legacy兼容、迁移与未解决项

| 标记 | 项目 | 限制/下一阶段门槛 |
|---|---|---|
| 现有 | 业务状态权威 | Session仍唯一现有权威；本契约未把新空表投入业务写入 |
| 现有 | 原Root唯一索引 | Session唯一Root索引保留；多Workflow尚未开放 |
| 结构已具备 | 新Workflow结构 | 有表/链接/索引/FK和Reader，不等于支持原生事务Writer或原子创建 |
| 目标 | Backfill | 仅可靠证据映射历史归属，无法确认标未知；不造消息/Root/Attempt；不从时间推断 |
| 目标 | Policy适用域 | 显式路由决定legacy/native；不能修改旧Manifest来假装已有V1.1 |
| 目标 | 状态权威Switch | 旧Worker排空/隔离、活跃任务检测、路由、Writer、fencing、兼容演练全部完成才可切换 |
| 目标 | 活跃检测 | 准备状态、Execution.running、Report queued/generating、LLM running、Trace queued/running及内存任务；没有running行不证明旧Worker已停止 |
| 目标 | 回滚 | Expand可保留旧应用；native数据写入后不能无条件回滚旧Session最新查询逻辑；须先拒新写/隔离/核查路由 |
| 目标 | Read Model V2 | 新版本化投影读取显式Workflow与当前引用；保留V1响应与Admin旧Report Trace/Prompt接口 |

**[目标]** 以下仍待后续设计/实现，不计为本次已解决：

1. native Workflow Writer、命令键实际字段/存储与完整fencing尚未接入。
2. 多Worker lease/实例隔离未实现；当前Recover只声明单进程。
3. Root完整生命周期守卫、新直接Span采集尚未实现；旧准备Root不能按目标边更新。
4. Read Model V1对Reporting覆盖partial的行为尚未修改；V2必须用本稿矩阵补齐。
5. ReportGeneration仍只有当前行，不能提供完整业务attempt历史；保留已采集Run/Call，但不伪造历史。
6. 完成后修订、Engine任务Resume、Report候选Resume、unavailable Retry均不在本版本许可范围。
7. 业务库、Trace库、Registry跨库没有分布式事务；必须保守复核、明确缺口。
8. legacy批准/修订宽守卫与目标不同；Policy上线之前必须评审哪些路由可变，不能把本次文档冻结当作旧API已收紧。

## 11. 可直接转换为自动化测试的验收案例

以下为目标/现有契约样例，不是已运行的业务测试。每个ER组合均须成为独立Read Model断言；以下A案例补充状态命令、恢复、并发、安全及兼容边界。实际测试需构造明确输入引用、持久行和并发屏障，而非仅对字面结果做字符串断言。

| 标记/ID | Given | Then |
|---|---|---|
| 目标/A01 | 仅control=COMPLETED，无可读取ExecutionResult | unknown/record_missing；禁止succeeded |
| 目标/A02 | Engine.partial_success，Report.generating | partially_succeeded/reporting；execution_partial保留；非running覆盖失败 |
| 目标/A03 | Engine.success，Report.failed | partially_succeeded/finished；report_failed+report_not_delivered |
| 目标/A04 | Engine.success，交付complete但goal_coverage=partial | partially_succeeded/delivered；不能succeeded |
| 目标/A05 | Engine.success，plan coverage=partial但report goal coverage=complete | unknown/inconsistent；不能伪造完整覆盖 |
| 目标/A06 | Root.complete，删除任务或重新执行 | 拒绝；原Root/Plan/Approval/Execution/Report均不修改 |
| 现有/A07 | legacy Session.COMPLETED，合法删除任务 | 仍按原服务创建新版本并AWAITING_APPROVAL；不移除兼容路径 |
| 目标/A08 | Report.unavailable，用户Retry | 不提供Retry；重复queue仅查询原记录；不发LLM |
| 目标/A09 | Engine中断前有任务已保存，尚有未完成任务 | Recover保留已存结果，未完成skipped，不自动Resume |
| 现有/A10 | 同execution_request_id，相同参数且原Execution.finished | 返回原结果，不新增执行/任务结果 |
| 现有/A11 | 同execution_request_id，不同参数 | EXECUTION_REQUEST_CONFLICT；不覆盖旧请求 |
| 目标/A12 | Planner旧回调，revision或active key或Intent hash不匹配 | 拒绝业务提交；不能换取新key后重放 |
| 目标/A13 | 旧Execution回调，当前execution_id不同 | 拒绝当前业务/Workflow写入；历史可读，不能覆盖新分支 |
| 现有/A14 | 旧report attempt finish=False | 不保存旧Report；旧Report Run不得complete，记录stale/interrupted |
| 目标/A15 | 两个Session中的不同Workflow引用同一Plan locator | 拒绝跨Session/Workflow归属；不同Workflow可以各自version1 |
| 目标/A16 | 创建阶段尚无DatasetProfile/Plan/Approval/Execution | 允许创建；需要origin消息/授权inputfile/root预留/幂等键，不要求未来ID非空 |
| 目标/A17 | 报告queue/start合法更新revision | worker只通过自己成功提交得到新revision；不误判自身检查点过期 |
| 目标/A18 | 新Node Span.parent_span_id非空 | 拒绝新采集结构；Node Span.run_id必须等于Workflow.root_run_id |
| 现有/A19 | 历史嵌套Span/独立Report Run | 兼容读取、不重写、不删除、不伪装为新Root节点 |
| 现有/A20 | Report已提交成功，Trace写失败 | 业务报告保留；collection降级，不重跑报告 |
| 现有/A21 | PromptRegistry.begin快照失败 | HTTP未发送，LLM_SNAPSHOT_UNAVAILABLE；不能套用Trace fail-open |
| 目标/A22 | Root同business_revision，两并发observation_revision旧对象 | 一个CAS提交，另一个False；不得覆盖新状态 |
| 目标/A23 | 旧Worker仍运行，启动Recover | 禁止接管；先排空或fence；不能只按queued/running判断失主 |
| 目标/A24 | 业务必要引用缺失或跨库错位 | unknown/inconsistent，默认拒绝新写；可查历史 |
| 目标/A25 | Engine Recover返回partial_success且无ReportGeneration | partially_succeeded/report_not_started；process_interrupted保留，不盖掉execution_partial |
| 目标/A26 | Engine Recover返回failed且无ReportGeneration | interrupted/finished；execution_outcome=failed，保留EXECUTION_INTERRUPTED |
| 目标/A27 | 报告进程Recover将generating改failed，Engine.success | partially_succeeded/finished；只可显式Retry报告，不重跑Engine |
| 目标/A28 | Root.partial且报告已部分交付，Retry或修订原计划 | 拒绝；generation.completed不是可重试failed，新需求新Workflow |
| 目标/A29 | Root.partial因report.failed，精确显式报告Retry | Root.running观测新执行活动；Engine.partial时business仍partially_succeeded |
| 目标/A30 | Engine.failed，Report.generating诊断 | failed/reporting，不隐藏执行失败；禁止成功事实，仅真实无证据说明 |

**[目标]** 未来测试还须逐条覆盖C命令的允许、缺每个守卫时的拒绝和事务回滚；相同输入在同一policy域不得产生两个不同结果。并发测试需要两个数据库连接/任务真实竞争，不用单线程模拟时序代替CAS验证。

## 12. 文档一致性检查与七项答复

完整记录见 [consistency-review.md](consistency-review.md) 和 [verification.json](verification.json)。检查对象包括矩阵唯一性、状态枚举/ALLOWED源码一致性、每个允许命令的状态边与证据、Engine/Report组合覆盖、禁止重开边、Source引用和旧档案/源码哈希。

**[目标]** 文档检查不等于已经实现所有fencing，也不能证明当前API没有越权窗口。回答必须区分native规范、legacy现状和仍待实现的守卫，不能仅用“全部通过”掩盖差距。

## 13. 下一阶段建议与停止点

**[目标]** 先评审并接受本V1.1的native/legacy隔离、部分成功组合与完成封闭边界，再单独下发Workflow Policy Validator任务。其输入应为已保存事实与明确policy域，输出允许/拒绝及理由，不负责偷偷更改状态或重校验计算算法。

**[目标]** 随后单独实施Lifecycle Read Model V2：先完成ER/A固定用例，保持业务纯只读，发布兼容版本；再评审Writer/fencing/Switch。设计工具、文档检查脚本不应被直接导入生产充当Policy或Aggregator。

**[目标]** 本次到此停止。不开发Policy Validator、V2运行服务、业务Writer、Backfill、UI或权威切换；不更改Prompt/模型参数/算法。

## 附录 A. Runtime节点与状态owner

| 标记 | 节点 | 真实入口 | 状态/输出owner与Trace现状 |
|---|---|---|---|
| 现有 | Data Profiler | backend/app/services/data_profiler.py — DataProfilerService.profile | PROFILING；实际DatasetProfile；准备observed_node |
| 现有 | Intent Parser | backend/app/services/intent_parser.py — IntentParserService.parse | PARSING_INTENT；proceed或clarify；准备Span/独立Call |
| 现有 | Analysis Planner | backend/app/services/analysis_planner.py — AnalysisPlannerService.plan | PLANNING；真实候选、经Validator的结构计划；不能决定审批 |
| 现有 | Plan Validator | PlanReviewService.validate_v1及Planner内部PlanValidator.validate | VALIDATING/同步子操作；F0/F1/F2与coverage；现有可能嵌套Span |
| 现有 | HITL | PlanReviewService.revise_v1/approve_v1 | AWAITING_APPROVAL/APPROVED与不可变Plan/Approval；无完整等待Span承诺 |
| 现有 | Analysis Engine | AnalysisEngineService.execute/recover_interrupted | RUNNING及已存ExecutionResult；无统一Root下端到端Span承诺 |
| 现有 | Evidence Builder | AnalysisReportService.generate内EvidenceBuilder.build | generation.generating，不改变control；evidence_builder Span |
| 现有 | Chart Builder | 同服务VisualizationBuilder.build | 真实受控ChartSpec；当前未独立chart_builder Span |
| 现有 | Insight Generator | 同服务generate内LLM调用 | generation.generating；insight_generator Span，NO_EVIDENCE真实skip |
| 现有 | Fact Validator | 同服务候选事实校验 | 合法/拒绝候选与rule IDs；fact_validator Span |
| 现有 | Report Assembler | 同服务组装AnalysisReport | report_status/goal_coverage；report_assembler Span |
| 现有 | Report Persistence | ReportRepository.finish，由ReportWorkflow.generate调用 | 真实提交及accepted；report_persistence Span；后续才结束Report Run |
| 目标 | 所有新节点执行 | 接纳的Workflow作业上下文 | 新Span直接挂Root；确定性子步骤不增加第三层；无Span不能推断成功 |

**[目标]** Reporting子节点共用当前报告作业fencing，逻辑模块不需要各自新增Control状态或Agent。Chart当前未独立采集应明确不可用，不能让Admin根据图表存在补造完成Span。


**[现有]** 附录节点源码位置：[S57–S63](source-index.md)；HITL/Engine/Persistence位置见[S19–S42](source-index.md)。

## 附录 B. 交付导航与设计验证

**[现有]** [V1.0至V1.1变更清单](changes-v1.0-to-v1.1.md)、[七项一致性评审答复](consistency-review.md)、[结构化矩阵与验收样例](contract-tables.json)、[源码证据索引](source-index.md)、[实际静态检查结果](verification.json)。

**[现有]** 本轮260项静态检查通过；326个源码/配置及旧文档文件未改变。51组组合/边界样例仅用于设计验收基线，不冒充已执行的业务回归。复核命令如下（脚本只会写本目录核验结果，不连接应用或数据库）：

```sh
.venv/bin/python docs/designs/lifecycle-contract-v1.1-2026-10-31/check_contract.py
```

**[目标]** [freeze-manifest.json](freeze-manifest.json)与REQ-0079版本归档共同标识本次冻结内容。将来修订另存新版本，不覆盖本目录；若需复跑验证也应在新复核副本/目录保存结果，避免覆盖冻结交付。
