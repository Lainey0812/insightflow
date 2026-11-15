# Phase 2-B1 与 Phase 2-A 设计的差异

本轮任务书只交付两个列表接口。下列差异按任务书实现，没有补做设计稿里的详情接口。

1. 设计稿 Phase 2-B1 写了 `list_runs`、`get_run`、`list_datasets`、`get_dataset` 四个接口。本轮任务书只要求两个列表，并禁止 Run Detail。因此没有实现运行详情和数据集详情。
2. 分页参数用任务书的 `page` 和 `page_size`（`page` 从 1 起，`page_size` 为 1–100，默认 20）。设计稿写的是与旧 Admin 一致的 `limit` 和 `offset`。
3. 字段名按任务书：`run_type`、`lifecycle_status`、`integrity_status`、`freeze_status=UNDECLARED`。设计稿用 `run_kind`、`lifecycle`、`integrity`、`NOT_DECLARED`。
4. 不可读运行和重复 Run ID 放在 `discovery_warnings`。重复 ID 的每一份都排除，不挑选其中一份。设计稿把它们分成 `unreadable` 和 `conflicts` 两个数组。
5. 运行目录如果是符号链接，一律不跟随，包括链接目标仍在根目录内的情况。设计稿允许解析后仍在根内的链接。任务书要求拒绝越界链接；全部不跟随更窄，避免通过链接读到根外。
6. 数据集除 `related_run_count` 外，另有 `hash_matched_run_count` 和 `weak_path_run_count`。任务书要求区分“哈希已核对”和“只凭配置根目录建立的弱关联”。`related_run_count` 是两者之和。哈希相同但记录的 dataset id 不同的运行不计入，并产生 `dataset_hash_id_conflict`。
7. Golden 文件没有 `version`，`dataset_version` 为 null。TC 的 `cases.json` 有 `suite_version`，数据集的 id 和 version 都取这个字段。运行列表不把数据集版本回填到运行上；历史运行自己的 `dataset_version` 仍是 null。文件哈希不写入 version。
8. 列表不返回 `list_state`、`trust` 和指标。设计稿把这些放在列表项上，本轮任务书没有要求。

`case_count` 是已执行、缺失和未开始的 case 数之和。`evaluated_case_count` 是已有 Evaluator 结果的执行数。TC 历史运行 `rg_20261112-133157_f04289` 因此是 15 和 1：14 条记录为 `not_run`。
