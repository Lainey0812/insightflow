# Implementation Gap Report

REQ-0082；本次只读源码审计，不包含任何新运行记录或迁移。源位置见[source-index.md](source-index.md)，语法树调用点见[observed-call-sites.json](observed-call-sites.json)。

## 1. 可复用能力与当前边界

| 组件 | 当前实现成熟度 | 已由源码证明的事实 | 不可据此宣称 |
|---|---|---|---|
| 准备Root登记与更新 | 部分实现 | Session创建后登记Root、原子observation_revision CAS、业务revision不倒退、旧回调忽略 | 已有Business Workflow原子预留Root或端到端完成状态 |
| Root CAS机制 | 已实现 | update_run在BEGIN IMMEDIATE内读比写；Manifest/身份不可变 | 已保护Span/业务提交或已允许完整Root转换 |
| Span存储与终态检查 | 部分实现 | 真实Scope开始/结束、终态不可再次更新的顺序检查、跨Run parent拒绝 | 原子Span CAS、全节点直接Root、无并发覆盖风险 |
| Workflow node_attempt预留 | 已实现（局部） | reserve_workflow_span库锁内MAX+1并插入 | Report旧Scope也有同等计数语义，或绕过该方法也安全 |
| TraceEvent | 部分实现 | Root内库锁sequence、唯一ID、同ID同记录幂等、跨Run引用检查 | Legacy Report Context有统一跨进程序、事件与Span状态原子 |
| LLM请求快照与Call日志 | 已实现（HTTP边界） | 配置Compatible Provider时begin记录请求、finish记录Provider结果，Schema/模板hash可查 | 未发送请求也算真实远端调用、业务语义一定通过、Workflow ID已统一 |
| Reporting局部Span | 部分实现 | evidence/insight/fact/assembly/persistence及真实NO_EVIDENCE skip | Chart已有Span、Report Run已合并Root、业务提交已走C19 Policy |
| HITL/Engine Trace | 未实现 | 有真实审批、执行与任务日志，但没有独立统一Trace Span | 业务记录存在就等于已经埋点 |
| Trace fail-open | 已实现（受控路径） | TraceRecorder捕获Exception，降级日志与gaps；snapshot构建也在fail-open范围 | Registry也fail-open、所有格式化/上下文错误已经证明绝不会影响业务 |
| V1.2 C19-A/B/核验 | 已实现（独立纯Policy） | 纯资格与提交事实核验、精确Span模型及测试 | 生产Writer、Recovery或Trace终态写入已接入 |
| Business Workflow/link结构 | 结构已具备 | 新表/约束/只读Reader与预留root字段 | 多Workflow运行已开放、Session唯一索引可直接删除 |

## 2. 缺口清单

| ID | 优先级 | 缺口与风险 | 源码事实/推导 | C2最低处置 |
|---|---|---|---|---|
| G01 | P0 | 身份仍依Session | register_root随机生成ID；preparation_context/TraceRepository.workflow按Session查；唯一索引workflow_session_unique | 原生可信Workflow绑定未具备前不生产激活，不用Session ID冒充Workflow ID |
| G02 | P0 | Root只覆盖准备 | kind=workflow update_run拒绝complete/partial，waiting_approval无出口 | 保留旧kind/capture_scope守卫；全链路Root接入须独立批准并按V1.2来源事实推进 |
| G03 | P0 | 新Span仍可能嵌套 | SpanHandle使用active parent拼node_key/parent_span_id；Planner内Validator嵌套 | 新scope平铺、稳定key、旧嵌套兼容读；不改写旧Span |
| G04 | P0 | Span终态并发保护不足 | save_span先SELECT再upsert，没有BEGIN IMMEDIATE原子读比写；两个旧running读取可能覆盖较新终态（源码推导，非本次DB复现） | 兼容的原子终结/身份守卫；不可把Root CAS当Span CAS |
| G05 | P0 | 结束事件与状态不原子 | SpanHandle.finish/TraceContext.finish先写Event再更新状态；update拒绝时仍可能已存在finished事件 | 同Trace库CAS+终态事件原子；读端不以事件存在直接推完成 |
| G06 | P0 | 新C19提交/恢复无生产接入 | ReportWorkflow只用finish返回值；新Policy和proof模块没有被业务服务导入；归属Writer未启用 | A/事务/proof/B四步适配单独实现与故障注入，业务提交在前，观察失败不回写业务 |
| G07 | P0 | C20观测终结未决 | V1.2 B仅接受Generation.completed和report.complete/partial；不能核验C20 unavailable | 架构专项决议前不激活该新native持久化路径；C1不改V1.2或虚构C20-B |
| G08 | P0 | 关联字段会丢 | SAFE_KEYS不含全部workflow/root/approval/execution/task/commit字段，新payload可能被静默过滤 | 字段白名单/类型/截断迁移与测试；不能只传kwargs就宣布已保存 |
| G09 | P0 | 端到端作业fencing未集成 | 准备revision和Report attempt已有局部保护，active_execution_key仍是Expand空结构 | 传播可信owner/branch/key，读/写分离；旧回调不改当前Span或业务 |
| G10 | P1 | 缺节点/审核事件 | Engine、HITL、Chart无真实独立Span，审批/排队/claim事件无统一字典 | 逐节点真实入口适配；不根据报告补假事件 |
| G11 | P1 | 当前终态只看异常/rejected_count | SpanHandle无异常时默认complete；Assembler.partial可能被记complete；F0/clarify业务含义只能从有限attrs看 | 明确业务outcome与合法状态映射，不改分析决策/算法 |
| G12 | P1 | 节点Span可能早于检查点接纳结束 | observed_node退出with后才存完整Intent/Profile/Planner检查点 | 标清阶段完成与业务接纳；事务性边界未来移到接纳后，旧记录按旧语义 |
| G13 | P1 | 恢复顺序/扫描不足 | main先业务再Trace恢复；Trace只扫queued/running Run，不扫waiting Run内孤立running Span；依赖单进程 | 先核验已提交C19，再处理失主；已有终态不重开，多Worker未隔离不恢复 |
| G14 | P1 | HTTP与Call成功含义易误读 | Registry.begin早于_send；当前llm.started早于Provider调用，Call.succeeded不代表节点Schema/事实成功 | 分离本地dispatch尝试、Provider结果和业务校验；不承诺远端收到 |
| G15 | P1 | node_attempt/sequence局部计数 | Root Span在库分配，Report Span主要本地；Report Event本地sequence；并发另Context可能冲突 | 新Root统一库内计数，Event按持久入库顺序；重复/并发测试 |
| G16 | P1 | 原生多次报告快照冲突 | trace_snapshots UNIQUE(run_id,kind)且不可变；旧Report每attempt一Run可用，新单Root多attempt会冲突 | 对attempt/operation的受控快照策略单独评审；不覆盖旧快照，不用新平行Run绕过 |
| G17 | P1 | 事件/诊断预算与缺口非持久 | 每Context256、Root库序号上限256、8KiB字段、warning_count最多10、gaps在内存；重启会丢部分缺口信息 | 有界摘要+明确丢失/unknown；预算与日志脱敏测试；不保证无丢失 |
| G18 | P1 | 快照/恢复能力不能过度宣传 | 当前受控投影只保有限Evidence/LLM候选hash/报告hash，Raw请求有独立权限与有效期 | 默认摘要、到期unavailable；不承诺可还原所有历史输出 |
| G19 | P0 | Trace与Registry故障策略不同 | TraceRecorder.call降级；CallRecorder.begin/finish失败阻止调用或交付结果 | 保留差异与明确错误，不能统一吞掉Registry错误提高成功率 |

## 3. 不能可靠推断的事实

- 没有业务引用的历史Call属于哪个Workflow，不能按时间/文本相似度补齐。
- 未采集或被截断的节点是否运行，不能从报告图表、Session.COMPLETED或零错误事件推断。
- 没有可信持久提交元数据的历史Report，不能伪造新V1.2 receipt；可按既有audit/作用域保守读取。
- 已interrupted的历史Span是否能改complete：不能；业务后来核验成功不授权重写历史终态。
- Trace失效时完整丢失了多少事件：若未记录计数则unknown，不能编成0。
- 当前本地Repo顺序检查在多Worker并发下是否足够：Root已有CAS，Span/历史Report Call终结仍需独立测试，不能外推。

## 4. 事实与推导边界

本报告“现有”指源码存在相关路径，不证明所有生产运行都覆盖。并发、重启与协议风险是由读写时序和约束推导；本轮未运行DB探针或业务测试。C19先前测试记录保留为既有证据，不冒充本次新端到端结果。
