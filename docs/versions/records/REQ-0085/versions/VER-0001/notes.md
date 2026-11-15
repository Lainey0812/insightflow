Lifecycle Instrumentation Vertical Slice 02 部分交付：只完成 HITL 审批、拒绝请求、修订与幂等重放的真实 Root 直接 Span；提交后核验真实 PlanVersion/Approval，Trace 故障 fail-open，修正 HITL 内 Validator 的观测角色，不改变业务授权或事务。
依据任务明确的停止条件，Engine 和 Reporting 未接入 Root：Engine finish 缺少精确当前分支 fence；Report 只有 attempt/status guard，尚无 C19-A/B 要求的 Workflow 链接与持久提交凭证；Root 更新规则仍仅准备阶段，waiting_approval 不允许后续转换。新增隔离 fixture 复现原始提交函数在合成分支漂移下的 guard 边界，未宣称是现有公共 API 可利用攻击，也未移除合法旧执行报告能力。
后端最终 1443 项通过（新增专项9项），Frontend67、Admin78，通过两者构建。真实60行CSV+qwen3.8-flash最终准备10.717秒，审批及重放后Session=APPROVED，同Root下8个真实Span、两条真实LLM调用、一条Approval；Engine/Report未执行。保存初轮和最终运行、源码快照、diff、审计与只读关联证据。
这是部分交付，不宣称全链路或完整Slice02验收通过。未实施Session权威切换、多Workflow、Engine Resume、C19 Writer修复或Root状态机扩展；保持旧Report Run和业务行为。停止，等待评审。
