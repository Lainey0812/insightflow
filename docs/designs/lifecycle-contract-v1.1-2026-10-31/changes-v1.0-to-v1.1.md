# Lifecycle Contract V1.0 至 V1.1 变更清单

关联REQ-0079；原V1.0目录与归档不修改。下表记录契约修订，不表示业务代码已更改。

| 标记 | 优先级/项目 | V1.0问题或边界 | V1.1冻结决定 | 位置 |
|---|---|---|---|---|
| 目标 | P0-1 控制与交付 | COMPLETED含义虽有说明，但Engine后各命令的授权不够明确 | Engine结束不等于交付；按generation阶段给出查询/初次生成/Retry/Worker/再执行完整许可；报告命令不重开Control | README第2、3、4节 |
| 目标 | P0-2 部分成功 | V1.0沿用现有generating覆盖为running | 固定execution_outcome、delivery_status、business_lifecycle三维；Engine partial时Reporting仍partially_succeeded；21组结果与特殊案例 | README第5节、ER01–ER21 |
| 目标 | P0-3 Root完成封闭 | V1.0目标表曾允许complete→running用于同目标修订 | **删除V1.1目标中的该边**；complete终态；报告partial交付亦不获得Retry；新目标新Workflow | README第6、9节 |
| 现有 | P0-3 Legacy路径 | 当前COMPLETED→AWAITING_APPROVAL与真实revise_v1存在 | 保留源代码、枚举与旧API；明确它不是native V1.1许可；原版本不覆盖 | README第3、4.3、6节 |
| 目标 | P0-4 三类恢复 | 原稿重试与“继续”语义容易混淆 | Recover只收敛已提交事实；Retry是新活动；Resume只指业务等待继续；Engine task/step、Report候选续跑不支持 | README第7节 |
| 现有 | P0-4 Engine Recover | 当前保存progress并把未完成任务skipped | 只声明Recover、不宣称任务Resume；启动次序与单进程限制明确 | S29、S53 |
| 目标 | P0-5 Fencing | 全字段列表容易错误要求未来ID提前存在；旧报告attempt不等于全Workflow隔离 | 分阶段M/O/N、owner/revision/key/branch/精确引用/幂等；四类旧回调拒绝；报告自身revision演进与Trace缺失明确 | README第8节 |
| 结构已具备 | P0-5 数据基础 | active_execution_key/组合FK已存在但未投入Writer | 不宣称+1触发器等于CAS，亦不宣称已全链路fence | README第1、8节 |
| 目标 | P1-1 Span直接Root | V1.0已有两层目标但通用Span仍可嵌套 | 新Node Span必须root run且parent为空；技术子步用Event；历史嵌套兼容读 | README第9节 |
| 目标 | P1-2 unavailable | queue终态可幂等返回易误解成Retry | unavailable不提供Retry或Resume；completed partial报告也不提供Retry | README第3、4、7节 |
| 现有 | P1-3 两类日志故障 | Trace fail-open与Registry强制请求日志不同 | 分开记录策略：Trace降级；Registry begin失败不发HTTP、finish失败不交结果 | README第9.3节 |
| 目标 | 补充Root unavailable | V1.0目标允许Root running→unavailable，但与Engine全失败/有成功计算的终态可能重叠 | 保留读取枚举，native V1.1不新增该写边；有成功结果用partial、无成功用failed | README第9节 |
| 目标 | 补充守卫缺口 | 不能把宽ALLOWED/直接赋值当成所有API已有状态许可校验 | 审计并公开approve_v1未单独检查AWAITING_APPROVAL、revise_v1未检查活动generation等差距 | README第4.3、10节 |
| 目标 | 可验证设计 | 纯说明文难发现命令/边不一致 | 提供结构化矩阵、51组结果/补充样例、静态设计检查与源码位置 | contract-tables.json、check_contract.py |

**[目标]** 此次冻结不改变Business Lifecycle或Activity枚举，不增加Attempt实体、Trace层级、Prompt节点、API或数据库Schema。execution_outcome/delivery_status为契约名与现有字段映射，不冒充现有API新字段。
