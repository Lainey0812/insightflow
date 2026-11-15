# V1.1 文档一致性评审

日期：2026-10-31；REQ-0079。检查范围是文档、结构化矩阵与源码只读证据，不是新Policy或Writer的运行证明。

## 逐项答复

### 1. 是否同一业务事实对应矛盾的生命周期结论？

**[目标]** native V1.1的ER矩阵每个execution_outcome/report_stage组合仅有一行，完整覆盖3×7=21种组合。优先核对一致性，再看实际交付和执行结果。partial_success+generating固定为partially_succeeded/reporting。与generating状态无关的执行失败原因始终保留。

**[现有]** Read Model V1在queued/generating时仍可能给出running，与V1.1目标不同。这是明确版本差异，不是同policy域内两个可任选结论。本轮未修改该行为。中断、覆盖不完整、缺记录等必须按额外前置规则处理，不能将基础矩阵当作忽略这些条件的无条件结果。

### 2. 是否允许命令却没有合法状态转换？

**[目标]** 32行C命令逐条指定control/generation/creation owner、前态、后态、guard及持久证据。报告命令修改generation而非Control；任务进度是RUNNING内检查点；读/去重无业务边。目标Control与generation边覆盖了这些命令，没有将COMPLETED→RUNNING虚构成报告动作。

**[现有]** 旧服务有直接赋值，approve_v1/revise_v1的宽守卫不能视为统一Policy。这是后续Policy要收敛的实现缺口，本轮不直接更改旧API。

### 3. 是否状态可转换但缺少持久业务证据？

**[目标]** 每条新许可边必须有提交/接纳证据。Root边另列证据：complete须实际完整交付，partial须真实成功计算与交付缺口，Retry须新业务命令已接纳。没有合适事实来源的native Root.unavailable写边已移除，只保留兼容读。

**[结构已具备]** 表约束不是运行保证；原生Writer、命令去重日志和完整fencing尚未实现。因此“设计要求有证据”不能写成“当前每次提交已被验证安全”。结构化检查只能证明规范列出证据，并不能替代真实数据库事务测试。

### 4. 是否可能迟到回调覆盖新Workflow结果？

**[目标]** 符合V1.1的原生提交必须同时验证Workflow owner、当前分支、revision、活动key、精确引用及幂等；任一不匹配拒绝，不重新读最新key再提交旧结果。准备/Engine/Report等阶段要求的字段不同，不误要求未来实体ID。

**[现有]** 准备revision、Root CAS和Report attempt屏障已经存在，但**尚不能宣称当前系统具备完整多Workflow fencing**。特别是Engine finish和历史Report分支提交仍需后续Writer约束。此风险仍是Switch阻断项，本次文档没有“修复代码”。

### 5. 是否错误地将Engine成功视为完整交付？

**[目标]** 不允许。仅COMPLETED不足以成功；Engine.success且无generation仍running/report_not_started，delivery=not_delivered；报告failed为partially_succeeded；只有真实complete报告、完整覆盖及delivered才succeeded。Report partial、unavailable与已写入说明文档分开判断。

**[现有]** Session.COMPLETED仍只表示真实Engine结束（success或partial_success），报告任务独立。legacy Mock同名值必须隔离，不能参与真实成功判断。

### 6. 是否存在不支持的Resume或Retry？

**[目标]** 目标许可不包含Engine task/step Resume、Report候选/token Resume、unavailable Retry、已交付报告Retry或已完成Root重开。恢复扫描不重算；同execution_request_id返回原结果不是再次执行。

**[现有]** API对completed/unavailable的queue可返回原记录fresh=False，不能包装为Retry启动。当前HITL允许完成后新版本，是legacy修订，不是本版本目标Engine Resume。

### 7. 是否破坏历史Session、Root、Report Run兼容？

**[现有]** 本轮没有改代码、数据库、API或旧设计文件；源码/旧文档哈希前后检查记录在verification.json。历史Session完成后修订、旧Root守卫、嵌套Span、独立Report Run与不可变载荷均保留。

**[目标]** 后续实现需显式policy/route和版本化Read Model；不能把旧准备Root硬套完整Root转换、重写Manifest或按时间伪造Workflow归属。本次未运行原业务测试，不将静态哈希一致冒充运行验收。

## 冻结后的剩余风险

**[目标]** 按README第10节处理：Writer/fencing、实例隔离、V2投影、新直接Span采集、命令键持久化、Switch门槛均未实施。V1.1是设计基线，不是“风险全部消除”结论。

## 静态验证边界

**[目标]** check_contract.py只读解析当前源码AST和本目录JSON/Markdown，检查枚举/边集合、命令覆盖、唯一组合、引用位置、冻结旧源码。它不接受运行请求、不连接SQLite、不发送HTTP、不导入app、不判断真实用户操作资格，因此不构成提前开发的Workflow Policy Validator。业务测试尚需下一阶段独立实现。

## 本次实际检查结果

**[现有]** 2026-10-31执行本目录check_contract.py：260项静态检查通过，0项失败。核对12个Control状态、32条命令、21个Engine/Report组合、30条补充案例、63个真实源码符号；326个受保护源码/配置/旧文档文件哈希前后不变。

**[现有]** 本轮未导入应用、未打开数据库、未发HTTP/LLM请求、未跑业务回归。本目录脚本是设计验证资料，不进入backend/tests或任何生产导入路径。51个验收组合/样例是后续测试设计，不是51次业务测试运行。
