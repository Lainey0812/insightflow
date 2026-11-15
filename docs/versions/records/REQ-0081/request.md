将 C19 拆分为两个明确的契约检查点。
C19-A：Report Commit Authorization
提交前检查 Workflow 归属、当前执行、attempt、有效状态和 fencing token。通过后才允许尝试业务事务。
Business Transaction
原子保存 Report、ReportGeneration 和归属关系。提交成功才产生可信的 accepted 结果。
C19-B：Report Completion Observation
仅在 accepted=True 且业务提交证据成立后，允许将对应 Trace Span 标记为完成。
这里还要处理一个边界：如果业务提交成功，但进程在返回 `accepted=True` 前崩溃，恢复程序必须查询持久化事实，不能仅因没有收到返回值就认定提交失败。
建议将这一修订作为 Lifecycle Contract V1.2 的定向变更，保留 V1.1 的历史冻结版本。C19 修订通过后，重新执行专项测试。
