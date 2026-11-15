# Phase 02：渐进迁移、回填与回滚方案

本文件全部是建议设计，**不是已运行的 DDL、迁移脚本或实现**。关联 REQ-0076，主报告见 [README.md](README.md)。

## 1. 先解决两个物理兼容难点

### 1.1 不能保留旧计划 PK 又直接在原表插入两个同 Session 的 v1

现有 `plan_versions` 的 PK 为 `(session_id,plan_version)`；UPDATE/DELETE 被禁止。仅加 workflow_id 列不能消除旧 PK 冲突；直接重编号或改历史 JSON 会破坏审计。依据：[原表与不可变触发器](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:8)。

推荐新增统一版本引用仓 `workflow_plan_versions`：

| 字段 | 约束 |
|---|---|
| plan_version_id | 新稳定主键，不取代/改写旧 Session+version 主键 |
| workflow_id、plan_version | UNIQUE(workflow_id,plan_version)，版本在 Workflow 内独立从 1 开始 |
| plan_id、dataset_id、dataset_version、validation_version、payload_hash | 与不可变载荷核对；版本只指向该 Workflow 的数据快照 |
| legacy_session_id、legacy_plan_version | 历史行的可空组合 FK 到原 plan_versions；二者同时存在或为空；非空时全局唯一 |
| record_json | 新版本的既有 PlanVersion/ValidatedAnalysisPlan 载荷；历史 locator 行不重复复制载荷 |
| registered_at、source_kind | 记录本次登记时间与 legacy_ref/native 来源 |

CHECK：legacy locator 与 native record_json 必须二选一；历史解析从原表读取，原行/ID/JSON/创建时间完全保留，新版本仅写统一版本仓。提供 UNIQUE(workflow_id,plan_version_id) 支持同作用域组合 FK。不可变触发器适用于新版本仓，不能更新已登记版本内容。

这不是第二套并行可修改的计划事实源：每个版本只有一个载荷位置，仓库 resolver 统一读取。旧表成为只读历史载荷；不得同时往旧表和新仓存两份可独立变化的相同新版本。

### 1.2 不绕过不可变 Approval、Report、Call 触发器回填 JSON

既有不可变对象采用**类型化归属链接**，不把 workflow_id 强塞旧 record/request/audit 中，也不改旧 payload hash。链接是事实引用和约束索引，不是新的业务执行或 Attempt 实体。

建议逻辑表：

| 新表/索引 | 内容与约束 |
|---|---|
| business_workflows | 主报告字段；FK Session；UNIQUE(root_run_id)、UNIQUE(workflow_id,session_id)、创建幂等约束；当前计划/批准/执行以同 Workflow 组合引用校验 |
| session_messages | 保留原 message_id、session_id、顺序和内容；UNIQUE(session_id,message_id)、UNIQUE(session_id,sequence)；新分析消息可指向 Workflow；会话级消息可为空 |
| session_datasets | PK(session_id,dataset_id)，FK Session/Dataset；授权目录，不复制数据或画像 |
| workflow_plan_versions | 上述统一版本仓；FK Workflow 和 DatasetProfile 复合键；历史 locator FK |
| workflow_approval_links | approval_id PK/FK 原审批；workflow_id、session_id、plan_version_id；UNIQUE(workflow_id,approval_id)；组合 FK 保证版本与 Workflow 一致；client_request_id、payload_hash 用于新作用域幂等 |
| workflow_execution_links | execution_id PK/FK 原执行；workflow_id、approval_id、plan_version_id、dispatch key、client_request_id/hash；组合 FK 指向同 Workflow 的审批和版本 |
| workflow_report_links | report_id PK/FK 原报告；workflow_id、execution_id、accepted_report_attempt；组合 FK 指向同 Workflow 执行，仅为真实 engine 报告建立可执行业务链 |
| session_workflow_routes | session_id PK、legacy/shadow/workflow_v2 模式、明确 legacy default 映射与迁移版本；新旧写入隔离，不按时间选默认 |
| workflow_backfill_items | 源类型/原键/hash、已分配 Workflow/新版本 ID、状态、证据、规则版本及校验错误；支持断点与人工复核；不是运行 Attempt |
| Trace 侧库 trace_workflow_links | run_id PK/FK 本库 TraceRun、workflow_id、kind、证据；对 kind=workflow 建 Workflow 唯一索引；不建立跨业务库 FK |
| Registry 侧库 llm_call_workflow_links | call_id PK/FK 本库调用、workflow_id、证据引用；允许 Run/Span 缺失；不改原调用终态及快照 |

可通过既有表的新增唯一索引 `(id,session_id)` 支持绑定的组合 FK，而不改变原 PK 或载荷。写入链接时还必须在同事务检查原 record 的 session_id、plan/version、审批快照及 payload hash；SQL FK 只核验关系，不能替代 JSON 一致性校验。

ReportGeneration 继续以 execution_id 为主键，Workflow 归属通过 execution link 唯一确定，无须复制另一套 generation 状态表。没有强 FK 的历史行先标记缺失/歧义；不得在未知归属时硬加必填 FK 后强行改数据通过。

这些是最小责任划分建议，实施时可以合并纯元数据索引的物理形式，但不能取消类型化关系校验或把绑定表当第二个结果载荷仓。

## 2. 幂等键与事务边界

### 2.1 保留旧唯一约束，兼容新 Workflow 命令作用域

现有审批 `UNIQUE(session_id,request_id)`、执行 `request_id UNIQUE` 不能立即删；前端旧缓存仅含 Session+数字版本。依据：[审批 DDL](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/plan_review_repository.py:15)、[执行 DDL](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/execution_repository.py:16)、[前端缓存](/Users/lainey/Desktop/vibe-coding/insightflow/frontend/src/api/client.ts:74)。

新 API 在归属链接中保存客户端原 key 与规范化请求 hash，UNIQUE(workflow_id,operation,client_request_id) 形成逻辑命令作用域。审批/执行各自表可将 operation 固定为该操作，不必新建命令运行实体。

向旧物理表写新对象时，使用服务端生成的作用域化有效 key，例如对 `(workflow_id,operation,client_request_id)` 规范化编码后计算稳定 hash。保存的原 request JSON、索引 request_id 及对象中的有效 key 必须保持一致；v2 receipt 同时明确原 client_request_id，避免错误回显。这样两个 Workflow 可各自使用 `confirm-1`，又不破坏旧唯一约束。历史 key 不重新编码；旧 replay 通过已登记的 legacy 映射按原请求验证。

同 key 不同 payload 必须冲突；同 key 相同 payload 返回原对象/回执，不能重做批准或计算；已失效批准重放必须明确 superseded，不因为回执存在就重新授权执行。hash 碰撞/存储不一致必须报错，不静默复用。

规范化 hash 必须区分业务命令内容与并发前置条件：Workflow、版本、批准、数据、确认项和目标等进入语义 hash；expected_workflow_revision 是首次接受时检查的前置条件，不应使已经成功的相同业务命令因刷新后 revision 变化而重复执行。重放先定位原回执并验证原业务内容/当前有效性，不改写原保存 request 的旧 revision。这个 v2 规则不能静默替换既有 v1 完整 request 字节比较；旧请求仍按原约定验证。

### 2.2 业务事务

在同一个业务 SQLite 事务中完成：验证 Workflow revision/控制状态/active_execution_key；核对数据和计划版本；保存命令事实与归属链接；原子更新该 Workflow 的当前引用及 revision；最后提交。批准后才能执行的现有校验不减少。

Workflow 执行/准备令牌只在合法接受或恢复命令时更新。worker 提交必须同时匹配 workflow_id、令牌、预期 Workflow revision 和具体 plan/approval/execution/report attempt；命中旧令牌时保留历史记录/忽略事件，不用最新值自动重放。

Session 消息追加与 Workflow 创建可在业务库同事务中完成，保持 origin FK。不同 Workflow 更新不竞争同一份“当前分析 JSON”；SQLite 仍会短暂串行写入，但不能产生跨 Workflow 状态污染。消息 revision 的独立增长不使别的 Workflow 的回调失效。

Trace 是独立库，不跨库事务。业务提交后以 accepted 结果驱动观测；Trace CAS 仍基于 observation_revision。报告落库必须检查 accepted=True，[现有保护](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/report_repository.py:65)不能被适配器取消。若 Trace 丢失，只暴露 collection 缺口，不能反向回滚已成功计算。

## 3. Expand：只加结构和兼容读取，暂不开放 1:N

未来实施步骤，不在本阶段执行：

1. 先保存源码/业务与侧库一致性备份，记录 Schema 版本、源行数/hash、未完成工作及恢复政策。确认所有受影响读写端版本；不能边升级边允许旧进程重新建旧索引。
   备份应采用 SQLite 一致性备份能力并处理 WAL；不能逐个复制正在写入的数据库文件就宣称跨库一致。需要跨库协调恢复点时，先进入明确停写/排空窗口；否则只能分别记录各库快照及业务 revision/采集边界，并在恢复后复核。
2. 业务库新增第 1 节的 Workflow、消息、数据授权、版本仓、归属/迁移路由表及索引。旧表、原 PK、不可变触发器、原 JSON 和对象 ID 均不改。
3. Trace/Registry 侧库新增归属链接及唯一索引；保留旧 Session 唯一 Root 索引，此时仍只允许单默认 Workflow。新解析器读旧 Run/Manifest/Call，也能识别缺失。
4. 部署理解新结构的 bridge 版本；默认读写仍走旧路径。shadow 模式中，旧 Session 是当前控制事实源，新 Workflow 只是带源 hash/revision 的镜像，禁止两边同时授权命令。
5. 对消息采用相同原则：shadow 阶段原 Session.messages 是事实源，新消息表只做可验证投影；Switch 后消息表成为事实源，单 Workflow 旧 DTO 由适配器生成，不允许两套独立消息写入。
6. 不改 Prompt 文本或 AnalysisPlan LLM 输出。若服务组合源码变化影响模板指纹，登记新的组合版本，保留原模板/请求；禁止复用旧版本标签覆盖源内容。[TemplateSource.build](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/llm/templates.py:111)。

Expand 成功标准：新表/约束可读，原单流程行为及旧数据字节不变，影子读取不能改变状态。只是存在新表不代表可开放多个 Workflow。

## 4. Backfill：按 Session 原子回填，但按证据绑定各历史对象

### 4.1 每个 Session 的默认 Workflow

1. 以只读快照读取 Session、版本/审批/执行/报告及必要侧库证据；捕获源 revision 和内容 hash。
2. 迁移路由记录中为 `(source Session,迁移契约版本)` 分配且持久保存一个随机 Workflow ID；重跑复用该 ID，不重新生成。当前 Row 不代表过去已存在独立 Business Workflow。
3. 在业务库 `BEGIN IMMEDIATE` 内重新核对 Session revision/hash 未变化，再创建默认 Workflow、可验证消息/数据关系、计划 locator 和各业务链接；单 Session 成功或全部回滚，不留下半个可执行 Workflow。
4. 正常历史单流程记 origin=legacy_default。legacy_mock 或缺少真实数据/审批链的记录记 legacy_archive，只读、不可执行；允许 input/profile/origin 字段明确缺失，不创建假的文件、画像、计划或审批来补齐。
5. 目标原话取 Session.user_goal，结构化 Intent/澄清按原记录保存。origin_message_id 只有在创建结构、原话及上下文有可靠对应时绑定；仅仅有“第一条用户消息”是候选，不足以匹配未知历史分支。
6. 历史 created_at 可以继承“旧分析开始时间”，但 provenance 必须注明其来自 Session；materialized_at 单独记现在的回填时间，不能冒称新表在旧时间已存在。

一条 Session 的默认 Workflow 只覆盖能够证明的原分析链。如果出现多个 plan_id、不同数据版本或互不兼容目标，先判断是否正常历史修订；无法证明则标记歧义，不因旧设计通常 1:1 就将所有记录判定 verified。

legacy_mock 的 Session.plans/旧 Report 不是 V1 AnalysisPlan/AnalysisReport，保留原分析 JSON 及旧 renderer，或在 control_context 中保存有源 hash 的只读归档引用；不能为填满新版本仓而转换成“真实已批准计划”。Session 元信息以后可以改变，但已归档分析字段/受控快照必须保留原值。

### 4.2 归属证据优先级

| 来源 | 可接受证据 | 不足时的处理 |
|---|---|---|
| PlanVersion | 明确 Session 索引与 JSON 一致；计划 ID、版本和数据链可核验 | 保留原表，只登记异常，不构造假版本 |
| Approval | approval_id/Session、精确计划版本快照、验证版本与数据一致 | 无匹配持久版本时保留 snapshot_only 历史，不能自动补一份“已审核计划”授权新执行 |
| Execution | 原行 Session、请求、不可变 approval snapshot、实际结果引用一致 | imported/mock、缺批准或冲突保持原 ID 可追溯，但不建立 verified 执行链 |
| ReportGeneration/Report | 明确 execution_id、对应执行归属、保存 audit 的 Plan/Approval/数据核对 | 无源执行的导入报告可按旧 ID 保留，不伪装成业务 Engine 报告 |
| Root | 旧 Root session_id 唯一且 Manifest 绑定一致 | 多候选/冲突隔离；完全缺失只预留 root_run_id，不造历史 Trace |
| 历史 Report Run | execution_id+attempt、保存的业务报告与不可变绑定核对 | 不依据最后成功时间选择根；无证据记 unresolved，不删除 |
| Span/Event | 已验证 Run 加既有同 Run 引用/序号 | 父链、索引冲突要隔离，不改名或重排序号 |
| LLMCallRecord | 明确 Run/Span 链；或唯一真实 IntentArtifact.parse_id=operation_id，并核对节点/模板/数据上下文 | 相似消息、相同模型、接近时间均不算确定归属；缺证据调用保持 unavailable |

所有原始记录保留。归属验证可以由 immutable snapshot 的精确 hash 支持，但“同数据内容”不能证明“同业务目标”。人工修正写新的归属裁定/版本说明，保存旧裁定，不覆盖旧请求、模型输出或原始 JSON。

已被业务消费的 verified 绑定不得直接改到另一 Workflow。新人工裁定先追加迁移证据并重新检查所有依赖，冲突保持不可执行；不能在不重新评审/失效相关授权的情况下移动批准、执行或报告。普通 unresolved→verified 的首次绑定可在验证事务中建立，之后视为不可变归属。

### 4.3 状态与中断

backfill_items 使用 proposed/verified/unresolved/conflict/failed 等迁移状态，记录原键、源 hash、规则版本、错误码及 checkpoint。它不是 Workflow 运行尝试实体。

- 未变化的已验证源重跑只核对，不重复插入 Workflow、版本或链接。
- 源在读取后变化：丢弃本次候选并重读，不拿旧 Session 覆盖新业务记录。
- 每 Session 业务事务失败：当前 Session 全部回滚；其他已完成 Session 可保留，当前路由不切换。
- 业务回填成功而侧库链接失败：保留业务 Workflow，标记 collection/association gap；幂等重试侧库链接，不回滚业务，不虚报采集完整。
- 任一关键审批/执行归属有 conflict 的 Session 不能切换为可执行 v2；可以保留只读归档或经人工解决后重验。非关键历史无归属 LLM 调用可明确保留 unavailable，不阻止可信业务链迁移。

旧 ReportGeneration 表只保存当前 attempt，过去 generation 的失败详情和排队时间不一定存在。已有 Report Run/Call/日志可以保留为观测证据，但不能反推补成过去的权威业务提交记录。本设计不新增独立 Attempt 实体，也不宣称可恢复所有缺失历史。

## 5. Validate：不能只比较总行数

每个 Session 及整体批次保存验证清单：

1. 原 Session/PlanVersion/Approval/Execution/Report/Trace/Call 的原主键、ID、不可变 JSON 和 hash 不变；不得为通过校验重算旧档案 hash。
2. 一个可切换 Session 恰有一个可确定 legacy 默认 Workflow；所有保留版本 locator 唯一、版本顺序不变；没有孤立或多归属的对象。
3. 组合 FK、同 Workflow/Session 所有权、数据复合版本、计划/批准/执行快照 hash 全部匹配。PRAGMA foreign_key_check 是其中一项，不代替语义校验。
4. 全量结果行数、result_ref、错误/警告、报告 evidence_refs 与原输出相同，不重新计算结果或调用 LLM 来“补历史”。
5. 旧单 Workflow API 与 shadow 新聚合在同一源快照下等价；Engine partial_success、Report failed/partial、未完成目标、旧分支和 Trace 缺失不能被提升为成功。
6. Root CAS token 与原始 Manifest 保留；已结束 Span、历史 Report Run、Event 顺序和 Call retry 链无改变。
7. 对未归属/歧义分别出具数量与具体受控引用，不把“所有已填列非空”当作正确回填。
8. 跨库独立事务后复核业务 Workflow/Session 源版本；变化返回 changed/inconsistent，禁止发布一次混合快照。

当前只读库存仅是样本现状，不是此验证已通过的宣称。本阶段未实施回填，也未生成已通过迁移的业务 ID。

## 6. Switch：单 Workflow 先切权威，再开放 1:N

1. 先按 Session 切到 workflow_v2，但仍限制一 Workflow。单个业务事务切换路由版本；以 Workflow 控制记录为唯一命令事实源，旧 DTO 仅是兼容投影。不要长期双向同步两个状态机。
2. 所有旧分析 API 只能经新版唯一解析适配器访问。审批/执行/报告落库及链接和 Workflow revision 同事务；报告不再镜像修改 Session 的分析当前槽。
3. 排空/终止旧 worker，拒绝其旧命令入口，并使用数据库写保护阻止 workflow_v2 Session 的旧分析字段被改写。新 Session 元信息可以更新，但旧 status/plan/approval/node_runs/report_generations 等分析槽冻结；旧 PlanVersion 插入对已切换 Session 同样禁止。仅依靠反向代理不够，持有数据库连接的旧 worker 仍可能回调。
4. 现有 guard 从 Session revision 转到 Workflow revision+active key，Root CAS 不变。所有 v2 工件只在可信链接同事务保存后可见，旧未绑定 worker 的孤立输出不能成为当前有效结果。
5. 所有读取端都理解业务归属后，Trace 查询改为 workflow_id 链接。在确保旧二进制不会再执行旧 migrate_workflow_roots 的条件下，删除旧“Session 唯一 Root”索引，保留新的“每 Workflow 唯一 Root”约束及原 execution_id+attempt 唯一约束。**删旧索引之前，新 Trace 读写器已上线；业务暂仍保持一 Workflow。**
6. 经测试、回滚演练及架构批准后，单独打开 Session 1:N gate。允许两个 Workflow 各有 v1，前端选择和幂等缓存改为新作用域；旧 API 多候选明确报歧义。不要以 legacy default 或最后成功项掩盖旧客户端问题。
7. 新 Reporting 只产生 Root 下实际 Node Span；历史独立 Report Run 继续只读跳转。完整 Root 生命周期写入器需要真实节点/业务提交证据，不得因为表扩展完成就标记所有阶段采集完整。

数据库保护是未来实现的约束，不在本轮写出可直接执行的触发器。实施时必须测试 Session 纯元信息更新、消息追加、合法 Workflow 提交不被误拦截，同时旧分析字段写入被明确拒绝。

## 7. Contract：收敛写路径，不删除历史

在充分观察和显式批准后，停用旧分析写入口、影子写入和不再需要的兼容缓存。旧 plan_versions 及被 locator 引用的载荷、旧 Approval/Execution/Report、Span、Report Run、Manifest、Call/Request/Template 永久按保留政策保存；Contract **不等于清理这些记录**。

原主键与旧 ID 查询仍保留。若未来要把 locator 载荷搬迁或改变 PK，应作为另一项经过校验的迁移，不属于本方案的默认 Contract 动作。不可变记录保护不能为了方便迁移被整体关闭。

## 8. 回滚与不可逆边界

| 阶段 | 可接受回退 | 限制 |
|---|---|---|
| Expand，未切权威 | 关闭 feature flag，继续旧逻辑；保留新增表/元数据 | 不删除回填档案或已登记链接；旧程序能否容忍新 Schema 仍需演练 |
| Backfill/Validate | 暂停当前批次，按源 hash 重验并续跑；不切未通过 Session | 不能回写旧 JSON 来迎合迁移 |
| Switch，仍单 Workflow | 仅在 bridge 确认旧投影与新事实完全同步、没有 v2-only 版本/记录后，受控回退路由 | 不是直接启动任意老二进制；涉及数据库写保护和当前工作者令牌 |
| 1:N gate 已开放或已有 v2-only 版本 | 回退到仍理解 Business Workflow 的上一兼容版本；可关闭新建并保持全部 Workflow 可读 | 不能选一个 Workflow 塞回 Session 后丢弃其他；不能恢复旧 Session-only 写入器 |
| Contract | 优先前向修复；只读兼容继续 | 旧载荷被引用不得删，Schema/权限收敛需独立批准 |

特别风险：

- 已有修复会写 observation_revision，旧 TraceModel extra=forbid 不能保证读取新记录。[当前契约](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/domain/tracing.py:5)。后续新增 Workflow 字段或 Manifest 版本同样需要兼容读取，不能把“DDL 可撤销”当作“程序可回滚”。
- 旧迁移函数启动时会再次创建 Session 唯一 Root 索引。[migrate_workflow_roots](/Users/lainey/Desktop/vibe-coding/insightflow/backend/app/storage/trace_migrations.py:26)。产生同 Session 多 Root 后，重建该索引将失败；即使尚未产生重复，也会重新禁止新业务。必须阻止旧二进制重新执行此路径。
- 旧 plan_versions 无法表示两个同 Session 的 v1；不能把新仓两份版本再反向写入旧表。唯一引用仓是兼容措施，不是回滚到旧写入模型的承诺。
- 产生多 Workflow、v2-only 版本/命令或在侧库写新契约后，回退到未理解新模型的程序是语义不可逆边界。禁止以删除新对象恢复旧唯一性。
- 恢复旧数据库备份会丢失备份后的新增业务；只有明确维护窗口、增量保护和用户批准后才可讨论，不能作为自动回滚步骤。

## 9. 本阶段停止点

待架构评审确认：预留 Root 身份的 0..1 物理采集解释、统一版本仓 locator、归属链接物理形式、v1 歧义错误、历史不可执行策略和 1:N gate 时机。通过后另立实施任务，先 Expand 与读取验证，再 Backfill。没有创建任何上述新生产表、迁移脚本或测试。
