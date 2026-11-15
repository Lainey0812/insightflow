Lifecycle Contract V1.2 C19定向修订，REQ-0081，保留REQ-0079/VER-0001及REQ-0080旧交付。
原C19替换为C19-A提交授权、原子业务事务要求、C19-B完成观测；其余31行逐字继承，共33检查点。新增持久事实reconciliation：回执丢失不等于失败；Report/Generation/归属/audit相符才accepted；未查/读失败unknown，错位inconsistent。唯一persistence_span_id可选绑定，Trace缺失不阻业务，历史终态Span不重开。
独立WorkflowPolicyValidatorV12实现A前置/B后置与只读重放，旧V1.1 C19拒绝行为保留。无生产接入；旧ReportRepository/ReportWorkflow/Engine/HITL/Trace/API/Prompt/Schema不变，不做Backfill/Switch。
最终专项544通过（原446+新98），完整后端1423通过，Frontend67、Admin78通过。真实子进程在提交中途退出验证原子回滚；提交后返回前退出仍能重新连接读事实accepted；丢失全部调用内存后从generation/report.audit重建授权并完成合法Span观察。中间1个用例期望错误与所有日志保留，未放宽校验。
交付V1.2冻结契约/变更表、33检查点映射与示例、纯提交证据模型/校验、临时SQLite协议测试、完整回归和源码前后快照。
D01在V1.2已解除，可提交下一阶段评审；未自动实施Writer、生产Recover、Lifecycle Read Model V2或Switch。纯领域输入仍须未来可信Reader/Writer适配，不能把客户端自报accepted或transactional当证据。
