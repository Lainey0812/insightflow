# 真实恢复验证范围（调用前登记）

REQ-0094，2026-11-05。用户已确认恢复既有计算结果，不重上传、重审批或重执行。

session_id: d855167be480454689e4c425f9e8a797
workflow_id: wf_133270fa002f4008b54baca9ba347a14
execution_id: exec_f86303595be2401d9b7541f9fbe0c8af
原报告attempt: 1，failed，REPORT_CORE_SCOPE_TOO_LARGE。
真实批准计划4任务，9核心指标、11总指标。预期2个批次，覆盖全部9核心指标；失败/缺失必须标记partial或失败，不挑选重试。Engine执行载荷、审批快照和PlanVersion应保持不变。

运行前对当前业务、Trace、Registry SQLite使用在线backup API制作本地受限备份，不直接复制WAL数据库文件。恢复走原有Report Workflow/业务API与真实已配置Provider。只传既有必要上下文，无完整数据集、API Key或会话密钥进入公开档案。持久化记录仅保存脱敏ID、状态、覆盖和哈希；原始模型调用留在受控本地Registry，不复制可能含用户数据的完整内容到docs。

另外使用冻结合成销售案例S01/S03及固定9指标统计做真实模型验证。所有第一次失败保留，和恢复用户记录分开。\n
