# Phase 2-B2 与 Phase 2-A 设计、Phase 2-B1 的差异

1. 运行 ID、Case ID、Dataset ID 格式不合法时返回 422，与任务书“422：参数非法”一致。设计稿写的是 404。格式合法但找不到的仍返回 404。
2. 证据缺失不返回 404。接口返回 200，`status` 为 `NOT_RECORDED`（该格式没有保存，或文件不存在）或 `UNAVAILABLE`（TC 的 trace 只在 SQLite 中、JSON 损坏、引用越界或是符号链接）。设计稿用 404 `EVIDENCE_NOT_RECORDED` 和 409 `EVIDENCE_UNREADABLE`/`EVIDENCE_NOT_EXPOSED`。任务书要求“优先返回结构化状态和错误原因”。
3. 证据种类按任务书：`trace`、`plan`、`profile`、`engine`、`result_tables`、`evaluator_refs`。设计稿的 `case_record` 没有实现；原始标签已经在 Case Detail 的 `legacy_labels` 中按白名单返回。
4. 证据超过限制时直接返回 413，不做尾部截断。限制有三项：原始文件 2 MiB、脱敏后响应 1 MiB、JSON 值 50000 个。嵌套深度超过 24 层时，在该位置换成截断标记，并在 `depth_truncated_paths` 中列出。
5. LLM endpoint 按 REQ-0147 Q5 整项删除，不保留 host。
6. 数据集关联修正了 B1 的分类。B1 把“记录了别的哈希”的运行算成弱关联。B2 改为三类：`hash_match`（哈希相同）、`weak_path`（运行没有记录哈希，只凭同一配置根目录关联）、`hash_mismatch`（运行记录了不同的哈希）。列表的 `related_run_count` 只计前两类，并新增 `hash_mismatch_run_count`。B1 测试中两处弱关联预期随之改变。
7. 历史格式没有逐 Case 的完整性记录。Case 级 `case_integrity` 显示运行级的 `UNVERIFIED`。
8. 运行详情的 `recorded_distribution` 是全部已记录 Case 的分布，包括完整性校验失败的 Case；可信指标在 `metrics` 中单独给出，并标 `trust`。
